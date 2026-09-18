# -*- coding: utf-8 -*-
import base64, json, os, re
from pathlib import Path
import httpx
from .config import FFMPEG, run

LOCAL_VLM_URL=os.environ.get('LOCAL_VLM_URL','').rstrip('/')
LOCAL_VLM_MODEL=os.environ.get('LOCAL_VLM_MODEL','qwen2.5vl:3b')
LOCAL_VLM_TIMEOUT=float(os.environ.get('LOCAL_VLM_TIMEOUT','120'))


def enabled():
    return bool(LOCAL_VLM_URL)


def _frame(src:Path, at:float, out:Path):
    run([FFMPEG,'-y','-ss',str(max(0,at)),'-i',str(src),'-frames:v','1','-vf','scale=640:-2',str(out)],90)
    return out


def _b64(path:Path):
    return base64.b64encode(path.read_bytes()).decode()


def _jsonish(text):
    if not text:return None
    try:return json.loads(text)
    except Exception:pass
    m=re.search(r'\{.*\}',text,re.S)
    if not m:return None
    try:return json.loads(m.group(0))
    except Exception:return None


def _chat(prompt, images):
    if not enabled():return None
    payload={'model':LOCAL_VLM_MODEL,'stream':False,'format':'json','messages':[{'role':'user','content':prompt,'images':[_b64(x) for x in images]}]}
    try:
        with httpx.Client(timeout=LOCAL_VLM_TIMEOUT) as c:
            r=c.post(f'{LOCAL_VLM_URL}/api/chat',json=payload);r.raise_for_status();data=r.json()
        return _jsonish(((data.get('message') or {}).get('content')) or '')
    except Exception as e:
        print('LOCAL VLM fallback',type(e).__name__,str(e)[:180],flush=True);return None


def refine_plan(project_name,plan,sources,paths,workdir):
    if not enabled():return plan,{'mode':'heuristic'}
    frames=[];labels=[]
    for i,seg in enumerate(plan.get('segments',[])[:6]):
        src=paths.get(str(seg.get('assetId')))
        if not src:continue
        out=workdir/f'vlm_plan_{i}.jpg'
        try:
            _frame(src,float(seg.get('start',0))+.35,out);frames.append(out);labels.append({'index':i,'assetId':seg.get('assetId'),'start':seg.get('start'),'quality':seg.get('momentScore')})
        except Exception:pass
    if not frames:return plan,{'mode':'heuristic'}
    prompt=(f"Tu es un directeur TikTok gaming local. Projet: {project_name}. Voici {len(frames)} images dans l'ordre du plan actuel. "
            f"Plan: {json.dumps(plan,ensure_ascii=False)[:5500]}. Indices: {json.dumps(labels)}. "
            "Retourne uniquement JSON: {\"hook\":\"...\",\"preferredOrder\":[0,1,...],\"captions\":{\"0\":\"texte court\"},\"reason\":\"...\"}. "
            "Objectif: compréhension immédiate, tension, payoff, aucune copie textuelle d'une référence, captions très courtes. Ne crée aucun nouvel assetId.")
    obj=_chat(prompt,frames)
    if not isinstance(obj,dict):return plan,{'mode':'heuristic'}
    refined={**plan,'source':'local-vlm'};segs=list(plan.get('segments',[]))
    order=obj.get('preferredOrder')
    if isinstance(order,list):
        valid=[]
        for x in order:
            try:i=int(x)
            except Exception:continue
            if 0<=i<len(segs) and i not in valid:valid.append(i)
        if len(valid)>=max(3,min(len(segs),len(segs)//2)):
            refined['segments']=[segs[i] for i in valid]+[s for i,s in enumerate(segs) if i not in valid]
    hook=str(obj.get('hook') or '').strip()
    if 5<=len(hook)<=140:refined['hook']=hook
    caps=obj.get('captions') if isinstance(obj.get('captions'),dict) else {}
    for i,s in enumerate(refined['segments']):
        cap=str(caps.get(str(i),'')).strip()
        if 1<=len(cap)<=80:s['caption']=cap
    return refined,{'mode':'local-vlm','model':LOCAL_VLM_MODEL,'reason':str(obj.get('reason',''))[:260]}


def critic_video(path,technical_score,plan,workdir):
    if not enabled():return technical_score,{'mode':'technical'}
    # sample beginning, middle and payoff/end
    duration=sum(float(s.get('duration',0)) for s in plan.get('segments',[])) or 12
    frames=[]
    for i,t in enumerate([.45,max(.8,duration*.36),max(1.0,duration*.76)]):
        out=workdir/f'vlm_critic_{i}.jpg'
        try:_frame(path,t,out);frames.append(out)
        except Exception:pass
    if not frames:return technical_score,{'mode':'technical'}
    prompt=(f"Evalue une video TikTok gaming finale. Hook: {plan.get('hook','')}. Strategie: {plan.get('strategy','')}. "
            f"Score technique: {technical_score}. Retourne uniquement JSON: {{\"score\":0-100,\"hook\":0-100,\"clarity\":0-100,\"payoff\":0-100,\"reason\":\"...\"}}. "
            "Juge retention des 2 premieres secondes, lisibilite, progression et payoff final.")
    obj=_chat(prompt,frames)
    if not isinstance(obj,dict):return technical_score,{'mode':'technical'}
    try:ai=max(0,min(100,float(obj.get('score',technical_score))))
    except Exception:ai=technical_score
    blended=round(.52*ai+.48*technical_score,1)
    return blended,{'mode':'local-vlm','model':LOCAL_VLM_MODEL,'aiScore':ai,'hook':obj.get('hook'),'clarity':obj.get('clarity'),'payoff':obj.get('payoff'),'reason':str(obj.get('reason',''))[:300]}
