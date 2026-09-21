# -*- coding: utf-8 -*-
"""Auto Director PC worker over HTTPS."""
import gc
import json
import os
import sys
import tempfile
import threading
import time
from pathlib import Path

REPO_ROOT=Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:sys.path.insert(0,str(REPO_ROOT))

import httpx
os.environ['REMOTE_WORKER_MODE']='1'
from engine.analysis import analyze_asset,content_profile,style_fingerprint
from engine.config import ENGINE_VERSION,FFMPEG_THREADS,MAX_REVISIONS,RENDER_FPS,RENDER_HEIGHT,RENDER_WIDTH
from engine.director import choose_plan
from engine.local_ai import critic_video,enabled as local_ai_enabled,refine_plan
from engine.rendering import critic,render_plan

STUDIO_URL=os.environ.get('STUDIO_URL','https://auto-director-web.onrender.com').rstrip('/')
WORKER_TOKEN=os.environ.get('WORKER_TOKEN','').strip();PROFILE_NAME=os.environ.get('PROFILE_NAME','safe-unknown');MODEL=os.environ.get('LOCAL_VLM_MODEL','qwen2.5vl:3b')
POLL_SECONDS=max(2,min(15,int(os.environ.get('WORKER_POLL_SECONDS','4'))));RENEW_SECONDS=max(1800,min(6*3600,int(os.environ.get('WORKER_RENEW_SECONDS','10800'))))
STOP=threading.Event();TOKEN_LOCK=threading.Lock()
if not WORKER_TOKEN:raise SystemExit('WORKER_TOKEN manquant. Lance le worker depuis le Studio ou le lanceur officiel.')

def current_token():
    with TOKEN_LOCK:return WORKER_TOKEN

def headers():return {'Authorization':'Bearer '+current_token(),'User-Agent':f'AutoDirector-PC/{ENGINE_VERSION}'}
def client(timeout=120):return httpx.Client(base_url=STUDIO_URL,headers=headers(),timeout=timeout,follow_redirects=True)

def renew_token():
    global WORKER_TOKEN
    try:
        with client(25) as c:r=c.post('/api/local-worker/renew')
        if r.status_code!=200:return False
        value=str((r.json() or {}).get('workerToken') or '').strip()
        if not value:return False
        with TOKEN_LOCK:WORKER_TOKEN=value
        print('Session worker HTTPS renouvelée.',flush=True);return True
    except Exception as exc:
        print('Renouvellement worker temporairement indisponible:',type(exc).__name__,str(exc)[:100],flush=True);return False

def renew_loop():
    while not STOP.wait(RENEW_SECONDS):
        while not renew_token():
            if STOP.wait(60):return

def heartbeat_payload():return {'engine':ENGINE_VERSION,'protocol':2,'agentVersion':'2.8','profile':PROFILE_NAME,'resolution':[RENDER_WIDTH,RENDER_HEIGHT],'fps':RENDER_FPS,'ffmpegThreads':FFMPEG_THREADS,'localAI':bool(local_ai_enabled()),'model':MODEL if local_ai_enabled() else None,'styleEngine':True}
def heartbeat_loop():
    while not STOP.is_set():
        try:
            with client(15) as c:r=c.post('/api/local-worker/heartbeat',json=heartbeat_payload())
            if r.status_code==401:
                if renew_token():continue
                print('Worker token expiré et non renouvelable. Redémarre le worker depuis le Studio.',flush=True);STOP.set();return
            r.raise_for_status()
        except Exception as exc:print('Heartbeat HTTPS temporairement indisponible:',type(exc).__name__,str(exc)[:120],flush=True)
        STOP.wait(5)

def progress(jid,stage,value,message,**extra):
    with client(30) as c:
        r=c.post(f'/api/local-worker/jobs/{jid}/progress',json={'stage':stage,'progress':int(value),'message':str(message)[:500],**extra})
        if r.status_code==409:raise RuntimeError('JOB_CANCELLED')
        r.raise_for_status()

def is_cancelled(jid):
    try:
        with client(20) as c:r=c.get(f'/api/local-worker/jobs/{jid}/state')
        if r.status_code==409:return True
        r.raise_for_status();return (r.json() or {}).get('status')=='cancelled'
    except Exception:return False

