import asyncio,os,subprocess,tempfile,uuid
from pathlib import Path
import psycopg,redis
from edge_tts import Communicate
from imageio_ffmpeg import get_ffmpeg_exe

DATABASE_URL=os.environ['DATABASE_URL']
REDIS_URL=os.environ['REDIS_URL']
FFMPEG=get_ffmpeg_exe()
r=redis.from_url(REDIS_URL,decode_responses=True)

def db(): return psycopg.connect(DATABASE_URL)
def update(jid,status,stage,progress,message):
    with db() as c:c.execute('update jobs set status=%s,stage=%s,progress=%s,message=%s,updated_at=now() where id=%s',(status,stage,progress,message,jid))
def run(cmd):
    p=subprocess.run(cmd,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,timeout=900)
    if p.returncode: raise RuntimeError((p.stderr or p.stdout)[-3000:])

def make_segment(src:Path,out:Path,duration:float=3.2):
    run([FFMPEG,'-y','-i',str(src),'-t',str(duration),'-vf','scale=720:1280:force_original_aspect_ratio=increase,crop=720:1280,fps=30,setsar=1','-an','-c:v','libx264','-preset','veryfast','-crf','23','-pix_fmt','yuv420p',str(out)])

def render_job(jid:str):
    try:
        update(jid,'running','loading',5,'Chargement du projet')
        with db() as c:
            job=c.execute('select project_id,variants,settings from jobs where id=%s',(jid,)).fetchone()
            if not job: return
            project_id,variants,settings=job
            ids=[uuid.UUID(x) for x in (settings.get('assetIds') or [])]
            rows=c.execute('select id,name,data from assets where id=any(%s)',(ids,)).fetchall()
            project=c.execute('select name from projects where id=%s',(project_id,)).fetchone()
        if not rows: raise RuntimeError('Aucun rush source')
        with tempfile.TemporaryDirectory(prefix='autodirector_') as td:
            td=Path(td); sources=[]
            for i,(aid,name,data) in enumerate(rows):
                p=td/f'source_{i}{Path(name).suffix or ".mp4"}';p.write_bytes(bytes(data));sources.append(p)
            outputs=[]
            for v in range(max(1,min(3,variants))):
                update(jid,'running','render',20+v*20,f'Rendu variante {v+1}/{variants}')
                segs=[]
                order=sources[v:]+sources[:v]
                for i,src in enumerate(order[:8]):
                    out=td/f'v{v}_seg{i}.mp4';make_segment(src,out,3.0 if i else 3.8);segs.append(out)
                concat=td/f'v{v}.txt';concat.write_text('\n'.join([f"file '{p.as_posix()}'" for p in segs]))
                base=td/f'v{v}_base.mp4';run([FFMPEG,'-y','-f','concat','-safe','0','-i',str(concat),'-c:v','libx264','-preset','veryfast','-crf','23','-movflags','+faststart',str(base)])
                title=(project[0] if project else 'Auto Director')[:90]
                voice=td/f'v{v}.mp3'
                try: asyncio.run(Communicate(f'{title}. Regarde jusqu à la fin.',voice='fr-FR-DeniseNeural').save(str(voice)))
                except Exception: voice=None
                final=td/f'AutoDirector_V{v+1}.mp4'
                if voice and Path(voice).exists(): run([FFMPEG,'-y','-i',str(base),'-i',str(voice),'-filter_complex','[1:a]volume=1.1[a]','-map','0:v:0','-map','[a]','-c:v','copy','-c:a','aac','-shortest','-movflags','+faststart',str(final)])
                else: final.write_bytes(base.read_bytes())
                outputs.append(final)
            out_ids=[]
            with db() as c:
                for i,p in enumerate(outputs):
                    aid=uuid.uuid4();b=p.read_bytes();c.execute("insert into assets(id,project_id,name,content_type,size,role,kind,data) values(%s,%s,%s,'video/mp4',%s,'render','render',%s)",(aid,project_id,p.name,len(b),b));out_ids.append(aid)
                c.execute("update jobs set status='done',stage='complete',progress=100,message='Rendu terminé',output_asset_ids=%s,updated_at=now() where id=%s",(out_ids,jid))
    except Exception as e:
        update(jid,'failed','error',0,str(e)[:500])

def main():
    print('Auto Director worker ready',flush=True)
    while True:
        item=r.brpop('auto_director:jobs',timeout=5)
        if item: render_job(item[1])

if __name__=='__main__': main()
