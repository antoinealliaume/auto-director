# -*- coding: utf-8 -*-
import json, os, tempfile, threading, time, uuid
from http.server import BaseHTTPRequestHandler,HTTPServer
from pathlib import Path
from psycopg.types.json import Jsonb
from .config import db,queue,run,FFMPEG,ENGINE_VERSION,RENDER_WIDTH,RENDER_HEIGHT,OPENAI_API_KEY,SELF_TEST,ensure_schema,recover_stale_jobs
from .job import process_job

def self_test():
    pid=aid=jid=None
    try:
        print('SELFTEST V8 start',flush=True)
        with tempfile.TemporaryDirectory(prefix='adv8_test_') as td:
            p=Path(td)/'synthetic.mp4'
            run([FFMPEG,'-y','-f','lavfi','-i','testsrc2=size=640x360:rate=24','-f','lavfi','-i','sine=frequency=550:sample_rate=44100','-t','5','-c:v','libx264','-pix_fmt','yuv420p','-c:a','aac',str(p)],120)
            blob=p.read_bytes()
        pid,aid,jid=uuid.uuid4(),uuid.uuid4(),uuid.uuid4()
        with db() as c:
            c.execute("insert into projects(id,name,description) values(%s,'__SELFTEST_V8__','automatic V8 validation')",(pid,))
            c.execute("insert into assets(id,project_id,name,content_type,size,role,kind,data,metadata) values(%s,%s,'selftest-v8.mp4','video/mp4',%s,'source','source',%s,'{}'::jsonb)",(aid,pid,len(blob),blob))
            settings={'assetIds':[str(aid)],'captions':True,'voiceover':'off','autoRevision':False,'targetDuration':8}
            c.execute("insert into jobs(id,project_id,status,stage,progress,message,variants,settings) values(%s,%s,'queued','queued',0,'selftest V8',1,%s)",(jid,pid,Jsonb(settings)))
        process_job(str(jid))
        with db() as c:row=c.execute('select status,critic_score,output_asset_ids from jobs where id=%s',(jid,)).fetchone()
        ok=bool(row and row[0]=='done' and row[2])
        print('SELFTEST V8 PASS '+str(row[:2]) if ok else 'SELFTEST V8 FAIL '+str(row),flush=True)
    except Exception as e:
        print('SELFTEST V8 FAIL '+repr(e),flush=True)
    finally:
        if pid:
            try:
                with db() as c:c.execute('delete from projects where id=%s',(pid,))
            except Exception:pass

class Health(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path!='/health':self.send_response(404);self.end_headers();return
        db_ok=q_ok=ff_ok=False
        try:
            with db() as c:c.execute('select 1');db_ok=True
        except Exception:pass
        try:q_ok=bool(queue.ping())
        except Exception:pass
        try:ff_ok=run([FFMPEG,'-version'],15,False).returncode==0
        except Exception:pass
        body=json.dumps({'ok':db_ok and q_ok and ff_ok,'worker':'ready','engine':ENGINE_VERSION,'database':db_ok,'queue':q_ok,'ffmpeg':ff_ok,'resolution':[RENDER_WIDTH,RENDER_HEIGHT],'ai':'openai' if OPENAI_API_KEY else 'local-v8','capabilities':['moment-ranker','style-fingerprint','multi-plan-director','performance-memory','retention-critic','auto-revision','job-recovery']}).encode()
        self.send_response(200 if db_ok and q_ok and ff_ok else 503);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
    def log_message(self,*args):pass

def health_server():
    HTTPServer(('0.0.0.0',int(os.environ.get('PORT','10000'))),Health).serve_forever()

def main():
    ensure_schema();recover_stale_jobs();threading.Thread(target=health_server,daemon=True).start()
    print(f'Auto Director V{ENGINE_VERSION} ready {RENDER_WIDTH}x{RENDER_HEIGHT} ai={bool(OPENAI_API_KEY)}',flush=True)
    if SELF_TEST:self_test()
    while True:
        try:
            item=queue.brpop('auto_director:jobs',timeout=5)
            if item:process_job(item[1])
        except Exception as e:
            print('V8 worker loop error',repr(e),flush=True);time.sleep(2)
