# -*- coding: utf-8 -*-
"""V8.6 PC worker extensions: adaptive local speech understanding.

The core HTTPS worker stays stable. This entry point decorates its analysis and
Director refinement with optional faster-whisper transcription, then runs the
same production loop.
"""
import http_worker as base
from transcription import apply_segment_captions, enabled as transcription_enabled, enrich_analysis, transcribe_clip

_original_analyze = base.analyze_asset
_original_refine = base.refine_plan


def analyze_with_speech(path, asset_id, name, role, metadata=None):
    analysis, changed = _original_analyze(path, asset_id, name, role, metadata)
    if role != 'reference' and transcription_enabled():
        transcript = transcribe_clip(path)
        analysis = enrich_analysis(analysis, transcript)
        if transcript.get('segments'):
            print(f"Speech: {name} · {len(transcript['segments'])} segment(s) · {transcript.get('language') or '?'}", flush=True)
    return analysis, changed


def refine_with_speech(project_name, plan, sources, paths, workdir):
    plan, diag = _original_refine(project_name, plan, sources, paths, workdir)
    plan, count = apply_segment_captions(plan, sources)
    diag = dict(diag or {})
    diag['speechCaptions'] = count
    diag['transcription'] = 'local' if transcription_enabled() else 'off'
    return plan, diag


def heartbeat_with_features():
    payload = base.heartbeat_payload()
    # Unknown fields are deliberately harmless server-side; this is also useful
    # for future Studio versions that expose the feature badge.
    payload['transcription'] = bool(transcription_enabled())
    return payload


base.analyze_asset = analyze_with_speech
base.refine_plan = refine_with_speech
base.heartbeat_payload = heartbeat_with_features

if __name__ == '__main__':
    print('PC intelligence: local speech=' + ('on' if transcription_enabled() else 'off'), flush=True)
    base.main()
