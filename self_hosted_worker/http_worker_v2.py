# -*- coding: utf-8 -*-
"""V9.1 PC worker extensions: speech + open-source quality analysis.

The core HTTPS worker stays stable. This entry point decorates analysis and
Director refinement with optional faster-whisper + librosa/OpenCV/PySceneDetect
features, then runs the same production loop.
"""
import http_worker as base
from quality_enhancer import enabled as quality_enabled, enrich_analysis as enrich_quality
from transcription import apply_segment_captions, enabled as transcription_enabled, enrich_analysis as enrich_speech, transcribe_clip

_original_analyze=base.analyze_asset
_original_refine=base.refine_plan


def analyze_with_intelligence(path,asset_id,name,role,metadata=None):
    analysis,changed=_original_analyze(path,asset_id,name,role,metadata)
    if role!='reference' and quality_enabled():
        analysis=enrich_quality(path,analysis)
        qa=analysis.get('qualityAudio') or {}
        if qa.get('enabled'):
            print(f"Quality audio: {name} · {qa.get('tempoBpm',0)} BPM · {qa.get('onsetCount',0)} impacts",flush=True)
    if role!='reference' and transcription_enabled():
        transcript=transcribe_clip(path);analysis=enrich_speech(analysis,transcript)
        if transcript.get('segments'):
            print(f"Speech: {name} · {len(transcript['segments'])} segment(s) · {transcript.get('language') or '?'}",flush=True)
    return analysis,changed


def refine_with_intelligence(project_name,plan,sources,paths,workdir):
    plan,diag=_original_refine(project_name,plan,sources,paths,workdir)
    plan,count=apply_segment_captions(plan,sources)
    diag=dict(diag or {});diag['speechCaptions']=count;diag['transcription']='local' if transcription_enabled() else 'off';diag['qualityEngine']='local-open-source' if quality_enabled() else 'core'
    return plan,diag


def heartbeat_with_features():
    payload=base.heartbeat_payload();payload['transcription']=bool(transcription_enabled());payload['qualityEngine']=bool(quality_enabled());return payload


base.analyze_asset=analyze_with_intelligence
base.refine_plan=refine_with_intelligence
base.heartbeat_payload=heartbeat_with_features

if __name__=='__main__':
    print('PC intelligence: speech='+('on' if transcription_enabled() else 'off')+' · quality='+('on' if quality_enabled() else 'off'),flush=True)
    base.main()
