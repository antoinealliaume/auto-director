# -*- coding: utf-8 -*-
"""Montage-aware helpers used by the Director and Critic.

Pure-Python on purpose: cloud rendering always has these quality rules, while
optional PC open-source analyzers can enrich the same fields with beats, speech
boundaries and smart-crop coordinates.
"""
from __future__ import annotations

import math
import statistics


def clamp(value, low, high):
    return max(low, min(high, value))


def shots_from_cuts(duration: float, cuts):
    duration=max(0.0,float(duration or 0))
    clean=[]
    for raw in cuts or []:
        try:value=float(raw)
        except Exception:continue
        if .08<value<duration-.08 and (not clean or value-clean[-1]>.18):clean.append(value)
    bounds=[0.0]+clean+([duration] if duration>0 else [])
    shots=[]
    for i in range(max(0,len(bounds)-1)):
        start,end=bounds[i],bounds[i+1]
        if end-start<.18:continue
        shots.append({'index':i,'start':round(start,3),'end':round(end,3),'duration':round(end-start,3)})
    return shots


def shot_for_time(shots, at: float):
    at=float(at or 0)
    for shot in shots or []:
        if float(shot['start'])-.02<=at<float(shot['end'])+.02:return shot
    return (shots or [None])[-1]


def nearest_event(events, at: float, max_delta: float):
    values=[]
    for x in events or []:
        try:values.append(float(x))
        except Exception:pass
    if not values:return None
    candidate=min(values,key=lambda x:abs(x-at))
    return candidate if abs(candidate-at)<=max_delta else None


def event_sync_score(events, at: float, tolerance: float=.18):
    if not events:return .5
    delta=min(abs(float(x)-float(at)) for x in events)
    return round(clamp(1-delta/max(tolerance,.01),0,1),3)


def rhythm_duration(base: float, elapsed: float, target: float, strategy: str, intensity: str='balanced'):
    """Create a deliberate hook/body/payoff rhythm instead of uniform cuts."""
    base=max(.62,float(base or 1.6));target=max(1.0,float(target or 18));progress=clamp(float(elapsed or 0)/target,0,1)
    if progress<.18:mult=.70 if intensity=='aggressive' else .80 if intensity=='balanced' else .92
    elif progress>.76:
        if strategy in {'tease_payoff','clean_story','escalation'}:mult=1.18
        else:mult=.84 if intensity=='aggressive' else .95
    else:mult=1.0
    if strategy=='speedrun':mult*=.82
    elif strategy=='clean_story':mult*=1.10
    return round(clamp(base*mult,.62,4.2),3)


def fit_segment(moment: dict, source: dict, desired: float, remaining: float, strategy: str):
    """Snap a selected moment to natural editorial boundaries when possible."""
    source_duration=max(0.0,float(source.get('duration',moment.get('sourceDuration',0)) or 0))
    start=max(0.0,float(moment.get('start',0) or 0));desired=max(.62,float(desired or 1.2));remaining=max(.2,float(remaining or desired))
    shot_start=moment.get('shotStart');shot_end=moment.get('shotEnd')
    speech_start=moment.get('speechStart');speech_end=moment.get('speechEnd')
    beats=source.get('beats') or [];onsets=source.get('onsets') or []
    alignment=[]

    # Story/dialogue modes should not begin in the middle of a spoken phrase.
    if strategy in {'clean_story','escalation'} and speech_start is not None:
        ss=float(speech_start)
        if abs(ss-start)<=.48 and ss>=0:start=ss;alignment.append('speech_start')
    elif shot_start is not None:
        ss=float(shot_start)
        if 0<=start-ss<=.34:start=ss+.02;alignment.append('shot_start')
    onset=nearest_event(onsets,start,.16)
    if onset is not None and onset>=0:
        start=max(0,onset);alignment.append('onset_start')

    max_available=(source_duration-start-.04) if source_duration>0 else desired
    duration=min(desired,remaining,max_available)
    if duration<.62:return None
    target_end=start+duration

    candidates=[]
    if strategy in {'clean_story','escalation'} and speech_end is not None:
        se=float(speech_end)
        if start+.62<=se<=start+min(desired*1.55,remaining):candidates.append((abs(se-target_end)*.72,se,'speech_end'))
    beat=nearest_event(beats,target_end,.24)
    if beat is not None and beat>=start+.62:candidates.append((abs(beat-target_end),beat,'beat_end'))
    onset_end=nearest_event(onsets,target_end,.18)
    if onset_end is not None and onset_end>=start+.62:candidates.append((abs(onset_end-target_end)*1.08,onset_end,'onset_end'))
    if shot_end is not None:
        se=float(shot_end)-.025
        if start+.62<=se<=start+min(desired*1.35,remaining):candidates.append((abs(se-target_end)*.92,se,'shot_end'))
    if candidates:
        _,chosen,label=min(candidates,key=lambda x:x[0]);duration=chosen-start;alignment.append(label)
    duration=min(duration,remaining,max_available)
    if duration<.62:return None
    end=start+duration
    beat_sync=event_sync_score(beats,end,.24) if beats else .5
    return {
        'start':round(start,3),'duration':round(duration,3),'end':round(end,3),
        'alignment':alignment,'beatSync':beat_sync,
    }


def continuity_penalty(previous: dict | None, current: dict):
    if not previous:return 0.0
    penalty=0.0
    if str(previous.get('assetId'))==str(current.get('assetId')):
        gap=abs(float(previous.get('start',0))-float(current.get('start',0)))
        penalty+=.30 if gap<2.0 else .12
    pm=float(previous.get('motion',.4));cm=float(current.get('motion',.4))
    if abs(pm-cm)>.65:penalty+=.07
    px=previous.get('focusX');cx=current.get('focusX')
    if px is not None and cx is not None and abs(float(px)-float(cx))>.58:penalty+=.05
    return round(penalty,3)


def cadence_metrics(segments):
    durations=[float(s.get('duration',0) or 0) for s in segments or [] if float(s.get('duration',0) or 0)>.05]
    if not durations:return {'mean':0,'variation':0,'tooLong':0,'tooShort':0,'beatSync':.5,'alignment':0}
    mean=statistics.mean(durations);variation=(statistics.pstdev(durations)/mean) if len(durations)>1 and mean else 0
    too_long=sum(1 for x in durations if x>3.7);too_short=sum(1 for x in durations if x<.58)
    beat=[float(s.get('beatSync',.5) or .5) for s in segments]
    aligned=sum(1 for s in segments if s.get('alignment'))/max(1,len(segments))
    return {
        'mean':round(mean,3),'variation':round(variation,3),'tooLong':too_long,'tooShort':too_short,
        'beatSync':round(statistics.mean(beat) if beat else .5,3),'alignment':round(aligned,3),
    }


def sequence_quality(segments):
    if not segments:return 0.0
    repeats=0
    for a,b in zip(segments,segments[1:]):
        if str(a.get('assetId'))==str(b.get('assetId')):repeats+=1
    repeat_score=1-repeats/max(1,len(segments)-1)
    cadence=cadence_metrics(segments)
    variation_fit=1-clamp(abs(cadence['variation']-.28)/.55,0,1)
    return round(clamp(.48*repeat_score+.30*variation_fit+.12*cadence['beatSync']+.10*cadence['alignment'],0,1),3)
