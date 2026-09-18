# -*- coding: utf-8 -*-
import re, statistics
from pathlib import Path
from .config import ANALYSIS_VERSION, FFMPEG, MOMENT_SAMPLES, run

def probe(path:Path):
    text=run([FFMPEG,'-hide_banner','-i',str(path)],45,False).stderr or ''
    m=re.search(r'Duration:\s*(\d+):(\d+):([\d.]+)',text)
    duration=int(m.group(1))*3600+int(m.group(2))*60+float(m.group(3)) if m else 0.0
    vm=re.search(r'Video:.*?(\d{2,5})x(\d{2,5})',text)
    res=[int(vm.group(1)),int(vm.group(2))] if vm else [0,0]
    return duration,'Audio:' in text,res

def scene_cuts(path:Path,max_seconds=60):
    p=run([FFMPEG,'-hide_banner','-t',str(max_seconds),'-i',str(path),'-vf',"select='gt(scene,0.27)',showinfo",'-an','-f','null','-'],180,False)
    vals=[float(x) for x in re.findall(r'pts_time:([0-9.]+)',p.stderr or '')]
    out=[]
    for x in vals:
        if x>.45 and (not out or x-out[-1]>=.45):out.append(round(x,2))
        if len(out)>=28:break
    return out

def motion_score(path:Path,at:float):
    p=run([FFMPEG,'-hide_banner','-ss',str(max(0,at)),'-t','.9','-i',str(path),'-vf','fps=6,tblend=all_mode=difference,signalstats,metadata=print','-an','-f','null','-'],60,False)
    text=(p.stdout or '')+'\n'+(p.stderr or '')
    vals=[float(x) for x in re.findall(r'lavfi\.signalstats\.YAVG=([\d.]+)',text)]
    raw=statistics.mean(vals) if vals else 10.0
    return round(max(0,min(1,raw/30.0)),3)

def audio_score(path:Path,at:float,has_audio:bool):
    if not has_audio:return 0.0
    p=run([FFMPEG,'-hide_banner','-ss',str(max(0,at)),'-t','1.15','-i',str(path),'-vn','-af','volumedetect','-f','null','-'],60,False)
    m=re.search(r'mean_volume:\s*(-?[\d.]+) dB',p.stderr or '')
    dbv=float(m.group(1)) if m else -30.0
    return round(max(0,min(1,(dbv+42.0)/34.0)),3)

def black_ratio(path:Path,start=0.0,span=.8):
    p=run([FFMPEG,'-hide_banner','-ss',str(max(0,start)),'-t',str(max(.4,span)),'-i',str(path),'-vf','blackdetect=d=.10:pix_th=.08','-an','-f','null','-'],80,False)
    spans=re.findall(r'black_start:([\d.]+)\s+black_end:([\d.]+)',p.stderr or '')
    black=sum(max(0,float(b)-float(a)) for a,b in spans)
    return min(1.0,black/max(span,.1))

def freeze_ratio(path:Path,duration:float):
    span=min(max(duration,1.0),22.0)
    p=run([FFMPEG,'-hide_banner','-t',str(span),'-i',str(path),'-vf','freezedetect=n=-45dB:d=.35','-an','-f','null','-'],120,False)
    starts=[float(x) for x in re.findall(r'freeze_start:\s*([\d.]+)',p.stderr or '')]
    ends=[float(x) for x in re.findall(r'freeze_end:\s*([\d.]+)',p.stderr or '')]
    total=0.0
    for i,a in enumerate(starts):total+=max(0,(ends[i] if i<len(ends) else span)-a)
    return min(1.0,total/max(span,.1))

def candidate_points(duration,cuts):
    pts=[.35]
    for c in cuts:pts += [max(0,c-.5),c+.05]
    if duration>3:pts += [duration*x for x in (.15,.30,.47,.64,.80)]
    uniq=[]
    for x in pts:
        x=round(max(0,min(max(0,duration-1),x)),2)
        if all(abs(x-u)>.7 for u in uniq):uniq.append(x)
    if len(uniq)<=MOMENT_SAMPLES:return uniq
    step=max(1,len(uniq)//MOMENT_SAMPLES)
    return uniq[::step][:MOMENT_SAMPLES]

def analyze_asset(path:Path,asset_id:str,name:str,role:str,metadata=None):
    old=(metadata or {}).get('directorAnalysis',{}) if isinstance(metadata,dict) else {}
    if isinstance(old,dict) and old.get('version')==ANALYSIS_VERSION:
        return {**old,'id':asset_id,'name':name,'role':role},False
    duration,has_audio,res=probe(path);cuts=scene_cuts(path);moments=[]
    for at in candidate_points(duration,cuts):
        mot=motion_score(path,at);aud=audio_score(path,at,has_audio)
        nearest=min([abs(at-c) for c in cuts],default=9.0);cut_bonus=max(0,1-nearest/1.4)
        black=black_ratio(path,at,.75)
        score=100*(.47*mot+.25*aud+.18*cut_bonus+.10*(1-black))
        moments.append({'start':at,'score':round(score,1),'motion':mot,'audio':aud,'cutBonus':round(cut_bonus,3),'black':round(black,3)})
    moments.sort(key=lambda x:x['score'],reverse=True)
    gaps=[];prev=0.0
    for c in cuts:
        if .35<c-prev<8:gaps.append(c-prev)
        prev=c
    pace=statistics.median(gaps) if gaps else 2.1
    analysis={'version':ANALYSIS_VERSION,'duration':round(duration,2),'hasAudio':has_audio,'resolution':res,'cuts':cuts,'cutRate':round(len(cuts)/max(duration,1),3),'naturalPace':round(max(.9,min(3.8,pace)),2),'moments':moments[:7],'avgMomentScore':round(statistics.mean([m['score'] for m in moments[:5]]) if moments else 35.0,1)}
    return {**analysis,'id':asset_id,'name':name,'role':role},True

def style_fingerprint(refs):
    if not refs:return {'source':'default','pace':2.0,'cutRate':.4,'intensity':.55}
    pace=statistics.median([r.get('naturalPace',2.0) for r in refs]);cut_rate=statistics.mean([r.get('cutRate',.4) for r in refs])
    moments=[m for r in refs for m in r.get('moments',[])[:4]]
    intensity=(statistics.mean([m.get('score',50) for m in moments])/100.0) if moments else .5
    return {'source':'references','pace':round(max(.9,min(3.3,pace)),2),'cutRate':round(cut_rate,3),'intensity':round(max(0,min(1,intensity)),3)}

def content_profile(sources):
    moments=[m for s in sources for m in s.get('moments',[])[:4]]
    motion=statistics.mean([m.get('motion',.4) for m in moments]) if moments else .4
    return {'motion':round(motion,3),'tempo':'chaotic' if motion>.67 else 'dynamic' if motion>.47 else 'controlled'}
