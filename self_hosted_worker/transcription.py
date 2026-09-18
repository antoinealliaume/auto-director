# -*- coding: utf-8 -*-
"""Conservative local speech-to-text for the PC worker.

This module is intentionally optional. It runs faster-whisper on CPU/int8 with a
small model and strict duration/text limits. If the dependency/model is unavailable,
the video pipeline continues without transcription.
"""
import os
from pathlib import Path

ENABLED = os.environ.get('LOCAL_TRANSCRIBE', '0') == '1'
MODEL_NAME = os.environ.get('LOCAL_WHISPER_MODEL', 'tiny') or 'tiny'
CPU_THREADS = max(1, min(3, int(os.environ.get('LOCAL_WHISPER_THREADS', '1'))))
MAX_SECONDS = max(15, min(180, int(os.environ.get('LOCAL_WHISPER_MAX_SECONDS', '90'))))
MAX_SEGMENTS = max(4, min(40, int(os.environ.get('LOCAL_WHISPER_MAX_SEGMENTS', '22'))))
_model = None
_failed = False


def enabled():
    return bool(ENABLED and not _failed)


def _get_model():
    global _model, _failed
    if _model is not None:
        return _model
    if not ENABLED or _failed:
        return None
    try:
        from faster_whisper import WhisperModel
        _model = WhisperModel(
            MODEL_NAME,
            device='cpu',
            compute_type='int8',
            cpu_threads=CPU_THREADS,
            num_workers=1,
        )
        return _model
    except Exception as exc:
        _failed = True
        print('Local transcription disabled:', type(exc).__name__, str(exc)[:180], flush=True)
        return None


def transcribe_clip(path: Path):
    model = _get_model()
    if model is None:
        return {'enabled': False, 'model': None, 'segments': [], 'text': ''}
    try:
        segments, info = model.transcribe(
            str(path),
            beam_size=1,
            best_of=1,
            vad_filter=True,
            word_timestamps=False,
            condition_on_previous_text=False,
            temperature=0.0,
            language=None,
        )
        out = []
        for seg in segments:
            if float(seg.start) > MAX_SECONDS:
                break
            text = ' '.join(str(seg.text or '').strip().split())
            if not text:
                continue
            out.append({
                'start': round(float(seg.start), 2),
                'end': round(min(float(seg.end), MAX_SECONDS), 2),
                'text': text[:180],
            })
            if len(out) >= MAX_SEGMENTS:
                break
        full = ' '.join(x['text'] for x in out)[:1600]
        return {
            'enabled': True,
            'model': MODEL_NAME,
            'language': getattr(info, 'language', None),
            'languageProbability': round(float(getattr(info, 'language_probability', 0) or 0), 3),
            'segments': out,
            'text': full,
        }
    except Exception as exc:
        print('Local transcription fallback:', type(exc).__name__, str(exc)[:180], flush=True)
        return {'enabled': False, 'model': MODEL_NAME, 'segments': [], 'text': '', 'error': type(exc).__name__}


def text_near(transcript, at: float, window: float = 2.6):
    segs = transcript.get('segments', []) if isinstance(transcript, dict) else []
    if not segs:
        return ''
    at = float(at or 0)
    candidates = []
    for seg in segs:
        start = float(seg.get('start', 0)); end = float(seg.get('end', start))
        distance = 0.0 if start <= at <= end else min(abs(at - start), abs(at - end))
        if distance <= window:
            candidates.append((distance, str(seg.get('text', '')).strip()))
    candidates.sort(key=lambda x: x[0])
    return (candidates[0][1] if candidates else '')[:90]


def enrich_analysis(analysis: dict, transcript: dict):
    """Give a small ranking bonus to moments near meaningful speech."""
    if not transcript.get('segments'):
        analysis['transcript'] = {'enabled': bool(transcript.get('enabled')), 'model': transcript.get('model'), 'segments': [], 'text': ''}
        return analysis
    for moment in analysis.get('moments', []):
        phrase = text_near(transcript, float(moment.get('start', 0)), 1.8)
        if phrase:
            base = float(moment.get('score', 0))
            # Speech matters, but visual/audio intensity remains dominant.
            moment['score'] = round(min(100, base + min(8.0, 2.0 + len(phrase) / 22.0)), 1)
            moment['speech'] = phrase
    analysis['moments'] = sorted(analysis.get('moments', []), key=lambda x: float(x.get('score', 0)), reverse=True)
    analysis['transcript'] = {
        'enabled': bool(transcript.get('enabled')),
        'model': transcript.get('model'),
        'language': transcript.get('language'),
        'segments': transcript.get('segments', [])[:MAX_SEGMENTS],
        'text': transcript.get('text', '')[:1600],
    }
    analysis['spokenText'] = transcript.get('text', '')[:800]
    return analysis


def apply_segment_captions(plan: dict, sources: list[dict]):
    """Use speech near the chosen source timestamp as a concise bottom caption."""
    by_id = {str(s.get('id')): s for s in sources}
    changed = 0
    for i, seg in enumerate(plan.get('segments', [])):
        src = by_id.get(str(seg.get('assetId')))
        if not src:
            continue
        phrase = text_near(src.get('transcript') or {}, float(seg.get('start', 0)), 2.0)
        if not phrase:
            continue
        phrase = phrase.strip(' -–—')[:78]
        if not phrase:
            continue
        # Keep deliberate Director captions such as escalation/payoff cues, except
        # on ordinary segments where the spoken line is more useful.
        if not seg.get('caption') or i == 0:
            seg['caption'] = phrase
            changed += 1
    return plan, changed
