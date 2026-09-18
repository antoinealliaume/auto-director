# -*- coding: utf-8 -*-
import os
import re
import statistics
from pathlib import Path

from .config import ANALYSIS_VERSION, FFMPEG, MOMENT_SAMPLES, run
from .quality import shot_for_time, shots_from_cuts


def probe(path:Path):
    text=run([FFMPEG,'-hide_banner','-i',str(path)],45,False).stderr or ''
    m=re.search(r'Duration:\s*(\d+):(\d+):([\d.]+)',text)
    duration=int(m.group(1))*3600+int(m.group(2))*60+float(m.group(3)) if m else 0.0
    vm=re.search(r'Video:.*?(\d{2,5})x(\d{2,5})',text)
    res=[int(vm.group(1)),int(vm.group(2))] if vm else [0,0]
    return duration,'Audio:' in text,res


def _pyscenedetect_cuts(path:Path,max_seconds=60):
    if os.environ.get('ADVANCED_SCENE_DETECT','0')!='1':return []
    try:
        from scenedetect import SceneManager, open_video
        from scenedetect.detectors import AdaptiveDetector
        video=open_video(str(path));fps=max(1.0,float(video.frame_rate or 30))
        manager=SceneManager();manager.add_detector(AdaptiveDetector(adaptive_threshold=3.0,min_scene_len=max(8,int(fps*.32))))
        end_time=video.base_timecode+int(max_seconds*fps)
        manager.detect_scenes(video,end_time=end_time,show_progress=False)
        scenes=manager.get_scene_list(start_in_scene=True)
        values=[round(float(start.get_seconds()),2) for start,_ in scenes[1:]]
        return [x for x in values if .35<x<max_seconds]
    except Exception as exc:
        print('PySceneDetect fallback:',type(exc).__name__,str(exc)[:100],flush=True)
        return []


def scene_cuts(path:Path,max_seconds=60):
    advanced=_pyscenedetect_cuts(path,max_seconds)
    if advanced:return advanced[:36]
    p=run([FFMPEG,'-hide_banner','-t',str(max_seconds),'-i',str(path),'-vf',"select='gt(scene,0.27)',showinfo",'-an','-f','null','-'],180,False)
    vals=[float(x) for x in re.findall(r'pts_time:([0-9.]+)',p.stderr or '')]
    out=[]
    for x in vals:
        if x>.45 and (not out or x-out[-1]>=.45):out.append(round(x,2))
        if len(out)>=32:break
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


def smart_focus(path:Path,at:float):
    """Estimate where visible action lives. Optional OpenCV, safe center fallback."""
    if os.environ.get('SMART_CROP','0')!='1':return .5,.5,0.0
    try:
        import cv2
        import numpy as np
        cap=cv2.VideoCapture(str(path));frames=[]
        for delta in (0,.16,.32,.52):
            cap.set(cv2.CAP_PROP_POS_MSEC,max(0,float(at)+delta)*1000)
            ok,frame=cap.read()
            if not ok or frame is None:continue
            h,w=frame.shape[:2];scale=min(1.0,320/max(1,w));frame=cv2.resize(frame,(max(2,int(w*scale)),max(2,int(h*scale))))
            frames.append(cv2.cvtColor(frame,cv2.COLOR_BGR2GRAY))
        cap.release()
        if len(frames)<2:return .5,.5,0.0
        heat=np.zeros_like(frames[0],dtype=np.float32)
        prev=frames[0]
        for cur in frames[1:]:
            heat+=cv2.GaussianBlur(cv2.absdiff(cur,prev),(5,5),0).astype(np.float32);prev=cur
        edges=cv2.Laplacian(frames[-1],cv2.CV_32F);heat+=np.abs(edges)*.10
        threshold=float(np.percentile(heat,72));mask=np.where(heat>=threshold,heat,0)
        total=float(mask.sum())
        if total<=1:return .5,.5,0.0
        ys,xs=np.indices(mask.shape);fx=float((mask*xs).sum()/total/max(1,mask.shape[1]-1));fy=float((mask*ys).sum()/total/max(1,mask.shape[0]-1))
        confidence=min(1.0,total/(mask.size*18.0));return round(max(.12,min(.88,fx)),3),round(max(.14,min(.86,fy)),3),round(confidence,3)
    except Exception as exc:
        print('Smart crop fallback:',type(exc).__name__,str(exc)[:90],flush=True)
        return .5,.5,0.0


