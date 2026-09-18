import asyncio
import base64
import json
import math
import os
import re
import subprocess
import tempfile
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import httpx
import psycopg
import redis
from edge_tts import Communicate
from imageio_ffmpeg import get_ffmpeg_exe
from psycopg.types.json import Jsonb

DATABASE_URL=os.environ['DATABASE_URL']
REDIS_URL=os.environ['REDIS_URL']
OPENAI_API_KEY=os.environ.get('OPENAI_API_KEY','')
AI_MODEL=os.environ.get('AI_MODEL','gpt-5.6-luna')
RENDER_WIDTH=int(os.environ.get('RENDER_WIDTH','1080'))
RENDER_HEIGHT=int(os.environ.get('RENDER_HEIGHT','1920'))
SELF_TEST_ON_START=os.environ.get('SELF_TEST_ON_START','0')=='1'
FFMPEG=get_ffmpeg_exe()
queue=redis.from_url(REDIS_URL,decode_responses=True)

def db(): return psycopg.connect(DATABASE_URL)

def ensure_schema():
    with db() as c:
        stmts=["alter table assets add column if not exists metadata jsonb not null default '{}'::jsonb","alter table jobs add column if not exists critic_score double precision","alter table jobs add column if not exists revision_count int not null default 0","alter table jobs add column if not exists strategy text not null default ''","alter table jobs add column if not exists creative_brief jsonb not null default '{}'::jsonb","alter table trends add column if not exists source_url text not null default ''"]
        for s in stmts:
            try:c.execute(s)
            except Exception: pass
        try:c.execute("update trends set source_url=url where source_url='' and coalesce(url,'')<>''")
        except Exception: pass

def run(cmd,timeout=900,check=True):
    p=subprocess.run(cmd,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,timeout=timeout)
    if check and p.returncode!=0: raise RuntimeError((p.stderr or p.stdout or '')[-4500:])
    return p

def update(jid,status,stage,progress,message,score=None,revision=None,strategy=None,brief=None):
    sets=['status=%s','stage=%s','progress=%s','message=%s','updated_at=now()'];vals=[status,stage,int(progress),str(message)[:500]]
    if score is not None:sets.append('critic_score=%s');vals.append(float(score))
    if revision is not None:sets.append('revision_count=%s');vals.append(int(revision))
    if strategy is not None:sets.append('strategy=%s');vals.append(str(strategy)[:120])
    if brief is not None:sets.append('creative_brief=%s');vals.append(Jsonb(brief))
    vals.append(jid)
    with db() as c:
        c.execute('update jobs set '+','.join(sets)+' where id=%s',vals)
        try:c.execute('insert into job_events(job_id,stage,message) values(%s,%s,%s)',(jid,stage,str(message)[:500]))
        except Exception:pass

def media_info(path:Path):
    p=run([FFMPEG,'-hide_banner','-i',str(path)],timeout=45,check=False);text=p.stderr or ''
    m=re.search(r'Duration:\s*(\d+):(\d+):([\d.]+)',text);duration=0.0
    if m:duration=int(m.group(1))*3600+int(m.group(2))*60+float(m.group(3))
    vm=re.search(r'Video:.*?(\d{2,5})x(\d{2,5})',text);res=[int(vm.group(1)),int(vm.group(2))] if vm else [0,0]
    return duration,'Audio:' in text,res

def scene_cuts(path:Path,max_seconds=45):
    p=run([FFMPEG,'-hide_banner','-t',str(max_seconds),'-i',str(path),'-vf',"select='gt(scene,0.28)',showinfo",'-an','-f','null','-'],timeout=180,check=False)
    vals=[float(x) for x in re.findall(r'pts_time:([0-9.]+)',p.stderr or '')];out=[]
    for x in vals:
        if x<0.55:continue
        if not out or x-out[-1]>=0.55:out.append(round(x,2))
        if len(out)>=20:break
    return out

def black_ratio(path:Path,duration:float):
    sample=min(max(duration,1.0),24.0);p=run([FFMPEG,'-hide_banner','-t',str(sample),'-i',str(path),'-vf','blackdetect=d=0.12:pix_th=0.08','-an','-f','null','-'],timeout=120,check=False)
    spans=re.findall(r'black_start:([\d.]+)\s+black_end:([\d.]+)',p.stderr or '');black=sum(max(0,float(b)-float(a)) for a,b in spans)
    return min(1.0,black/max(sample,0.1))

