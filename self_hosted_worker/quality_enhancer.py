# -*- coding: utf-8 -*-
"""Optional high-quality audio analysis for the Windows worker.

Uses librosa (ISC) when the hardware profile enables the quality engine. The
pipeline is strictly best-effort: any dependency/model failure falls back to the
core FFmpeg analyzer without failing the user's render.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

from engine.config import FFMPEG, run


def _bounded_int(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(maximum, value))


ENABLED=os.environ.get('LOCAL_QUALITY_ENGINE','0')=='1'
AUDIO_ENABLED=os.environ.get('AUDIO_BEAT_ANALYSIS','0')=='1'
MAX_SECONDS=_bounded_int('QUALITY_AUDIO_MAX_SECONDS',120,20,180)
_failed=False


def enabled():
    return bool(ENABLED and not _failed)


def _nearest(values,at):
    if not values:return 999.0
    return min(abs(float(x)-float(at)) for x in values)


def analyze_audio(path:Path):
    global _failed
    if not enabled() or not AUDIO_ENABLED:return {'enabled':False,'beats':[],'onsets':[]}
    wav=None
    try:
        import librosa
        import numpy as np
        handle=tempfile.NamedTemporaryFile(prefix='ad_quality_',suffix='.wav',delete=False);wav=Path(handle.name);handle.close()
        run([FFMPEG,'-y','-t',str(MAX_SECONDS),'-i',str(path),'-vn','-ac','1','-ar','22050','-c:a','pcm_s16le',str(wav)],180)
        y,sr=librosa.load(str(wav),sr=22050,mono=True,duration=MAX_SECONDS)
        if y is None or len(y)<sr:return {'enabled':True,'beats':[],'onsets':[],'tempoBpm':0}
        onset_env=librosa.onset.onset_strength(y=y,sr=sr)
        onset_times=librosa.onset.onset_detect(onset_envelope=onset_env,sr=sr,units='time',backtrack=True)
        onsets=[round(float(x),3) for x in onset_times[:120] if float(x)>=0]
        beats=[];tempo=0.0
        try:
            bpm,beat_times=librosa.beat.beat_track(onset_envelope=onset_env,sr=sr,units='time',trim=False)
            if isinstance(bpm,np.ndarray):bpm=float(bpm.reshape(-1)[0]) if bpm.size else 0.0
            tempo=float(bpm or 0);beats=[round(float(x),3) for x in beat_times[:160] if float(x)>=0]
        except Exception as exc:
            print('Beat tracker fallback:',type(exc).__name__,str(exc)[:90],flush=True)
        rms=librosa.feature.rms(y=y,frame_length=2048,hop_length=512)[0]
        dynamic=float(np.percentile(rms,90)-np.percentile(rms,25)) if len(rms) else 0.0
        return {'enabled':True,'beats':beats,'onsets':onsets,'tempoBpm':round(tempo,1),'audioDynamics':round(dynamic,5)}
    except Exception as exc:
        _failed=True
        print('Local quality audio disabled:',type(exc).__name__,str(exc)[:160],flush=True)
        return {'enabled':False,'beats':[],'onsets':[],'error':type(exc).__name__}
    finally:
        if wav:
            try:wav.unlink(missing_ok=True)
            except Exception:pass


def enrich_analysis(path:Path,analysis:dict):
    features=analyze_audio(path)
    if not features.get('enabled'):
        analysis['qualityAudio']={'enabled':False}
        return analysis
    beats=features.get('beats',[]);onsets=features.get('onsets',[])
    for moment in analysis.get('moments',[]):
        at=float(moment.get('start',0) or 0);onset_delta=_nearest(onsets,at);beat_delta=_nearest(beats,at)
        onset_bonus=max(0.0,1-onset_delta/.28) if onset_delta<.28 else 0.0
        beat_bonus=max(0.0,1-beat_delta/.20) if beat_delta<.20 else 0.0
        moment['onsetBonus']=round(onset_bonus,3);moment['beatProximity']=round(beat_bonus,3)
        if onset_bonus>0:
            moment['score']=round(min(100,float(moment.get('score',0))+5.5*onset_bonus+2.0*beat_bonus),1)
    analysis['moments']=sorted(analysis.get('moments',[]),key=lambda x:float(x.get('score',0)),reverse=True)
    analysis['beats']=beats;analysis['onsets']=onsets;analysis['tempoBpm']=features.get('tempoBpm',0)
    analysis['qualityAudio']={'enabled':True,'tempoBpm':features.get('tempoBpm',0),'beatCount':len(beats),'onsetCount':len(onsets),'audioDynamics':features.get('audioDynamics',0)}
    return analysis
