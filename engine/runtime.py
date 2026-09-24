# -*- coding: utf-8 -*-
import json
import os
import tempfile
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler,HTTPServer
from pathlib import Path

from psycopg.types.json import Jsonb

from .config import db,queue,run,FFMPEG,ENGINE_VERSION,RENDER_WIDTH,RENDER_HEIGHT,SELF_TEST,ensure_schema,recover_stale_jobs,promote_due_retries,FFMPEG_THREADS
from .job import process_job

WORKER_KIND=os.environ.get('WORKER_KIND','cloud').strip().lower()
if WORKER_KIND not in {'local','cloud'}:WORKER_KIND='cloud'
HEARTBEAT_PREFIX='autodirector:worker:'
LOCAL_HEARTBEAT_KEY=HEARTBEAT_PREFIX+'local:heartbeat'
CLOUD_HEARTBEAT_KEY=HEARTBEAT_PREFIX+'cloud:heartbeat'
PROFILE_NAME=os.environ.get('PROFILE_NAME','cloud-safe' if WORKER_KIND!='local' else 'safe-unknown')
LOCAL_VLM_URL=os.environ.get('LOCAL_VLM_URL','').strip()
LOCAL_VLM_MODEL=os.environ.get('LOCAL_VLM_MODEL','qwen2.5vl:3b').strip()
RENDER_FPS=max(24,min(30,int(os.environ.get('RENDER_FPS','30'))))
RECOVERY_SECONDS=max(30,min(300,int(os.environ.get('QUEUE_RECOVERY_SECONDS','60'))))


def self_test():
    pid=aid=jid=None
    try:
        print(f'SELFTEST V{ENGINE_VERSION} start',flush=True)
        with tempfile.TemporaryDirectory(prefix='autodirector_selftest_') as td:
            p=Path(td)/'synthetic.mp4'
            run([FFMPEG,'-y','-f','lavfi','-i','testsrc2=size=640x360:rate=24','-f','lavfi','-i','sine=frequency=550:sample_rate=44100','-t','5','-c:v','libx264','-pix_fmt','yuv420p','-c:a','aac',str(p)],120)
            blob=p.read_bytes()
        pid,aid,jid=uuid.uuid4(),uuid.uuid4(),uuid.uuid4()
        with db() as c:
            c.execute("insert into projects(id,name,description) values(%s,%s,%s)",(pid,'__SELFTEST__',f'automatic V{ENGINE_VERSION} validation'))
            c.execute("insert into assets(id,project_id,name,content_type,size,role,kind,data,metadata) values(%s,%s,'selftest.mp4','video/mp4',%s,'source','source',%s,'{}'::jsonb)",(aid,pid,len(blob),blob))
            settings={'assetIds':[str(aid)],'captions':True,'voiceover':'off','autoRevision':False,'targetDuration':8}
            c.execute("insert into jobs(id,project_id,status,stage,progress,message,variants,settings) values(%s,%s,'queued','queued',0,%s,1,%s)",(jid,pid,f'selftest V{ENGINE_VERSION}',Jsonb(settings)))
        process_job(str(jid))
        with db() as c:row=c.execute('select status,critic_score,output_asset_ids from jobs where id=%s',(jid,)).fetchone()
        ok=bool(row and row[0] in {'done','completed'} and row[2])
        print(f'SELFTEST V{ENGINE_VERSION} PASS '+str(row[:2]) if ok else f'SELFTEST V{ENGINE_VERSION} FAIL '+str(row),flush=True)
    except Exception as e:
        print(f'SELFTEST V{ENGINE_VERSION} FAIL '+repr(e),flush=True)
    finally:
        if pid:
            try:
                with db() as c:c.execute('delete from projects where id=%s',(pid,))
            except Exception:pass


def heartbeat_payload():
    return {
        'kind':WORKER_KIND,'engine':ENGINE_VERSION,'profile':PROFILE_NAME,
        'resolution':[RENDER_WIDTH,RENDER_HEIGHT],'fps':RENDER_FPS,'ffmpegThreads':FFMPEG_THREADS,
        'localAI':bool(LOCAL_VLM_URL) if WORKER_KIND=='local' else False,
        'model':LOCAL_VLM_MODEL if WORKER_KIND=='local' and LOCAL_VLM_URL else None,
        'updatedAt':int(time.time()),'protocol':2,
    }