def has_drawtext():
    try:return 'drawtext' in run([FFMPEG,'-hide_banner','-filters'],timeout=30,check=False).stdout
    except Exception:return False
DRAWTEXT=has_drawtext()

def extract_frame(path:Path,at:float,out:Path):
    run([FFMPEG,'-y','-ss',str(max(0,at)),'-i',str(path),'-frames:v','1','-vf','scale=512:-2',str(out)],timeout=90);return out

def image_data_url(path:Path):return 'data:image/jpeg;base64,'+base64.b64encode(path.read_bytes()).decode()

def extract_openai_text(data):
    if isinstance(data,dict) and data.get('output_text'):return data['output_text']
    chunks=[]
    for out in (data or {}).get('output',[]):
        for c in out.get('content',[]) if isinstance(out,dict) else []:
            if isinstance(c,dict) and c.get('text'):chunks.append(c['text'])
    return '\n'.join(chunks)

def parse_jsonish(text):
    if not text:return None
    text=text.strip()
    try:return json.loads(text)
    except Exception:pass
    m=re.search(r'\{.*\}',text,re.S)
    if m:
        try:return json.loads(m.group(0))
        except Exception:return None
    return None

def openai_response(prompt,images=None,max_output=1600):
    if not OPENAI_API_KEY:return None
    content=[{'type':'input_text','text':prompt}]
    for img in images or []:content.append({'type':'input_image','image_url':image_data_url(img)})
    payload={'model':AI_MODEL,'input':[{'role':'user','content':content}],'max_output_tokens':max_output}
    try:
        with httpx.Client(timeout=90) as client:
            r=client.post('https://api.openai.com/v1/responses',headers={'Authorization':f'Bearer {OPENAI_API_KEY}','Content-Type':'application/json'},json=payload);r.raise_for_status();return extract_openai_text(r.json())
    except Exception as e:print('OpenAI fallback:',type(e).__name__,str(e)[:220],flush=True);return None

def get_context(project_id):
    with db() as c:
        feedback=c.execute("select a.name,sum(f.views),avg(f.completion),sum(f.shares) from feedback f join assets a on a.id=f.asset_id join projects p on p.id=a.project_id where p.id=%s group by a.name order by sum(f.views) desc limit 8",(project_id,)).fetchall()
        try:trends=c.execute("select label,coalesce(source_url,''),notes from trends order by created_at desc limit 10").fetchall()
        except Exception:trends=[]
    return {'performance':[{'name':x[0],'views':int(x[1] or 0),'completion':float(x[2] or 0),'shares':int(x[3] or 0)} for x in feedback],'trends':[{'label':x[0],'url':x[1],'notes':x[2]} for x in trends]}

def build_candidates(items):
    for item in items:
        pts=[0.0]
        for cut in item['cuts']:pts.extend([max(0,cut-0.45),cut])
        d=item['duration']
        if d>4:pts += [d*0.18,d*0.38,d*0.58,d*0.78]
        seen=[]
        for p in pts:
            q=round(max(0,p),2)
            if all(abs(q-x)>0.55 for x in seen):seen.append(q)
        item['starts']=seen[:24]
    return items

def reference_pace(refs):
    intervals=[]
    for item in refs:
        prev=0
        for c in item.get('cuts',[])[:14]:
            if 0.4<c-prev<5:intervals.append(c-prev)
            prev=c
    if not intervals:return 2.15
    return max(1.0,min(3.2,sum(intervals)/len(intervals)))

def local_hooks(project_name):
    clean=(project_name or 'ce moment')[:55]
    return [f'Attends de voir ce qui se passe sur {clean}…','Je ne pensais pas que ça allait finir comme ça…','Regarde bien les prochaines secondes.']

