# -*- coding: utf-8 -*-
import os
import subprocess
import uuid

import psycopg
import redis
from imageio_ffmpeg import get_ffmpeg_exe
from psycopg.types.json import Jsonb

from storage_schema import ensure_storage_schema

ENGINE_VERSION = '9.2'
ANALYSIS_VERSION = 5
REMOTE_WORKER_MODE = os.environ.get('REMOTE_WORKER_MODE','0') == '1'
DATABASE_URL = os.environ.get('DATABASE_URL','')
REDIS_URL = os.environ.get('REDIS_URL','')
RENDER_WIDTH = max(480,min(1080,int(os.environ.get('RENDER_WIDTH','720'))))
RENDER_HEIGHT = max(854,min(1920,int(os.environ.get('RENDER_HEIGHT','1280'))))
RENDER_FPS = max(24,min(30,int(os.environ.get('RENDER_FPS','30'))))
FFMPEG_THREADS = max(1,min(6,int(os.environ.get('FFMPEG_THREADS','2'))))
RENDER_CRF = max(18,min(24,int(os.environ.get('RENDER_CRF','20'))))
RENDER_PRESET = os.environ.get('RENDER_PRESET','veryfast').strip().lower()
if RENDER_PRESET not in {'ultrafast','superfast','veryfast','faster','fast','medium'}:RENDER_PRESET='veryfast'
MAX_REVISIONS = max(0,min(2,int(os.environ.get('MAX_REVISIONS','1'))))
MOMENT_SAMPLES = max(4,min(12,int(os.environ.get('MOMENT_SAMPLES','7'))))
SELF_TEST = os.environ.get('SELF_TEST_ON_START','0') == '1'
FFMPEG = get_ffmpeg_exe()
queue = redis.from_url(REDIS_URL,decode_responses=True) if REDIS_URL else None
QUEUE_KEY = 'auto_director:jobs'


def db():
    if not DATABASE_URL:raise RuntimeError('DATABASE_URL unavailable in HTTPS remote-worker mode')
    return psycopg.connect(DATABASE_URL)


def run(cmd,timeout=900,check=True):
    p=subprocess.run(cmd,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,timeout=timeout)
    if check and p.returncode:raise RuntimeError((p.stderr or p.stdout or '')[-4000:])
    return p


def ensure_schema():
    if REMOTE_WORKER_MODE:return
    stmts=[
        "alter table projects add column if not exists description text not null default ''",
        "alter table assets add column if not exists metadata jsonb not null default '{}'::jsonb",
        "alter table jobs add column if not exists critic_score double precision",
        "alter table jobs add column if not exists revision_count int not null default 0",
        "alter table jobs add column if not exists strategy text not null default ''",
        "alter table jobs add column if not exists creative_brief jsonb not null default '{}'::jsonb",
        "alter table trends add column if not exists source_url text not null default ''",
        "create table if not exists job_events(id bigserial primary key,job_id uuid references jobs(id) on delete cascade,stage text not null,message text not null,created_at timestamptz not null default now())",
        "create table if not exists worker_leases(job_id uuid primary key references jobs(id) on delete cascade,worker_id text not null,lease_expires timestamptz not null,updated_at timestamptz not null default now())",
        "create index if not exists idx_worker_leases_expiry on worker_leases(lease_expires)",
    ]
    with db() as c:
        for s in stmts:c.execute(s)
        ensure_storage_schema(c)
        c.execute("delete from projects where name in ('__SELFTEST__','__SELFTEST_V8__','__SELFTEST_V9__')")


def update_job(jid,status,stage,progress,message,score=None,revision=None,strategy=None,brief=None):
    if REMOTE_WORKER_MODE:return
    sets=['status=%s','stage=%s','progress=%s','message=%s','updated_at=now()'];vals=[status,stage,int(progress),str(message)[:500]]
    if score is not None:sets.append('critic_score=%s');vals.append(float(score))
    if revision is not None:sets.append('revision_count=%s');vals.append(int(revision))
    if strategy is not None:sets.append('strategy=%s');vals.append(str(strategy)[:120])
    if brief is not None:sets.append('creative_brief=%s');vals.append(Jsonb(brief))
    vals.append(jid)
    with db() as c:
        c.execute('update jobs set '+','.join(sets)+' where id=%s',vals)
        c.execute('insert into job_events(job_id,stage,message) values(%s,%s,%s)',(jid,stage,str(message)[:500]))


def cancelled(jid):
    if REMOTE_WORKER_MODE:return False
    with db() as c:row=c.execute('select status from jobs where id=%s',(jid,)).fetchone()
    return bool(row and row[0]=='cancelled')


def save_asset_analysis(asset_id,metadata,analysis):
    if REMOTE_WORKER_MODE:return
    meta=dict(metadata or {});meta['directorAnalysis']={k:v for k,v in analysis.items() if k not in {'id','name','role'}};meta['engineVersion']=ENGINE_VERSION
    with db() as c:c.execute('update assets set metadata=%s where id=%s',(Jsonb(meta),uuid.UUID(str(asset_id))))


def acquire_job_lock(jid,ttl=3600):
    if queue is None:return True
    return bool(queue.set('autodirector:lock:'+str(jid),'1',nx=True,ex=ttl))


def release_job_lock(jid):
    if queue is None:return
    try:queue.delete('autodirector:lock:'+str(jid))
    except Exception:pass


def _enqueue_if_missing(jid):
    if queue is None:return False
    jid=str(jid)
    try:
        if queue.lpos(QUEUE_KEY,jid) is None:queue.lpush(QUEUE_KEY,jid);return True
    except Exception:
        try:queue.lpush(QUEUE_KEY,jid);return True
        except Exception:pass
    return False


def recover_stale_jobs():
    """Rebuild the volatile Redis queue from PostgreSQL without stealing valid leases."""
    if REMOTE_WORKER_MODE or queue is None:return 0
    recovered=[]
    with db() as c:
        c.execute('delete from worker_leases where lease_expires<=now()')
        stale=c.execute("""
            select j.id from jobs j
            left join worker_leases l on l.job_id=j.id and l.lease_expires>now()
            where j.status='running'
              and j.updated_at < now()-interval '30 minutes'
              and l.job_id is null
            order by j.updated_at asc limit 50
        """).fetchall()
        for (jid,) in stale:
            c.execute("update jobs set status='queued',stage='queued',message='Reprise automatique après interruption',progress=0,updated_at=now() where id=%s",(jid,))
            try:queue.delete('autodirector:lock:'+str(jid))
            except Exception:pass
            recovered.append(jid)
        queued=c.execute("select id from jobs where status='queued' order by created_at asc limit 200").fetchall()
    for (jid,) in queued:
        try:queue.delete('autodirector:lock:'+str(jid))
        except Exception:pass
        if _enqueue_if_missing(jid):recovered.append(jid)
    count=len(set(map(str,recovered)))
    if count:print(f'Queue recovery: {count} durable job(s) available',flush=True)
    return count
