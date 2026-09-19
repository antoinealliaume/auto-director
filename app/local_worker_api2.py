# -*- coding: utf-8 -*-
import hashlib
import hmac
import json
import os
import secrets
import tempfile
import time
import uuid
from pathlib import Path
from typing import Optional

import psycopg
import redis
from fastapi import File, Form, Header, HTTPException, Query, UploadFile
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field
from psycopg.types.json import Jsonb

import storage_backend as media_store
from storage_schema import ensure_storage_schema
from engine.memory import load_context
from .job_lifecycle import WORKER_PROTOCOL, retry_plan, worker_compatibility
from .structured_logging import log_event

DATABASE_URL = os.environ.get('DATABASE_URL','')
REDIS_URL = os.environ.get('REDIS_URL','')
TOKEN_TTL = max(3600,min(7*24*3600,int(os.environ.get('WORKER_TOKEN_TTL','86400'))))
QUEUE_KEY='auto_director:jobs'
RETRY_KEY='auto_director:jobs:retry'
LOCAL_HEARTBEAT='autodirector:worker:local:heartbeat'
MAX_OUTPUT_MB=max(20,min(250,int(os.environ.get('MAX_REMOTE_OUTPUT_MB','120'))))


def db(): return psycopg.connect(DATABASE_URL)
def rq(): return redis.from_url(REDIS_URL,decode_responses=True)

def _read_worker_info(client):
    try:
        value=json.loads(client.get(LOCAL_HEARTBEAT) or '{}')
        return value if isinstance(value,dict) else None
    except Exception:return None

def secret():
    v=os.environ.get('TOKEN_SECRET','')
    if v:return v
    from .main import TOKEN_SECRET
    return TOKEN_SECRET

def sign(raw): return hmac.new(secret().encode(),raw.encode(),hashlib.sha256).hexdigest()

def require_studio(auth):
    token=auth[7:] if auth and auth.startswith('Bearer ') else ''
    from .main import verify_token
    if not token or not verify_token(token):raise HTTPException(401,'Session Studio invalide')

def make_worker_token(wid):
    raw=f'w.{int(time.time())}.{wid}.{secrets.token_urlsafe(24)}'
    return raw+'.'+sign(raw)

def require_worker(auth):
    token=auth[7:] if auth and auth.startswith('Bearer ') else ''
    raw,sep,sig=token.rpartition('.')
    if not sep or not hmac.compare_digest(sign(raw),sig):raise HTTPException(401,'Jeton worker invalide')
    p=raw.split('.')
    if len(p)!=4 or p[0]!='w':raise HTTPException(401,'Jeton worker invalide')
    try:age=int(time.time())-int(p[1])
    except Exception:raise HTTPException(401,'Jeton worker invalide')
    if age<0 or age>TOKEN_TTL:raise HTTPException(401,'Jeton worker expiré')
    return p[2]

def ensure_schema():
    with db() as c:
        ensure_storage_schema(c)
        c.execute('''create table if not exists worker_leases(
            job_id uuid primary key references jobs(id) on delete cascade,
            worker_id text not null,lease_expires timestamptz not null,
            updated_at timestamptz not null default now())''')
        c.execute('create index if not exists idx_worker_leases_expiry on worker_leases(lease_expires)')

def check_lease(jid,wid,refresh=True):
    ensure_schema()
    with db() as c:
        row=c.execute('''select j.project_id,j.settings,j.status from worker_leases l join jobs j on j.id=l.job_id
            where l.job_id=%s and l.worker_id=%s and l.lease_expires>now()''',(jid,wid)).fetchone()
        if not row:raise HTTPException(409,'Lease worker absent ou expiré')
        if refresh:c.execute("update worker_leases set lease_expires=now()+interval '35 minutes',updated_at=now() where job_id=%s and worker_id=%s",(jid,wid))
        return row

class SessionIn(BaseModel): label:str=Field(default='windows-pc',max_length=80)
class HeartbeatIn(BaseModel):
    engine:str=Field(default='8.6',max_length=32);profile:str=Field(default='safe-unknown',max_length=80)
    resolution:list[int]=Field(default_factory=lambda:[720,1280]);fps:int=24;ffmpegThreads:int=2;localAI:bool=False;model:Optional[str]=None
    protocol:int=WORKER_PROTOCOL;agentVersion:Optional[str]=Field(default=None,max_length=32)
class ProgressIn(BaseModel):
    stage:str=Field(default='running',max_length=80);progress:int=0;message:str=Field(default='',max_length=500)
    score:Optional[float]=None;revision:Optional[int]=None;strategy:Optional[str]=None;brief:Optional[dict]=None