def local_plan(project_name,sources,refs,variant,target,revision=0):
    pace=reference_pace(refs)*(0.82 if revision else 1.0);pace=max(1.0,min(3.2,pace));target=max(8,min(35,target));needed=max(3,min(14,math.ceil(target/pace)));order=sources[variant%len(sources):]+sources[:variant%len(sources)];segs=[]
    for i in range(needed):
        item=order[i%len(order)];starts=item.get('starts') or [0.0];start=starts[(variant+i*2)%len(starts)];remaining=target-sum(s['duration'] for s in segs);duration=min(pace,max(1.0,remaining));segs.append({'assetId':item['id'],'start':start,'duration':duration,'zoom':1.02+0.018*((i+variant)%4),'caption':''})
        if sum(s['duration'] for s in segs)>=target-0.35:break
    hs=local_hooks(project_name);return {'hook':hs[variant%len(hs)],'segments':segs,'strategy':'reference_fast_reveal' if refs else 'dynamic_scene_reveal','pace':round(pace,2),'source':'local'}

def ai_plan(project_name,sources,refs,variant,target,context,frame_paths):
    prompt=f'''Tu es Director pour une vidéo verticale TikTok gaming. Projet: {project_name}. Durée cible: {target}s. Variante: {variant+1}.
Rushs analysés: {json.dumps([{k:v for k,v in s.items() if k!='starts'} for s in sources],ensure_ascii=False)}
Références de style: {json.dumps([{k:v for k,v in s.items() if k!='starts'} for s in refs],ensure_ascii=False)}
Mémoire/performance/tendances: {json.dumps(context,ensure_ascii=False)[:5000]}
Retourne UNIQUEMENT un JSON: {{"hook":"...","strategy":"...","segments":[{{"assetId":"id exact","start":0.0,"duration":2.0,"zoom":1.04,"caption":"texte court"}}]}}.
Contraintes: hook original, pas de copie textuelle des références, 3-12 segments, somme proche de {target}s, utilise uniquement les assetId fournis, rythme très rapide, captions courtes.'''
    obj=parse_jsonish(openai_response(prompt,frame_paths,max_output=1800))
    if not isinstance(obj,dict) or not isinstance(obj.get('segments'),list):return None
    valid={s['id'] for s in sources};segments=[]
    for seg in obj['segments'][:14]:
        if str(seg.get('assetId')) not in valid:continue
        try:segments.append({'assetId':str(seg['assetId']),'start':max(0,float(seg.get('start',0))),'duration':max(0.8,min(4.5,float(seg.get('duration',2)))),'zoom':max(1.0,min(1.14,float(seg.get('zoom',1.03)))),'caption':str(seg.get('caption',''))[:80]})
        except Exception:continue
    if len(segments)<3:return None
    return {'hook':str(obj.get('hook') or local_hooks(project_name)[variant%3])[:140],'segments':segments,'strategy':str(obj.get('strategy') or 'ai_dynamic_reveal')[:100],'pace':round(sum(s['duration'] for s in segments)/len(segments),2),'source':'openai'}

def segment_filter(zoom,hook_file,caption_file):
    w,h=RENDER_WIDTH,RENDER_HEIGHT;zw=max(w,int(round((w*zoom)/2)*2));zh=max(h,int(round((h*zoom)/2)*2));f=[f'scale={w}:{h}:force_original_aspect_ratio=increase',f'crop={w}:{h}',f'scale={zw}:{zh}',f'crop={w}:{h}','fps=30','setsar=1']
    if DRAWTEXT and hook_file:f.append(f"drawtext=textfile='{hook_file.as_posix()}':fontcolor=white:fontsize={int(w*0.06)}:borderw=5:bordercolor=black:x=(w-text_w)/2:y={int(h*0.07)}:box=1:boxcolor=black@0.34:boxborderw=16")
    if DRAWTEXT and caption_file:f.append(f"drawtext=textfile='{caption_file.as_posix()}':fontcolor=white:fontsize={int(w*0.043)}:borderw=4:bordercolor=black:x=(w-text_w)/2:y=h*0.76:box=1:boxcolor=black@0.28:boxborderw=13")
    return ','.join(f)

