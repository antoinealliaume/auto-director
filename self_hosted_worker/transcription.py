# -*- coding: utf-8 -*-
"""Conservative local speech-to-text for the PC worker.

Uses faster-whisper with word timestamps + Silero VAD when enabled. Everything
is best-effort and bounded: if transcription is unavailable the video pipeline
continues with the core Director.
"""
import os
import subprocess
import tempfile
from pathlib import Path

from imageio_ffmpeg import get_ffmpeg_exe

ENABLED = os.environ.get('LOCAL_TRANSCRIBE', '0') == '1'
MODEL_NAME = os.environ.get('LOCAL_WHISPER_MODEL', 'tiny') or 'tiny'
CPU_THREADS = max(1, min(3, int(os.environ.get('LOCAL_WHISPER_THREADS', '1'))))
MAX_SECONDS = max(15, min(180, int(os.environ.get('LOCAL_WHISPER_MAX_SECONDS', '90'))))
MAX_SEGMENTS = max(4, min(40, int(os.environ.get('LOCAL_WHISPER_MAX_SEGMENTS', '22'))))
MAX_WORDS = max(40, min(500, int(os.environ.get('LOCAL_WHISPER_MAX_WORDS', '240'))))
_model = None
_failed = False


def enabled():
    return bool(ENABLED and not _failed)


def _get_model():
    global _model, _failed
    if _model is not None:return _model
    if not ENABLED or _failed:return None
    try:
        from faster_whisper import WhisperModel
        _model = WhisperModel(MODEL_NAME,device='cpu',compute_type='int8',cpu_threads=CPU_THREADS,num_workers=1)
        return _model
    except Exception as exc:
        _failed = True
        print('Local transcription disabled:', type(exc).__name__, str(exc)[:180], flush=True)
        return None


def _bounded_audio(path: Path):
    handle=tempfile.NamedTemporaryFile(prefix='ad_transcribe_',suffix='.wav',delete=False);clip=Path(handle.name);handle.close()
    try:
        p=subprocess.run(
            [get_ffmpeg_exe(),'-y','-t',str(MAX_SECONDS),'-i',str(path),'-vn','-ac','1','-ar','16000','-c:a','pcm_s16le',str(clip)],
            stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,timeout=MAX_SECONDS+60,
        )
        if p.returncode:raise RuntimeError((p.stderr or p.stdout or 'FFmpeg transcription clip failed')[-1200:])
        return clip
    except Exception:
        try:clip.unlink(missing_ok=True)
        except Exception:pass
        raise


def transcribe_clip(path: Path):
    model = _get_model()
    if model is None:return {'enabled': False, 'model': None, 'segments': [], 'words': [], 'text': ''}
    clip=None
    try:
        clip=_bounded_audio(path)
        segments, info = model.transcribe(
            str(clip),beam_size=1,best_of=1,vad_filter=True,
            vad_parameters=dict(min_silence_duration_ms=320,speech_pad_ms=120),
            word_timestamps=True,condition_on_previous_text=False,temperature=0.0,language=None,
        )
        out=[];words=[]
        for seg in segments:
            if float(seg.start) > MAX_SECONDS:break
            text=' '.join(str(seg.text or '').strip().split())
            seg_words=[]
            for w in (getattr(seg,'words',None) or []):
                ws=float(getattr(w,'start',0) or 0);we=float(getattr(w,'end',ws) or ws)
                if ws>MAX_SECONDS:break
                token=' '.join(str(getattr(w,'word','') or '').split())
                if not token:continue
                item={'start':round(ws,2),'end':round(min(we,MAX_SECONDS),2),'text':token[:60]}
                prob=getattr(w,'probability',None)
                if prob is not None:
                    try:item['probability']=round(float(prob),3)
                    except Exception:pass
                seg_words.append(item);words.append(item)
                if len(words)>=MAX_WORDS:break
            if text:
                out.append({'start':round(float(seg.start),2),'end':round(min(float(seg.end),MAX_SECONDS),2),'text':text[:220],'words':seg_words[:50]})
            if len(out)>=MAX_SEGMENTS or len(words)>=MAX_WORDS:break
        full=' '.join(x['text'] for x in out)[:2200]
        return {
            'enabled':True,'model':MODEL_NAME,'language':getattr(info,'language',None),
            'languageProbability':round(float(getattr(info,'language_probability',0) or 0),3),
            'segments':out,'words':words[:MAX_WORDS],'text':full,
        }
    except Exception as exc:
        print('Local transcription fallback:', type(exc).__name__, str(exc)[:180], flush=True)
        return {'enabled':False,'model':MODEL_NAME,'segments':[],'words':[],'text':'','error':type(exc).__name__}
    finally:
        if clip:
            try:clip.unlink(missing_ok=True)
            except Exception:pass


