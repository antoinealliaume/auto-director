# -*- coding: utf-8 -*-
import os, subprocess, uuid
from pathlib import Path
import psycopg, redis
from imageio_ffmpeg import get_ffmpeg_exe
from psycopg.types.json import Jsonb
from storage_schema import ensure_storage_schema

ENGINE_VERSION = '8.6'
ANALYSIS_VERSION = 4
REMOTE_WORKER_MODE = os.environ.get('REMOTE_WORKER_MODE','0') == '1'
DATABASE_URL = os.environ.get('DATABASE_URL','')
REDIS_URL = os.environ.get('REDIS_URL','')
OPENAI_API_KEY = os.environ.get('OPENAI_API_KEY','')
AI_MODEL = os.environ.get('AI_MODEL','gpt-5.6-luna')
RENDER_WIDTH = max(480,min(1080,int(os.environ.get('RENDER_WIDTH','720'))))
RENDER_HEIGHT = max(854,min(1920,int(os.environ.get('RENDER_HEIGHT','1280'))))
RENDER_FPS = max(24,min(30,int(os.environ.get('RENDER_FPS','30'))))
FFMPEG_THREADS = max(1,min(6,int(os.environ.get('FFMPEG_THREADS','2'))))
MAX_REVISIONS = max(0,min(2,int(os.environ.get('MAX_REVISIONS','1'))))
MOMENT_SAMPLES = max(4,min(10,int(os.environ.get('MOMENT_SAMPLES','7'))))
SELF_TEST = os.environ.get('SELF_TEST_ON_START','0') == '1'
FFMPEG = get_ffmpeg_exe()
queue = redis.from_url(REDIS_URL,decode_responses=True) if REDIS_URL else None


def db():
    if not DATABASE_URL:
        raise RuntimeError('DATABASE_URL unavailable in HTTPS remote-worker mode')
    return psycopg.connect(DATABASE_URL)


def run(cmd,timeout=900,check=True):
    p=subprocess.run(cmd,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,timeout=timeout)
    if check and p.returncode:
        raise RuntimeError((p.stderr or p.stdout or '')[-4000:])
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
    ]
    with db() as c:
        for s in stmts:
            try:c.execute(s)
            except Exception:pass
        try:ensure_storage_schema(c)
        except Exception:pass
        try:c.execute("delete from projects where name in ('__SELFTEST__','__SELFTEST_V8__')")
        except Exception:pass


def update_job(jid,status,stage,progress,message,score=None,revision=None,strategy=None,brief=None):
    if REMOTE_WORKER_MODE:return
    sets=['status=%s','stage=%s','progress=%s','message=%s','updated_at=now()']
    vals=[status,stage,int(progress),str(message)[:500]]
    if score is not None:
        sets.append('critic_score=%s');vals.append(float(score))
    if revision is not None:
        sets.append('revision_count=%s');vals.append(int(revision))
    if strategy is not None:
        sets.append('strategy=%s');vals.append(str(strategy)[:120])
    if brief is not None:
        sets.append('creative_brief=%s');vals.append(Jsonb(brief))
    vals.append(jid)
    with db() as c:
        c.execute('update jobs set '+','.join(sets)+' where id=%s',vals)
        try:c.execute('insert into job_events(job_id,stage,message) values(%s,%s,%s)',(jid,stage,str(message)[:500]))
        except Exception:pass


def cancelled(jid):
    if REMOTE_WORKER_MODE:return False
    with db() as c:
        row=c.execute('select status from jobs where id=%s',(jid,)).fetchone()
    return bool(row and row[0]=='cancelled')


def save_asset_analysis(asset_id,metadata,analysis):
    if REMOTE_WORKER_MODE:return
    meta=dict(metadata or {})
    meta['directorAnalysis']={k:v for k,v in analysis.items() if k not in {'id','name','role'}}
    meta['engineVersion']=ENGINE_VERSION
    with db() as c:
        c.execute('update assets set metadata=%s where id=%s',(Jsonb(meta),uuid.UUID(str(asset_id))))


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
        if queue.lpos('auto_director:jobs',jid) is None:
            queue.lpush('auto_director:jobs',jid)
            return True
    except Exception:
        try:queue.lpush('auto_director:jobs',jid);return True
        except Exception:pass
    return False


def recover_stale_jobs():
    if REMOTE_WORKER_MODE or queue is None:return
    recovered=[]
    with db() as c:
        stale=c.execute("select id from jobs where status='running' and updated_at < now()-interval '20 minutes' limit 50").fetchall()
        for (jid,) in stale:
            c.execute("update jobs set status='queued',stage='queued',message='Reprise automatique après interruption',progress=0,updated_at=now() where id=%s",(jid,))
            try:queue.delete('autodirector:lock:'+str(jid))
            except Exception:pass
            recovered.append(jid)
        queued=c.execute("select id from jobs where status='queued' order by created_at asc limit 200").fetchall()
    for (jid,) in queued:
        if _enqueue_if_missing(jid):recovered.append(jid)
    if recovered:
        print(f'Queue recovery: {len(set(map(str,recovered)))} durable job(s) available',flush=True)