def make_segment(src,out,start,duration,zoom,hook='',caption=''):
    total,has_audio,_=media_info(src);start=min(max(0,start),max(0,total-duration)) if total else max(0,start);hook_file=caption_file=None
    if hook:hook_file=out.with_suffix('.hook.txt');hook_file.write_text(hook,encoding='utf-8')
    if caption:caption_file=out.with_suffix('.cap.txt');caption_file.write_text(caption,encoding='utf-8')
    vf=segment_filter(zoom,hook_file,caption_file);cmd=[FFMPEG,'-y','-ss',str(start),'-i',str(src)]
    if has_audio:cmd += ['-t',str(duration),'-vf',vf,'-map','0:v:0','-map','0:a:0','-c:v','libx264','-preset','veryfast','-crf','21','-pix_fmt','yuv420p','-c:a','aac','-b:a','160k','-ar','44100','-ac','2','-shortest',str(out)]
    else:cmd += ['-f','lavfi','-t',str(duration),'-i','anullsrc=channel_layout=stereo:sample_rate=44100','-t',str(duration),'-vf',vf,'-map','0:v:0','-map','1:a:0','-c:v','libx264','-preset','veryfast','-crf','21','-pix_fmt','yuv420p','-c:a','aac','-b:a','128k','-ar','44100','-ac','2','-shortest',str(out)]
    run(cmd,timeout=700)

def render_variant(workdir,plan,paths,out,captions=True,voiceover='auto'):
    segfiles=[]
    for i,s in enumerate(plan['segments']):
        seg=workdir/f'{out.stem}_s{i}.mp4';make_segment(paths[s['assetId']],seg,float(s['start']),float(s['duration']),float(s.get('zoom',1.03)),plan['hook'] if captions and i==0 else '',s.get('caption','') if captions else '');segfiles.append(seg)
    concat=workdir/f'{out.stem}.txt';concat.write_text('\n'.join([f"file '{p.as_posix()}'" for p in segfiles]),encoding='utf-8');base=workdir/f'{out.stem}_base.mp4';run([FFMPEG,'-y','-f','concat','-safe','0','-i',str(concat),'-c:v','libx264','-preset','veryfast','-crf','21','-c:a','aac','-b:a','160k','-movflags','+faststart',str(base)],timeout=1000)
    if voiceover!='off':
        voice=workdir/f'{out.stem}_voice.mp3'
        try:
            asyncio.run(Communicate(plan['hook'],voice='fr-FR-DeniseNeural',rate='+8%').save(str(voice)))
            if voice.exists() and voice.stat().st_size:
                run([FFMPEG,'-y','-i',str(base),'-i',str(voice),'-filter_complex','[0:a]volume=0.28[a0];[1:a]volume=1.1[a1];[a0][a1]amix=inputs=2:duration=first:dropout_transition=2[a]','-map','0:v:0','-map','[a]','-c:v','copy','-c:a','aac','-b:a','160k','-movflags','+faststart',str(out)],timeout=700);return
        except Exception as e:print('TTS fallback:',type(e).__name__,flush=True)
    out.write_bytes(base.read_bytes())

def technical_score(path,target,source_count,segment_count):
    duration,_,_=media_info(path);black=black_ratio(path,duration);duration_score=max(0,30-abs(duration-target)*2.5);diversity=min(20,source_count*6);pacing=min(20,segment_count*2.5);black_score=max(0,20-black*80);integrity=10 if path.exists() and path.stat().st_size>150000 else 0
    return round(max(0,min(100,duration_score+diversity+pacing+black_score+integrity)),1),round(duration,2),round(black,3)

def ai_critic(path,tech_score,plan,workdir):
    if not OPENAI_API_KEY:return tech_score,{'mode':'technical'}
    duration,_,_=media_info(path);frames=[]
    for i,t in enumerate([0.8,max(1,duration*0.45),max(1,duration*0.82)]):
        try:frames.append(extract_frame(path,t,workdir/f'critic_{i}.jpg'))
        except Exception:pass
    prompt=f'''Évalue cette vidéo TikTok gaming finale. Hook: {plan['hook']}. Stratégie: {plan['strategy']}. Score technique actuel: {tech_score}. Retourne uniquement JSON {{"score":0-100,"reason":"...","revision":"instruction courte"}}. Juge lisibilité, hook, rythme, payoff et intérêt visuel.'''
    obj=parse_jsonish(openai_response(prompt,frames,max_output=500))
    if not isinstance(obj,dict):return tech_score,{'mode':'technical'}
    try:score=max(0,min(100,float(obj.get('score',tech_score))))
    except Exception:score=tech_score
    return round(0.55*score+0.45*tech_score,1),{'mode':'openai','aiScore':score,'reason':str(obj.get('reason',''))[:300],'revision':str(obj.get('revision',''))[:220]}

