# -*- coding: utf-8 -*-
import base64, ctypes, json, os, re
from pathlib import Path
import httpx
from .config import FFMPEG, run

URL=os.environ.get('LOCAL_VLM_URL','').rstrip('/')
MODEL=os.environ.get('LOCAL_VLM_MODEL','qwen2.5vl:3b')
TIMEOUT=float(os.environ.get('LOCAL_VLM_TIMEOUT','150'))
IMAGE_WIDTH=max(384,min(640,int(os.environ.get('LOCAL_VLM_IMAGE_WIDTH','448'))))
MAX_IMAGES=max(2,min(4,int(os.environ.get('LOCAL_VLM_MAX_IMAGES','3'))))
NUM_CTX=max(1024,min(2048,int(os.environ.get('LOCAL_VLM_NUM_CTX','1280'))))
NUM_PREDICT=max(120,min(320,int(os.environ.get('LOCAL_VLM_NUM_PREDICT','200'))))
NUM_THREADS=max(1,min(4,int(os.environ.get('LOCAL_VLM_THREADS','2'))))
MIN_FREE_GB=max(2.0,float(os.environ.get('LOCAL_VLM_MIN_FREE_GB','3.0')))


def available_memory_gb():
    try:
        if os.name=='nt':
            class M(ctypes.Structure):
                _fields_=[('dwLength',ctypes.c_ulong),('dwMemoryLoad',ctypes.c_ulong),('ullTotalPhys',ctypes.c_ulonglong),('ullAvailPhys',ctypes.c_ulonglong),('ullTotalPageFile',ctypes.c_ulonglong),('ullAvailPageFile',ctypes.c_ulonglong),('ullTotalVirtual',ctypes.c_ulonglong),('ullAvailVirtual',ctypes.c_ulonglong),('sullAvailExtendedVirtual',ctypes.c_ulonglong)]
            s=M();s.dwLength=ctypes.sizeof(M)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(s)):return s.ullAvailPhys/(1024**3)
        if hasattr(os,'sysconf') and 'SC_AVPHYS_PAGES' in os.sysconf_names:return os.sysconf('SC_AVPHYS_PAGES')*os.sysconf('SC_PAGE_SIZE')/(1024**3)
    except Exception:pass
    return 0.0


def enabled():return bool(URL)

def _frame(src:Path,at:float,out:Path):
    run([FFMPEG,'-y','-ss',str(max(0,at)),'-i',str(src),'-frames:v','1','-vf',f'scale={IMAGE_WIDTH}:-2',str(out)],90);return out

def _jsonish(text):
    if not text:return None
    try:return json.loads(text)
    except Exception:pass
    m=re.search(r'\{.*\}',text,re.S)
    if not m:return None
    try:return json.loads(m.group(0))
    except Exception:return None

def _chat(prompt,images):
    free=available_memory_gb()
    if not enabled() or free<MIN_FREE_GB:
        if enabled():print(f'Local AI skipped: free RAM {free:.1f} GB < {MIN_FREE_GB:.1f} GB',flush=True)
        return None
    imgs=list(images or [])[:MAX_IMAGES]
    try:
        payload={'model':MODEL,'stream':False,'format':'json','keep_alive':'90s','options':{'num_ctx':NUM_CTX,'num_predict':NUM_PREDICT,'num_thread':NUM_THREADS,'temperature':0.20},'messages':[{'role':'user','content':prompt,'images':[base64.b64encode(p.read_bytes()).decode() for p in imgs]}]}
        with httpx.Client(timeout=TIMEOUT) as c:r=c.post(URL+'/api/chat',json=payload);r.raise_for_status();data=r.json()
        return _jsonish(((data.get('message') or {}).get('content')) or '')
    except Exception as e:
        print('Local AI fallback',type(e).__name__,str(e)[:160],flush=True);return None


def _speech_context(sources):
    out=[]
    for s in sources or []:
        text=str(s.get('spokenText') or (s.get('transcript') or {}).get('text') or '').strip()
        if text:out.append({'assetId':s.get('id'),'speech':text[:420]})
        if len(out)>=5:break
    return out


def refine_plan(project_name,plan,sources,paths,workdir):
    if not enabled():return plan,{'mode':'heuristic'}
    frames=[];labels=[]
    for i,seg in enumerate(plan.get('segments',[])[:MAX_IMAGES]):
        src=paths.get(str(seg.get('assetId')))
        if not src:continue
        out=workdir/f'vlm_plan_{i}.jpg'
        try:_frame(src,float(seg.get('start',0))+.35,out);frames.append(out);labels.append({'index':i,'assetId':seg.get('assetId'),'start':seg.get('start'),'quality':seg.get('momentScore')})
        except Exception:pass
    if not frames:return plan,{'mode':'heuristic'}
    speech=_speech_context(sources)
    prompt=(f"Directeur TikTok gaming. Projet: {project_name}. Plan: {json.dumps(plan,ensure_ascii=False)[:2800]}. "
            f"Indices images: {json.dumps(labels,ensure_ascii=False)}. Paroles transcrites locales: {json.dumps(speech,ensure_ascii=False)[:1600]}. "
            "Utilise les paroles seulement si elles apportent du contexte; ne les invente jamais. "
            "Reponds uniquement JSON avec hook, preferredOrder, captions, reason. Privilegie comprehension immediate, tension, payoff et captions tres courtes.")
    obj=_chat(prompt,frames)
    if not isinstance(obj,dict):return plan,{'mode':'heuristic'}
    refined={**plan,'source':'local-vlm'};segs=list(plan.get('segments',[]));order=obj.get('preferredOrder')
    if isinstance(order,list):
        valid=[]
        for x in order:
            try:i=int(x)
            except Exception:continue
            if 0<=i<len(segs) and i not in valid:valid.append(i)
        if len(valid)>=2:refined['segments']=[segs[i] for i in valid]+[s for i,s in enumerate(segs) if i not in valid]
    hook=str(obj.get('hook') or '').strip()
    if 5<=len(hook)<=140:refined['hook']=hook
    caps=obj.get('captions') if isinstance(obj.get('captions'),dict) else {}
    for i,s in enumerate(refined['segments']):
        cap=str(caps.get(str(i),'')).strip()
        if 1<=len(cap)<=80:s['caption']=cap
    return refined,{'mode':'local-vlm','model':MODEL,'reason':str(obj.get('reason',''))[:260],'speechContext':bool(speech)}


def critic_video(path,technical_score,plan,workdir):
    if not enabled():return technical_score,{'mode':'technical'}
    duration=sum(float(s.get('duration',0)) for s in plan.get('segments',[])) or 12;frames=[]
    for i,t in enumerate([.45,max(.8,duration*.45),max(1.0,duration*.80)]):
        if len(frames)>=MAX_IMAGES:break
        out=workdir/f'vlm_critic_{i}.jpg'
        try:_frame(path,t,out);frames.append(out)
        except Exception:pass
    if not frames:return technical_score,{'mode':'technical'}
    obj=_chat(f"Evalue ce TikTok gaming. Hook: {plan.get('hook','')}. Score technique: {technical_score}. Reponds uniquement JSON avec score, hook, clarity, payoff, reason.",frames)
    if not isinstance(obj,dict):return technical_score,{'mode':'technical'}
    try:ai=max(0,min(100,float(obj.get('score',technical_score))))
    except Exception:ai=technical_score
    return round(.52*ai+.48*technical_score,1),{'mode':'local-vlm','model':MODEL,'aiScore':ai,'hook':obj.get('hook'),'clarity':obj.get('clarity'),'payoff':obj.get('payoff'),'reason':str(obj.get('reason',''))[:300]}