def download_asset(c,jid,item,out_path):
    with c.stream('GET',f"/api/local-worker/assets/{item['id']}",params={'jobId':jid}) as r:
        r.raise_for_status()
        with out_path.open('wb') as f:
            for chunk in r.iter_bytes(1024*1024):
                if chunk:f.write(chunk)
    expected=int(item.get('size') or 0)
    if expected and out_path.stat().st_size!=expected:raise RuntimeError(f"Téléchargement incomplet: {item.get('name','asset')}")

def upload_output(jid,path,metadata):
    with client(900) as c,path.open('rb') as f:
        r=c.post(f'/api/local-worker/jobs/{jid}/output',data={'metadata_json':json.dumps(metadata,ensure_ascii=False,separators=(',',':'))},files={'file':(path.name,f,'video/mp4')})
        if r.status_code==409:raise RuntimeError('JOB_CANCELLED')
        r.raise_for_status();return r.json()

def process_remote_job(job):
    jid=job['id'];settings=job.get('settings') or {};variants=max(1,min(3,int(job.get('variants') or 1)));target=max(8,min(35,int(settings.get('targetDuration',18))))
    captions=bool(settings.get('captions',True));voice=settings.get('voiceover','auto');auto_revision=bool(settings.get('autoRevision',True));context=job.get('context') or {};project_name=job.get('projectName') or 'Auto Director'
    mode=str(settings.get('directorMode','auto'));intensity=str(settings.get('editIntensity','balanced'));hook_style=str(settings.get('hookStyle','auto'));visual_style=str(settings.get('visualStyle','auto'))
    progress(jid,'download',3,'Worker PC · récupération sécurisée des rushs')
    with tempfile.TemporaryDirectory(prefix='autodirector_pc_v92_') as td:
        work=Path(td);paths={};sources=[];refs=[];assets=job.get('assets') or []
        if not assets:raise RuntimeError('Aucun rush fourni au worker PC')
        with client(300) as c:
            for i,item in enumerate(assets):
                if is_cancelled(jid):raise RuntimeError('JOB_CANCELLED')
                suffix=Path(item.get('name') or '').suffix or '.mp4';path=work/f'a{i}{suffix}';download_asset(c,jid,item,path);paths[str(item['id'])]=path
                analysis,_=analyze_asset(path,str(item['id']),item.get('name') or path.name,item.get('role') or 'source',item.get('metadata') or {})
                (refs if item.get('role')=='reference' else sources).append(analysis)
                progress(jid,'analysis',6+int(14*(i+1)/max(1,len(assets))),f"Analyse locale {i+1}/{len(assets)}")
        if not sources:raise RuntimeError('Aucun rush source exploitable')
        style=style_fingerprint(refs);profile=content_profile(sources)
        brief={'engine':ENGINE_VERSION,'transport':'https-remote-worker','project':project_name,'targetDuration':target,'sourceCount':len(sources),'referenceCount':len(refs),'styleFingerprint':style,'contentProfile':profile,'performanceMemory':context.get('winningStrategies',[]),'localAI':local_ai_enabled(),'profileName':PROFILE_NAME,'directorMode':mode,'editIntensity':intensity,'hookStyle':hook_style,'visualStyle':visual_style}
        progress(jid,'director',22,f'Director V9.2 · mode {mode} · style {visual_style}',brief=brief)
        scores=[];revisions=0;last_strategy=''
        for variant in range(variants):
            if is_cancelled(jid):raise RuntimeError('JOB_CANCELLED')
            plan,simulations=choose_plan(project_name,sources,style,profile,context,target,variant,0,mode,intensity,hook_style,visual_style);plan,local_diag=refine_plan(project_name,plan,sources,paths,work);last_strategy=plan['strategy']
            brief_v={**brief,'selectedStrategy':last_strategy,'selectedVisualStyle':plan.get('visualStyle'),'styleDiversity':plan.get('styleDiversity'),'simulations':simulations,'predictedRetention':plan.get('predictedRetention'),'localAIDirector':local_diag}
            progress(jid,'director',25+variant*18,f"Plan V9.2 {variant+1}/{variants} · {last_strategy} · {plan.get('visualStyle','auto')}",strategy=last_strategy,brief=brief_v)
            initial=work/f'AutoDirector_PC_V92_{variant+1}.mp4';render_plan(work,plan,paths,initial,captions,voice);score,diag=critic(initial,target,plan);score,vlm_diag=critic_video(initial,score,plan,work);diag={**diag,'localVLM':vlm_diag};final=initial;revision_count=0
            if auto_revision and score<82 and MAX_REVISIONS>0:
                progress(jid,'revision',min(88,50+variant*15),f'V9.2 Critic local · révision automatique · {score}/100')
                plan2,_=choose_plan(project_name,sources,style,profile,context,target,variant,1,mode,intensity,hook_style,visual_style);plan2,local_diag2=refine_plan(project_name,plan2,sources,paths,work);revised=work/f'AutoDirector_PC_V92_{variant+1}_R1.mp4';render_plan(work,plan2,paths,revised,captions,voice);score2,diag2=critic(revised,target,plan2);score2,vlm_diag2=critic_video(revised,score2,plan2,work);diag2={**diag2,'localVLM':vlm_diag2,'localAIDirector':local_diag2}
                if score2>=score:final,plan,score,diag=revised,plan2,score2,diag2;revision_count=1;revisions+=1;last_strategy=plan['strategy']
            meta={'engineVersion':ENGINE_VERSION,'worker':'pc-https','profile':PROFILE_NAME,'score':score,'duration':diag.get('duration'),'strategy':plan['strategy'],'hook':plan['hook'],'pace':plan.get('pace'),'predictedRetention':plan.get('predictedRetention'),'revisionCount':revision_count,'referenceCount':len(refs),'segmentCount':len(plan.get('segments',[])),'critic':diag,'styleFingerprint':style,'resolution':[RENDER_WIDTH,RENDER_HEIGHT],'fps':RENDER_FPS,'localAI':local_ai_enabled(),'directorMode':mode,'editIntensity':intensity,'hookStyle':hook_style,'visualStyle':plan.get('visualStyle',visual_style),'styleEngine':plan.get('styleEngine'),'styleDiversity':plan.get('styleDiversity')}
            progress(jid,'upload',min(94,62+variant*14),f"Envoi sécurisé · {plan.get('visualStyle','auto')} · variante {variant+1}");upload_output(jid,final,meta);scores.append(float(score));gc.collect()
        with client(40) as c:
            r=c.post(f'/api/local-worker/jobs/{jid}/complete',json={'score':max(scores) if scores else 0,'revisionCount':revisions,'strategy':last_strategy,'message':'Rendu terminé · prêt pour publication manuelle'});r.raise_for_status()
        print(f'Job V9.2 {jid} terminé sur le PC · score {max(scores) if scores else 0}',flush=True)