def render_job(jid):
    try:
        with db() as c:
            job=c.execute('select project_id,variants,settings,status from jobs where id=%s',(jid,)).fetchone()
            if not job:return
            project_id,variants,settings,status=job
            if status=='cancelled':return
            project=c.execute('select name from projects where id=%s',(project_id,)).fetchone();ids=[uuid.UUID(x) for x in settings.get('assetIds',[])]
            source_rows=c.execute("select id,name,data,role from assets where id=any(%s) and kind='source' and role in ('source','broll','talking_head')",(ids,)).fetchall();ref_rows=c.execute("select id,name,data,role from assets where project_id=%s and role='reference' and kind='source' order by created_at desc limit 4",(project_id,)).fetchall()
        if not source_rows:raise RuntimeError('Aucun rush source exploitable')
        update(jid,'running','analysis',7,'Analyse des rushs · scènes · rythme');context=get_context(project_id)
        with tempfile.TemporaryDirectory(prefix='autodirector_') as td:
            work=Path(td);sources=[];refs=[];paths={};frames=[]
            for idx,(role,row) in enumerate([('source',r) for r in source_rows]+[('reference',r) for r in ref_rows]):
                aid,name,data,asset_role=row;p=work/f'a{idx}{Path(name).suffix or ".mp4"}';p.write_bytes(bytes(data));paths[str(aid)]=p;duration,has_audio,res=media_info(p);cuts=scene_cuts(p);item={'id':str(aid),'name':name,'duration':round(duration,2),'cuts':cuts,'resolution':res,'role':asset_role};(sources if role=='source' else refs).append(item)
                if role=='source' and len(frames)<6 and duration>0:
                    for t in [min(1,duration*.15),duration*.55]:
                        if len(frames)>=6:break
                        try:frames.append(extract_frame(p,t,work/f'frame_{len(frames)}.jpg'))
                        except Exception:pass
            build_candidates(sources);build_candidates(refs);target=int(settings.get('targetDuration',18));captions=bool(settings.get('captions',True));voiceover=settings.get('voiceover','auto');auto_rev=bool(settings.get('autoRevision',True));out_ids=[];scores=[];revisions=0;best_strategy='';brief={'project':project[0] if project else 'Auto Director','aiMode':'openai' if OPENAI_API_KEY else 'local','sourceCount':len(sources),'referenceCount':len(refs),'targetDuration':target,'context':context};update(jid,'running','director',17,'Director : création du plan',brief=brief)
            for v in range(max(1,min(3,int(variants)))):
                with db() as c:st=c.execute('select status from jobs where id=%s',(jid,)).fetchone()
                if st and st[0]=='cancelled':return
                plan=ai_plan(brief['project'],sources,refs,v,target,context,frames) or local_plan(brief['project'],sources,refs,v,target,0);best_strategy=plan['strategy'];update(jid,'running','director',20+v*20,f'Director · variante {v+1}/{variants} · {plan["source"]}',strategy=best_strategy,brief={**brief,'lastPlan':plan});initial=work/f'AutoDirector_V{v+1}.mp4';render_variant(work,plan,paths,initial,captions,voiceover);tech,duration,black=technical_score(initial,target,len({s['assetId'] for s in plan['segments']}),len(plan['segments']));score,crit=ai_critic(initial,tech,plan,work);final=initial;revision_count=0
                if auto_rev and score<80:
                    update(jid,'running','revision',min(88,38+v*20),f'Auto-révision V{v+1} · score {score}/100');plan2=local_plan(brief['project'],sources,refs,v,target,1);revised=work/f'AutoDirector_V{v+1}_R1.mp4';render_variant(work,plan2,paths,revised,captions,voiceover);tech2,duration2,black2=technical_score(revised,target,len({s['assetId'] for s in plan2['segments']}),len(plan2['segments']));score2,crit2=ai_critic(revised,tech2,plan2,work)
                    if score2>=score:final,plan,score,duration,black,crit=revised,plan2,score2,duration2,black2,crit2;revision_count=1;revisions+=1
                meta={'score':score,'duration':duration,'blackRatio':black,'strategy':plan['strategy'],'hook':plan['hook'],'revisionCount':revision_count,'referenceCount':len(refs),'segmentCount':len(plan['segments']),'critic':crit,'resolution':[RENDER_WIDTH,RENDER_HEIGHT]}
                with db() as c:
                    aid=uuid.uuid4();blob=final.read_bytes();c.execute("insert into assets(id,project_id,name,content_type,size,role,kind,data,metadata) values(%s,%s,%s,'video/mp4',%s,'render','render',%s,%s)",(aid,project_id,final.name,len(blob),blob,Jsonb(meta)))
                out_ids.append(aid);scores.append(score);update(jid,'running','render',min(94,48+v*18),f'Variante {v+1} terminée · {score}/100',score=max(scores),revision=revisions,strategy=best_strategy)
            with db() as c:c.execute("update jobs set status='done',stage='complete',progress=100,message='Rendu terminé · galerie prête',output_asset_ids=%s,critic_score=%s,revision_count=%s,strategy=%s,updated_at=now() where id=%s",(out_ids,max(scores) if scores else 0,revisions,best_strategy,jid))
    except Exception as e:
        print('JOB FAILED',jid,repr(e),flush=True)
        try:update(jid,'failed','error',0,str(e)[:500])
        except Exception:pass

