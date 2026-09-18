# -*- coding: utf-8 -*-
import hashlib
import hmac
import json
import os
import secrets
import time
import uuid
from typing import Optional

import psycopg
import redis
from fastapi import File, Form, Header, HTTPException, Query, UploadFile
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field
from psycopg.types.json import Jsonb

from engine.memory import load_context

DATABASE_URL = os.environ.get('DATABASE_URL','')
REDIS_URL = os.environ.get('REDIS_URL','')
TOKEN_TTL = max(3600,min(7*24*3600,int(os.environ.get('WORKER_TOKEN_TTL','86400'))))
QUEUE_KEY='auto_director:jobs'
LOCAL_HEARTBEAT='autodirector:worker:local:heartbeat'
MAX_OUTPUT_MB=max(20,min(250,int(os.environ.get('MAX_REMOTE_OUTPUT_MB','120'))))


def db(): return psycopg.connect(DATABASE_URL)
def rq(): return redis.from_url(REDIS_URL,decode_responses=True)

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
        payload={'kind':'local','engine':x.engine,'profile':x.profile,'resolution':[max(480,min(1080,w)),max(854,min(1920,h))],
                 'fps':max(24,min(30,int(x.fps))),'ffmpegThreads':max(1,min(6,int(x.ffmpegThreads))),
                 'localAI':bool(x.localAI),'model':x.model if x.localAI else None,'workerId':wid,'updatedAt':int(time.time()),'transport':'https'}
        rq().set(LOCAL_HEARTBEAT,json.dumps(payload),ex=20);return {'ok':True}

    async def claim(authorization:Optional[str]=Header(None)):
        wid=require_worker(authorization);ensure_schema();selected=None;lock_key=None;r=rq()
        with db() as c:
            c.execute('delete from worker_leases where lease_expires<=now()')
            rows=c.execute("select id,project_id,variants,settings from jobs where status='queued' order by created_at asc for update skip locked limit 10").fetchall()
            for row in rows:
                lk='autodirector:lock:'+str(row[0])
                if r.set(lk,'remote:'+wid,nx=True,ex=3600):
                    selected=row;lock_key=lk
                    c.execute("update jobs set status='running',stage='local_claim',progress=1,message='Pris par le worker PC',updated_at=now() where id=%s",(row[0],))
                    c.execute("insert into worker_leases(job_id,worker_id,lease_expires) values(%s,%s,now()+interval '35 minutes') on conflict(job_id) do update set worker_id=excluded.worker_id,lease_expires=excluded.lease_expires,updated_at=now()",(row[0],wid));break
        if not selected:return {'job':None}
        jid,pid,variants,settings=selected
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
        with db() as c:row=c.execute("select name,content_type,data,role from assets where id=%s and project_id=%s and kind='source'",(aid,pid)).fetchone()
        if not row or (str(aid) not in allowed and row[3]!='reference'):raise HTTPException(404,'Asset worker introuvable')
        return Response(bytes(row[2]),media_type=row[1],headers={'Content-Disposition':f'attachment; filename="{row[0]}"','Cache-Control':'no-store'})

    async def progress(job_id:str,x:ProgressIn,authorization:Optional[str]=Header(None)):
        wid=require_worker(authorization);jid=uuid.UUID(job_id);_,_,status=check_lease(jid,wid)
        if status=='cancelled':raise HTTPException(409,'Job annulé')
        sets=["status='running'",'stage=%s','progress=%s','message=%s','updated_at=now()'];vals=[x.stage,max(0,min(99,int(x.progress))),x.message[:500]]
        if x.score is not None:sets.append('critic_score=%s');vals.append(float(x.score))
        if x.revision is not None:sets.append('revision_count=%s');vals.append(max(0,int(x.revision)))
        if x.strategy is not None:sets.append('strategy=%s');vals.append(str(x.strategy)[:120])
        if x.brief is not None:sets.append('creative_brief=%s');vals.append(Jsonb(x.brief))
        vals.append(jid)
        with db() as c:c.execute('update jobs set '+','.join(sets)+' where id=%s',vals);c.execute('insert into job_events(job_id,stage,message) values(%s,%s,%s)',(jid,x.stage,x.message[:500]))
        return {'ok':True}

    async def state(job_id:str,authorization:Optional[str]=Header(None)):
        wid=require_worker(authorization);jid=uuid.UUID(job_id);check_lease(jid,wid,False)
        with db() as c:row=c.execute('select status,stage,progress from jobs where id=%s',(jid,)).fetchone()
        return {'status':row[0],'stage':row[1],'progress':row[2]} if row else {'status':'missing'}

    async def output(job_id:str,file:UploadFile=File(...),metadata_json:str=Form('{}'),authorization:Optional[str]=Header(None)):
        wid=require_worker(authorization);jid=uuid.UUID(job_id);pid,_,status=check_lease(jid,wid)
        if status=='cancelled':raise HTTPException(409,'Job annulé')
        limit=MAX_OUTPUT_MB*1024*1024;parts=[];total=0
        while True:
            b=await file.read(1024*1024)
            if not b:break
            total+=len(b)
            if total>limit:raise HTTPException(413,f'Rendu > {MAX_OUTPUT_MB} Mo')
            parts.append(b)
        if not parts:raise HTTPException(400,'Rendu vide')
        try:meta=json.loads(metadata_json) if metadata_json else {}
        except Exception:meta={}
        if not isinstance(meta,dict):meta={}
        aid=uuid.uuid4();name=os.path.basename(file.filename or f'AutoDirector_{aid}.mp4')[:180];blob=b''.join(parts)
        with db() as c:
            c.execute("insert into assets(id,project_id,name,content_type,size,role,kind,data,metadata) values(%s,%s,%s,'video/mp4',%s,'render','render',%s,%s)",(aid,pid,name,len(blob),blob,Jsonb(meta)))
            c.execute("update jobs set output_asset_ids=array_append(output_asset_ids,%s),updated_at=now() where id=%s and not (%s=any(output_asset_ids))",(aid,jid,aid))
        return {'ok':True,'assetId':str(aid),'size':len(blob)}

    async def complete(job_id:str,x:CompleteIn,authorization:Optional[str]=Header(None)):
        wid=require_worker(authorization);jid=uuid.UUID(job_id);check_lease(jid,wid)
        with db() as c:
            c.execute("update jobs set status='done',stage='complete',progress=100,message=%s,critic_score=%s,revision_count=%s,strategy=%s,updated_at=now() where id=%s",(x.message[:500],max(0,min(100,float(x.score))),max(0,int(x.revisionCount)),x.strategy[:120],jid));c.execute('delete from worker_leases where job_id=%s',(jid,))
        try:rq().delete('autodirector:lock:'+str(jid))
        except Exception:pass
        return {'ok':True}

    async def fail(job_id:str,x:FailIn,authorization:Optional[str]=Header(None)):
        wid=require_worker(authorization);jid=uuid.UUID(job_id);check_lease(jid,wid,False)
        with db() as c:c.execute("update jobs set status='failed',stage='error',progress=0,message=%s,updated_at=now() where id=%s",(x.error[:500],jid));c.execute('delete from worker_leases where job_id=%s',(jid,))
        try:rq().delete('autodirector:lock:'+str(jid))
        except Exception:pass
        return {'ok':True}

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