def claim_job():
    with client(40) as c:
        r=c.post('/api/local-worker/jobs/claim')
        if r.status_code==401:
            if renew_token():return None
            raise RuntimeError('WORKER_TOKEN_EXPIRED')
        r.raise_for_status();return (r.json() or {}).get('job')

def fail_job(jid,error):
    if not jid:return
    try:
        with client(25) as c:c.post(f'/api/local-worker/jobs/{jid}/fail',json={'error':str(error)[:500]})
    except Exception:pass

def main():
    print(f'Auto Director PC HTTPS V{ENGINE_VERSION} · {RENDER_WIDTH}x{RENDER_HEIGHT}@{RENDER_FPS} · {PROFILE_NAME} · Style Engine',flush=True)
    threading.Thread(target=heartbeat_loop,daemon=True).start();threading.Thread(target=renew_loop,daemon=True).start();time.sleep(1.2)
    while not STOP.is_set():
        jid=None
        try:
            job=claim_job()
            if not job:STOP.wait(POLL_SECONDS);continue
            jid=job.get('id');process_remote_job(job)
        except KeyboardInterrupt:STOP.set()
        except Exception as exc:
            text=str(exc)
            if text=='WORKER_TOKEN_EXPIRED':print('Session worker expirée. Redémarre depuis le Studio.',flush=True);STOP.set();break
            if text=='JOB_CANCELLED':print(f'Job {jid or "?"} annulé.',flush=True)
            else:print('Erreur worker PC:',type(exc).__name__,text[:400],flush=True);fail_job(jid,text)
            STOP.wait(2)
    print('Worker PC arrêté.',flush=True)

if __name__=='__main__':main()