def candidate_points(duration,cuts):
    pts=[.30]
    shots=shots_from_cuts(duration,cuts)
    for shot in shots:
        start=float(shot['start']);end=float(shot['end']);span=end-start
        if span>.7:pts.append(start+.08)
        if span>1.8:pts.append(start+min(.75,span*.38))
    for c in cuts:pts += [max(0,c-.55),c+.06]
    if duration>3:pts += [duration*x for x in (.12,.27,.44,.62,.79,.91)]
    uniq=[]
    for x in pts:
        x=round(max(0,min(max(0,duration-1),x)),2)
        if all(abs(x-u)>.55 for u in uniq):uniq.append(x)
    if len(uniq)<=MOMENT_SAMPLES:return uniq
    # Preserve temporal coverage instead of accidentally sampling only the intro.
    uniq=sorted(uniq)
    step=(len(uniq)-1)/max(1,MOMENT_SAMPLES-1)
    picks=[]
    for i in range(MOMENT_SAMPLES):
        x=uniq[min(len(uniq)-1,round(i*step))]
        if x not in picks:picks.append(x)
    return picks[:MOMENT_SAMPLES]


def analyze_asset(path:Path,asset_id:str,name:str,role:str,metadata=None):
    old=(metadata or {}).get('directorAnalysis',{}) if isinstance(metadata,dict) else {}
    if isinstance(old,dict) and old.get('version')==ANALYSIS_VERSION:
        return {**old,'id':asset_id,'name':name,'role':role},False
    duration,has_audio,res=probe(path);cuts=scene_cuts(path);shots=shots_from_cuts(duration,cuts);moments=[]
    for at in candidate_points(duration,cuts):
        mot=motion_score(path,at);aud=audio_score(path,at,has_audio)
        nearest=min([abs(at-c) for c in cuts],default=9.0);cut_bonus=max(0,1-nearest/1.25)
        black=black_ratio(path,at,.75);focus_x,focus_y,focus_conf=smart_focus(path,at);shot=shot_for_time(shots,at) or {}
        # Prefer crisp, audible, active moments close to natural edit points. Smart
        # focus confidence gives only a small bonus; it must never dominate content.
        score=100*(.43*mot+.25*aud+.18*cut_bonus+.10*(1-black)+.04*focus_conf)
        moments.append({
            'start':at,'score':round(score,1),'motion':mot,'audio':aud,'cutBonus':round(cut_bonus,3),'black':round(black,3),
            'focusX':focus_x,'focusY':focus_y,'focusConfidence':focus_conf,
            'shotStart':shot.get('start'),'shotEnd':shot.get('end'),'shotIndex':shot.get('index'),
        })
    moments.sort(key=lambda x:x['score'],reverse=True)
    gaps=[float(s['duration']) for s in shots if .35<float(s['duration'])<8]
    pace=statistics.median(gaps) if gaps else 2.1
    analysis={
        'version':ANALYSIS_VERSION,'duration':round(duration,2),'hasAudio':has_audio,'resolution':res,'cuts':cuts,'shots':shots[:40],
        'sceneDetector':'pyscenedetect' if os.environ.get('ADVANCED_SCENE_DETECT','0')=='1' else 'ffmpeg',
        'cutRate':round(len(cuts)/max(duration,1),3),'naturalPace':round(max(.85,min(3.8,pace)),2),'moments':moments[:max(7,MOMENT_SAMPLES)],
        'avgMomentScore':round(statistics.mean([m['score'] for m in moments[:5]]) if moments else 35.0,1),
    }
    return {**analysis,'id':asset_id,'name':name,'role':role},True


def style_fingerprint(refs):
    if not refs:return {'source':'default','pace':2.0,'cutRate':.4,'intensity':.55}
    pace=statistics.median([r.get('naturalPace',2.0) for r in refs]);cut_rate=statistics.mean([r.get('cutRate',.4) for r in refs])
    moments=[m for r in refs for m in r.get('moments',[])[:4]]
    intensity=(statistics.mean([m.get('score',50) for m in moments])/100.0) if moments else .5
    return {'source':'references','pace':round(max(.85,min(3.3,pace)),2),'cutRate':round(cut_rate,3),'intensity':round(max(0,min(1,intensity)),3)}


def content_profile(sources):
    moments=[m for s in sources for m in s.get('moments',[])[:4]]
    motion=statistics.mean([m.get('motion',.4) for m in moments]) if moments else .4
    audio=statistics.mean([m.get('audio',.3) for m in moments]) if moments else .3
    speech=sum(1 for m in moments if m.get('speech'))/max(1,len(moments))
    return {'motion':round(motion,3),'audio':round(audio,3),'speechDensity':round(speech,3),'tempo':'chaotic' if motion>.67 else 'dynamic' if motion>.47 else 'controlled'}