class CompleteIn(BaseModel):
    score:float=0;revisionCount:int=0;strategy:str=Field(default='',max_length=120);message:str=Field(default='Rendu local terminé',max_length=500)
class FailIn(BaseModel): error:str=Field(default='Erreur worker local',max_length=500)


def attach(app):
    async def session(x:SessionIn,authorization:Optional[str]=Header(None)):
        require_studio(authorization);wid=uuid.uuid4().hex
        return JSONResponse({'workerToken':make_worker_token(wid),'workerId':wid,'expiresIn':TOKEN_TTL,'protocol':2},headers={'Cache-Control':'no-store'})

    async def renew(authorization:Optional[str]=Header(None)):
        wid=require_worker(authorization)
        return JSONResponse({'workerToken':make_worker_token(wid),'workerId':wid,'expiresIn':TOKEN_TTL},headers={'Cache-Control':'no-store'})

    async def heartbeat(x:HeartbeatIn,authorization:Optional[str]=Header(None)):
        wid=require_worker(authorization);res=list(x.resolution or [720,1280]);w=int(res[0]) if len(res)>0 else 720;h=int(res[1]) if len(res)>1 else 1280
        compatibility=worker_compatibility(x.engine,x.protocol)
        payload={'kind':'local','engine':x.engine,'protocol':x.protocol,'agentVersion':x.agentVersion,'compatible':compatibility['compatible'],'compatibilityReason':compatibility['reason'],'profile':x.profile,'resolution':[max(480,min(1080,w)),max(854,min(1920,h))],
                 'fps':max(24,min(30,int(x.fps))),'ffmpegThreads':max(1,min(6,int(x.ffmpegThreads))),
                 'localAI':bool(x.localAI),'model':x.model if x.localAI else None,'workerId':wid,'updatedAt':int(time.time()),'transport':'https'}
        rq().set(LOCAL_HEARTBEAT,json.dumps(payload),ex=20);return {'ok':True,**compatibility}

    async def claim(authorization:Optional[str]=Header(None)):
        wid=require_worker(authorization);ensure_schema();selected=None;lock_key=None;r=rq()
        worker_info=_read_worker_info(r)
        compatibility=worker_compatibility((worker_info or {}).get('engine'),(worker_info or {}).get('protocol'))
        if not compatibility['compatible']:raise HTTPException(409,'Worker incompatible: '+compatibility['reason'])
        with db() as c:
            c.execute('delete from worker_leases where lease_expires<=now()')
            rows=c.execute("select id,project_id,variants,settings from jobs where status='queued' order by created_at asc for update skip locked limit 10").fetchall()
            for row in rows:
                lk='autodirector:lock:'+str(row[0])
                if r.set(lk,'remote:'+wid,nx=True,ex=3600):
                    selected=row;lock_key=lk
                    claimed=c.execute("update jobs set status='claimed',stage='claimed',progress=1,message='Réservé par le worker PC',updated_at=now() where id=%s and status='queued' returning id",(row[0],)).fetchone()
                    if not claimed:
                        r.delete(lk);selected=None;lock_key=None;continue
                    c.execute("insert into worker_leases(job_id,worker_id,lease_expires) values(%s,%s,now()+interval '35 minutes') on conflict(job_id) do update set worker_id=excluded.worker_id,lease_expires=excluded.lease_expires,updated_at=now()",(row[0],wid));break
        if not selected:return {'job':None}
        jid,pid,variants,settings=selected;log_event('job.claimed',job_id=str(jid),worker_id=wid,transport='https')
        try:r.lrem(QUEUE_KEY,0,str(jid))
        except Exception:pass
        try:
            with db() as c:
                project=c.execute('select name from projects where id=%s',(pid,)).fetchone();wanted=[uuid.UUID(str(x)) for x in (settings or {}).get('assetIds',[])]
                src=c.execute("select id,name,role,size,content_type,metadata from assets where project_id=%s and kind='source' and id=any(%s)",(pid,wanted)).fetchall() if wanted else []
                refs=c.execute("select id,name,role,size,content_type,metadata from assets where project_id=%s and kind='source' and role='reference' order by created_at desc limit 5",(pid,)).fetchall()
            seen=set();assets=[]
            for row in list(src)+list(refs):
                if row[0] in seen:continue
                seen.add(row[0]);assets.append({'id':str(row[0]),'name':row[1],'role':row[2],'size':int(row[3]),'contentType':row[4],'metadata':row[5] or {}})
            return {'job':{'id':str(jid),'projectId':str(pid),'projectName':project[0] if project else 'Auto Director','variants':int(variants),'settings':settings or {},'assets':assets,'context':load_context(pid)}}
        except Exception:
            try:r.delete(lock_key)
            except Exception:pass
            with db() as c:c.execute("update jobs set status='queued',stage='queued',message='Replacé en file après erreur de claim',updated_at=now() where id=%s",(jid,));c.execute('delete from worker_leases where job_id=%s',(jid,))
            raise

    async def asset(asset_id:str,jobId:str=Query(...),authorization:Optional[str]=Header(None)):
        wid=require_worker(authorization);jid=uuid.UUID(jobId);pid,settings,status=check_lease(jid,wid);aid=uuid.UUID(asset_id)
        allowed={str(x) for x in (settings or {}).get('assetIds',[])}
        with db() as c:
            ensure_storage_schema(c)
            row=c.execute("select name,content_type,data,role,storage_key from assets where id=%s and project_id=%s and kind='source'",(aid,pid)).fetchone()
        if not row or (str(aid) not in allowed and row[3]!='reference'):raise HTTPException(404,'Asset worker introuvable')
        try:payload=media_store.read_asset(row[4],row[2])
        except Exception as exc:raise HTTPException(503,'Média source indisponible') from exc
        return Response(payload,media_type=row[1],headers={'Content-Disposition':f'attachment; filename="{row[0]}"','Cache-Control':'no-store'})

    async def progress(job_id:str,x:ProgressIn,authorization:Optional[str]=Header(None)):
        wid=require_worker(authorization);jid=uuid.UUID(job_id);_,_,status=check_lease(jid,wid)
        if status=='cancelled':raise HTTPException(409,'Job annulé')
        sets=["status='running'",'stage=%s','progress=%s','message=%s','updated_at=now()'];vals=[x.stage,max(0,min(99,int(x.progress))),x.message[:500]]
        if x.score is not None:sets.append('critic_score=%s');vals.append(float(x.score))
        if x.revision is not None:sets.append('revision_count=%s');vals.append(max(0,int(x.revision)))
        if x.strategy is not None:sets.append('strategy=%s');vals.append(str(x.strategy)[:120])
        if x.brief is not None:sets.append('creative_brief=%s');vals.append(Jsonb(x.brief))
        vals.append(jid)
        with db() as c:
            updated=c.execute("update jobs set "+','.join(sets)+" where id=%s and status in ('claimed','running') returning id",vals).fetchone()
            if not updated:raise HTTPException(409,'Job annulé ou déjà terminé')
            c.execute('insert into job_events(job_id,stage,message) values(%s,%s,%s)',(jid,x.stage,x.message[:500]))
        return {'ok':True}

    async def state(job_id:str,authorization:Optional[str]=Header(None)):
        wid=require_worker(authorization);jid=uuid.UUID(job_id);check_lease(jid,wid,False)
        with db() as c:row=c.execute('select status,stage,progress from jobs where id=%s',(jid,)).fetchone()
        return {'status':row[0],'stage':row[1],'progress':row[2]} if row else {'status':'missing'}

    async def output(job_id:str,file:UploadFile=File(...),metadata_json:str=Form('{}'),authorization:Optional[str]=Header(None)):
        wid=require_worker(authorization);jid=uuid.UUID(job_id);pid,_,status=check_lease(jid,wid)
        if status=='cancelled':raise HTTPException(409,'Job annulé')
        limit=MAX_OUTPUT_MB*1024*1024;total=0;tmp_path=None;storage_key=None
        try:
            suffix=Path(file.filename or 'render.mp4').suffix or '.mp4'
            with tempfile.NamedTemporaryFile(prefix='ad_local_output_',suffix=suffix,delete=False) as tmp:
                tmp_path=Path(tmp.name)
                while True:
                    b=await file.read(1024*1024)
                    if not b:break
                    total+=len(b)
                    if total>limit:raise HTTPException(413,f'Rendu > {MAX_OUTPUT_MB} Mo')
                    tmp.write(b)
            if total<=0:raise HTTPException(400,'Rendu vide')
            try:meta=json.loads(metadata_json) if metadata_json else {}
            except Exception:meta={}
            if not isinstance(meta,dict):meta={}
            aid=uuid.uuid4();name=os.path.basename(file.filename or f'AutoDirector_{aid}.mp4')[:180]
            data,storage_key,backend,checksum=media_store.persist_file(pid,aid,'render',name,tmp_path,'video/mp4')
            meta={**meta,'storageBackend':backend,'checksumSha256':checksum}
            try:
                with db() as c:
                    ensure_storage_schema(c)
                    c.execute("insert into assets(id,project_id,name,content_type,size,role,kind,data,metadata,storage_key,storage_backend,checksum_sha256) values(%s,%s,%s,'video/mp4',%s,'render','render',%s,%s,%s,%s,%s)",(aid,pid,name,total,data,Jsonb(meta),storage_key,backend,checksum))
                    updated=c.execute("update jobs set output_asset_ids=array_append(output_asset_ids,%s),updated_at=now() where id=%s and status in ('claimed','running') and not (%s=any(output_asset_ids)) returning id",(aid,jid,aid)).fetchone()
                    if not updated:raise HTTPException(409,'Job annulé ou déjà terminé')
            except Exception:
                if storage_key:
                    try:media_store.delete(storage_key)
                    except Exception:pass
                raise
            return {'ok':True,'assetId':str(aid),'size':total,'storage':backend}
        finally:
            if tmp_path:
                try:tmp_path.unlink(missing_ok=True)
                except Exception:pass

    async def complete(job_id:str,x:CompleteIn,authorization:Optional[str]=Header(None)):
        wid=require_worker(authorization);jid=uuid.UUID(job_id);check_lease(jid,wid)
        with db() as c:
            updated=c.execute("update jobs set status='completed',stage='ready_for_manual_publication',progress=100,message='Rendu terminé · prêt pour publication manuelle',critic_score=%s,revision_count=%s,strategy=%s,updated_at=now() where id=%s and status in ('claimed','running') returning id",(max(0,min(100,float(x.score))),max(0,int(x.revisionCount)),x.strategy[:120],jid)).fetchone()
            if not updated:raise HTTPException(409,'Job annulé ou déjà terminé')
            c.execute("insert into job_events(job_id,stage,message) values(%s,'ready_for_manual_publication','Fichier disponible ; aucune publication automatique')",(jid,));c.execute('delete from worker_leases where job_id=%s',(jid,))
        try:rq().delete('autodirector:lock:'+str(jid))
        except Exception:pass
        log_event('job.completed',job_id=str(jid),worker_id=wid,publication_mode='manual-only');return {'ok':True,'status':'completed','publicationMode':'manual-only'}

    async def fail(job_id:str,x:FailIn,authorization:Optional[str]=Header(None)):
        wid=require_worker(authorization);jid=uuid.UUID(job_id);_,settings,_=check_lease(jid,wid,False);plan=retry_plan(settings)
        with db() as c:
            if plan['allowed']:
                c.execute("update jobs set status='queued',stage='retry_wait',progress=0,message=%s,settings=%s,updated_at=now() where id=%s",(f"Nouvelle tentative {plan['attempt']}/2 dans {plan['delaySeconds']} s · {x.error[:300]}",Jsonb(plan['settings']),jid))
                c.execute("insert into job_events(job_id,stage,message) values(%s,'retry_wait',%s)",(jid,f"Backoff {plan['delaySeconds']} s"))
            else:c.execute("update jobs set status='failed',stage='error',progress=0,message=%s,updated_at=now() where id=%s",(x.error[:500],jid))
            c.execute('delete from worker_leases where job_id=%s',(jid,))
        if plan['allowed']:rq().zadd(RETRY_KEY,{str(jid):time.time()+plan['delaySeconds']})
        try:rq().delete('autodirector:lock:'+str(jid))
        except Exception:pass
        log_event('job.retry.scheduled' if plan['allowed'] else 'job.failed',job_id=str(jid),worker_id=wid,attempt=plan['attempt']);return {'ok':True,'retryScheduled':plan['allowed']}

    app.add_api_route('/api/local-worker/session',session,methods=['POST'],include_in_schema=False)
    app.add_api_route('/api/local-worker/renew',renew,methods=['POST'],include_in_schema=False)
    app.add_api_route('/api/local-worker/heartbeat',heartbeat,methods=['POST'],include_in_schema=False)
    app.add_api_route('/api/local-worker/jobs/claim',claim,methods=['POST'],include_in_schema=False)
    app.add_api_route('/api/local-worker/assets/{asset_id}',asset,methods=['GET'],include_in_schema=False)
    app.add_api_route('/api/local-worker/jobs/{job_id}/progress',progress,methods=['POST'],include_in_schema=False)
    app.add_api_route('/api/local-worker/jobs/{job_id}/state',state,methods=['GET'],include_in_schema=False)
    app.add_api_route('/api/local-worker/jobs/{job_id}/output',output,methods=['POST'],include_in_schema=False)
    app.add_api_route('/api/local-worker/jobs/{job_id}/complete',complete,methods=['POST'],include_in_schema=False)
    app.add_api_route('/api/local-worker/jobs/{job_id}/fail',fail,methods=['POST'],include_in_schema=False)