def self_test():
    pid=aid=jid=None
    try:
        print('SELFTEST start',flush=True)
        with tempfile.TemporaryDirectory(prefix='ad_selftest_') as td:
            p=Path(td)/'synthetic.mp4';run([FFMPEG,'-y','-f','lavfi','-i','testsrc2=size=640x360:rate=30','-f','lavfi','-i','sine=frequency=440:sample_rate=44100','-t','4','-c:v','libx264','-pix_fmt','yuv420p','-c:a','aac',str(p)],timeout=120);blob=p.read_bytes()
        pid,aid,jid=uuid.uuid4(),uuid.uuid4(),uuid.uuid4()
        with db() as c:
            c.execute("insert into projects(id,name,description) values(%s,'__SELFTEST__','automatic worker validation')",(pid,));c.execute("insert into assets(id,project_id,name,content_type,size,role,kind,data,metadata) values(%s,%s,'selftest.mp4','video/mp4',%s,'source','source',%s,'{}'::jsonb)",(aid,pid,len(blob),blob));settings={'assetIds':[str(aid)],'captions':True,'voiceover':'off','autoRevision':False,'targetDuration':8};c.execute("insert into jobs(id,project_id,status,stage,progress,message,variants,settings) values(%s,%s,'queued','queued',0,'selftest',1,%s)",(jid,pid,Jsonb(settings)))
        render_job(str(jid))
        with db() as c:row=c.execute('select status,critic_score,output_asset_ids from jobs where id=%s',(jid,)).fetchone();ok=row and row[0]=='done' and row[2]
        print('SELFTEST PASS' if ok else f'SELFTEST FAIL {row}',flush=True)
    except Exception as e:print('SELFTEST FAIL',repr(e),flush=True)
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
        try:ff_ok=run([FFMPEG,'-version'],timeout=15,check=False).returncode==0
        except Exception:pass
        body=json.dumps({'ok':db_ok and q_ok and ff_ok,'worker':'ready','database':db_ok,'queue':q_ok,'ffmpeg':ff_ok,'resolution':[RENDER_WIDTH,RENDER_HEIGHT],'ai':'openai' if OPENAI_API_KEY else 'local-fallback'}).encode();self.send_response(200 if db_ok and q_ok and ff_ok else 503);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
    def log_message(self,*args):pass

def health_server():HTTPServer(('0.0.0.0',int(os.environ.get('PORT','10000'))),Health).serve_forever()
def main():
    ensure_schema();threading.Thread(target=health_server,daemon=True).start();print(f'Auto Director worker V7 ready {RENDER_WIDTH}x{RENDER_HEIGHT} ai={bool(OPENAI_API_KEY)}',flush=True)
    if SELF_TEST_ON_START:self_test()
    while True:
        try:
            item=queue.brpop('auto_director:jobs',timeout=5)
            if item:render_job(item[1])
        except Exception as e:print('worker loop error',repr(e),flush=True);time.sleep(2)

if __name__=='__main__':main()