def speech_window_near(transcript, at: float, window: float = 2.6):
    segs=transcript.get('segments',[]) if isinstance(transcript,dict) else []
    if not segs:return None
    at=float(at or 0);candidates=[]
    for seg in segs:
        start=float(seg.get('start',0));end=float(seg.get('end',start))
        distance=0.0 if start<=at<=end else min(abs(at-start),abs(at-end))
        if distance<=window:candidates.append((distance,start,end,str(seg.get('text','')).strip()))
    if not candidates:return None
    _,start,end,text=min(candidates,key=lambda x:x[0])
    return {'start':start,'end':end,'text':text[:120]}


def text_near(transcript, at: float, window: float = 2.6):
    hit=speech_window_near(transcript,at,window)
    return (hit.get('text','') if hit else '')[:100]


def caption_for_window(transcript,start:float,end:float,max_chars=78):
    words=transcript.get('words',[]) if isinstance(transcript,dict) else []
    picked=[]
    for word in words:
        ws=float(word.get('start',0));we=float(word.get('end',ws))
        if we<start-.12 or ws>end+.12:continue
        token=str(word.get('text','')).strip()
        if token:picked.append(token)
        if len(' '.join(picked))>=max_chars:break
    text=' '.join(picked).strip()
    if not text:
        hit=speech_window_near(transcript,(start+end)/2,max(1.2,(end-start)/2+.4));text=hit.get('text','') if hit else ''
    text=' '.join(text.split()).strip(' -–—')
    if len(text)>max_chars:
        cut=text[:max_chars].rsplit(' ',1)[0].strip();text=cut or text[:max_chars]
    return text


def enrich_analysis(analysis: dict, transcript: dict):
    if not transcript.get('segments'):
        analysis['transcript']={'enabled':bool(transcript.get('enabled')),'model':transcript.get('model'),'segments':[],'words':[],'text':''}
        return analysis
    for moment in analysis.get('moments',[]):
        hit=speech_window_near(transcript,float(moment.get('start',0)),1.8)
        if hit:
            phrase=hit['text'];base=float(moment.get('score',0))
            moment['score']=round(min(100,base+min(8.5,2.0+len(phrase)/22.0)),1)
            moment['speech']=phrase;moment['speechStart']=round(float(hit['start']),2);moment['speechEnd']=round(float(hit['end']),2)
    analysis['moments']=sorted(analysis.get('moments',[]),key=lambda x:float(x.get('score',0)),reverse=True)
    analysis['transcript']={
        'enabled':bool(transcript.get('enabled')),'model':transcript.get('model'),'language':transcript.get('language'),
        'segments':transcript.get('segments',[])[:MAX_SEGMENTS],'words':transcript.get('words',[])[:MAX_WORDS],'text':transcript.get('text','')[:2200],
    }
    analysis['spokenText']=transcript.get('text','')[:1000]
    return analysis


def apply_segment_captions(plan: dict, sources: list[dict]):
    by_id={str(s.get('id')):s for s in sources};changed=0
    for i,seg in enumerate(plan.get('segments',[])):
        src=by_id.get(str(seg.get('assetId')))
        if not src:continue
        start=float(seg.get('start',0));duration=float(seg.get('duration',0) or 0);speed=max(.85,min(1.25,float(seg.get('speed',1.0) or 1.0)));end=start+duration*speed
        phrase=caption_for_window(src.get('transcript') or {},start,end,78)
        if not phrase:continue
        if not seg.get('caption') or i==0:
            seg['caption']=phrase;changed+=1
    return plan,changed