def heartbeat_key(kind):return LOCAL_HEARTBEAT_KEY if kind=='local' else CLOUD_HEARTBEAT_KEY


def worker_heartbeat():
    key=heartbeat_key(WORKER_KIND)
    while True:
        try:queue.set(key,json.dumps(heartbeat_payload()),ex=20)
        except Exception:pass
        time.sleep(5)


def read_worker_heartbeat(kind):
    try:
        raw=queue.get(heartbeat_key(kind))
        if not raw:return None
        value=json.loads(raw)
        return value if isinstance(value,dict) else None
    except Exception:return None


class Health(BaseHTTPRequestHandler):
    def _headers(self,status,length):
        self.send_response(status);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(length));self.send_header('Cache-Control','no-store');self.end_headers()
    def do_GET(self):
        if self.path!='/health':
            body=b'{"detail":"not found"}';self._headers(404,len(body));self.wfile.write(body);return
        db_ok=q_ok=ff_ok=False
        try:
            with db() as c:c.execute('select 1');db_ok=True
        except Exception:pass
        try:q_ok=bool(queue.ping())
        except Exception:pass
        try:ff_ok=run([FFMPEG,'-version'],15,False).returncode==0
        except Exception:pass
        local_info=read_worker_heartbeat('local');cloud_info=read_worker_heartbeat('cloud')
        try:queue_depth=int(queue.llen('auto_director:jobs'))
        except Exception:queue_depth=None
        body=json.dumps({
            'ok':db_ok and q_ok and ff_ok,'worker':'ready','workerKind':WORKER_KIND,
            'activeWorker':'local' if local_info else ('cloud' if cloud_info else WORKER_KIND),
            'localWorkerOnline':bool(local_info),'cloudWorkerOnline':bool(cloud_info),
            'localWorker':local_info,'cloudWorker':cloud_info,'engine':ENGINE_VERSION,
            'database':db_ok,'queue':q_ok,'queueDepth':queue_depth,'ffmpeg':ff_ok,
            'resolution':[RENDER_WIDTH,RENDER_HEIGHT],'fps':RENDER_FPS,'ffmpegThreads':FFMPEG_THREADS,
            'ai':'local-vlm' if LOCAL_VLM_URL else f'director-v{ENGINE_VERSION}',
            'capabilities':['moment-ranker','style-fingerprint','multi-plan-director','performance-memory','retention-critic','auto-revision','job-recovery','local-worker-priority','adaptive-safe-mode','durable-queue-recovery','worker-heartbeats']
        }).encode()
        self._headers(200 if db_ok and q_ok and ff_ok else 503,len(body));self.wfile.write(body)
    def log_message(self,*args):pass


def health_server():HTTPServer(('0.0.0.0',int(os.environ.get('PORT','10000'))),Health).serve_forever()


def next_job():
    if WORKER_KIND=='local':
        item=queue.brpop('auto_director:jobs',timeout=5);return item[1] if item else None
    try:
        if queue.exists(LOCAL_HEARTBEAT_KEY):time.sleep(5);return None
    except Exception:pass
    item=queue.rpop('auto_director:jobs')
    if not item:time.sleep(4)
    return item


def main():
    ensure_schema();recover_stale_jobs()
    threading.Thread(target=health_server,daemon=True).start();threading.Thread(target=worker_heartbeat,daemon=True).start()
    print(f'Auto Director V{ENGINE_VERSION} ready {RENDER_WIDTH}x{RENDER_HEIGHT}@{RENDER_FPS} kind={WORKER_KIND} profile={PROFILE_NAME} localAI={bool(LOCAL_VLM_URL)}',flush=True)
    if SELF_TEST:self_test()
    last_recovery=time.monotonic()
    while True:
        try:
            promote_due_retries()
            if WORKER_KIND=='cloud' and time.monotonic()-last_recovery>=RECOVERY_SECONDS:
                recover_stale_jobs();last_recovery=time.monotonic()
            jid=next_job()
            if jid:process_job(jid)
        except Exception as e:
            print(f'V{ENGINE_VERSION} worker loop error',repr(e),flush=True);time.sleep(2)


if __name__=='__main__':main()
