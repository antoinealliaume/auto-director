# -*- coding: utf-8 -*-
import math
import statistics

from .memory import strategy_prior, preferred_pace
from .quality import continuity_penalty, fit_segment, rhythm_duration, sequence_quality
from .style_engine import decorate_plan

STRATEGIES=('tease_payoff','escalation','speedrun','contrast','clean_story')
MODE_STRATEGIES={
    'auto':STRATEGIES,
    'story':('clean_story','escalation','tease_payoff'),
    'funny':('contrast','tease_payoff','escalation'),
    'highlight':('tease_payoff','speedrun','escalation'),
    'fast':('speedrun','contrast','tease_payoff'),
    'clean':('clean_story','contrast'),
}
INTENSITY_MULTIPLIER={'soft':1.18,'balanced':1.0,'aggressive':.72}


def _moments(sources):
    out=[]
    for source_order,s in enumerate(sources):
        duration=max(0.0,float(s.get('duration',0) or 0))
        for rank,m in enumerate(s.get('moments',[])[:10]):
            out.append({
                'assetId':s['id'],'start':float(m.get('start',0)),'quality':float(m.get('score',35))/100.0,
                'motion':float(m.get('motion',.4)),'audio':float(m.get('audio',.3)),'rank':rank,
                'role':s.get('role','source'),'sourceOrder':source_order,'sourceDuration':duration,
                'focusX':m.get('focusX'),'focusY':m.get('focusY'),'focusConfidence':float(m.get('focusConfidence',0) or 0),
                'shotStart':m.get('shotStart'),'shotEnd':m.get('shotEnd'),'shotIndex':m.get('shotIndex'),
                'speech':m.get('speech',''),'speechStart':m.get('speechStart'),'speechEnd':m.get('speechEnd'),
                'onsetBonus':float(m.get('onsetBonus',0) or 0),
            })
    if not out:
        for source_order,s in enumerate(sources):
            out.append({'assetId':s['id'],'start':0.0,'quality':.35,'motion':.3,'audio':.2,'rank':0,'role':s.get('role','source'),'sourceOrder':source_order,'sourceDuration':float(s.get('duration',0) or 0),'focusX':.5,'focusY':.5,'focusConfidence':0})
    return out


def _duration(style,profile,strategy,revision=0,intensity='balanced'):
    pace=float(style.get('pace',2.0))
    if strategy=='speedrun':pace*=.68
    elif strategy=='tease_payoff':pace*=.86
    elif strategy=='clean_story':pace*=1.22
    elif strategy=='contrast':pace*=.95
    pace*=INTENSITY_MULTIPLIER.get(intensity,1.0)
    if profile.get('tempo')=='chaotic':pace*=.86
    if revision:pace*=.82
    return max(.72,min(3.8,pace))


def _continuity_reorder(seq):
    """Keep strategic ranking, but avoid robotic A-A-A or violent focal jumps."""
    remaining=list(seq);out=[]
    while remaining:
        if not out:out.append(remaining.pop(0));continue
        window=remaining[:min(6,len(remaining))];prev=out[-1]
        best=min(range(len(window)),key=lambda i:continuity_penalty(prev,window[i])+.025*i-.04*float(window[i].get('quality',0)))
        out.append(remaining.pop(best))
    return out


def _order(pool,strategy,variant):
    quality=sorted(pool,key=lambda x:(x['quality']+.04*x.get('onsetBonus',0),x['motion']+.35*x['audio']),reverse=True)
    if strategy=='escalation':ordered=sorted(pool,key=lambda x:x['quality']+.04*x.get('onsetBonus',0))
    elif strategy=='contrast':
        hi=quality[:];lo=sorted(pool,key=lambda x:x['quality']);ordered=[];seen=set()
        while hi or lo:
            for arr in (hi,lo):
                if not arr:continue
                x=arr.pop(0);key=(x['assetId'],round(x['start'],1))
                if key not in seen:ordered.append(x);seen.add(key)
    elif strategy=='clean_story':ordered=sorted(pool,key=lambda x:(x['sourceOrder'],x.get('shotIndex') if x.get('shotIndex') is not None else 999,x['start']))
    elif strategy=='speedrun':ordered=sorted(pool,key=lambda x:(x['motion']+.30*x['audio']+.38*x['quality']+.08*x.get('onsetBonus',0)),reverse=True)
    else:
        top=quality[:max(3,len(quality)//2)];ordered=top[1:]+quality[len(top):]+quality[:1]
    if strategy!='clean_story':ordered=_continuity_reorder(ordered)
    if ordered and variant:ordered=ordered[variant%len(ordered):]+ordered[:variant%len(ordered)]
    return ordered


def _dedupe(seq):
    out=[];last_by_asset={};seen=set()
    for m in seq:
        a=m['assetId'];t=m['start'];key=(a,round(t,1))
        if key in seen:continue
        if a in last_by_asset and abs(t-last_by_asset[a])<.85:continue
        out.append(m);seen.add(key);last_by_asset[a]=t
    return out


def _hook(project,strategy,variant,hook_style='auto'):
    name=(project or 'ce moment')[:45]
    if hook_style=='curiosity':
        options=[f'Tu vois le détail qui change tout sur {name} ?','Regarde bien ce qui se passe juste après.']
    elif hook_style=='payoff':
        options=['Attends la fin, le meilleur arrive après.','Les dernières secondes changent complètement la scène.']
    elif hook_style=='direct':
        options=[f'Voilà exactement ce qui s’est passé sur {name}.','Le moment fort commence maintenant.']
    else:
        by_strategy={
          'tease_payoff':[f'La fin sur {name} est impossible à prédire.','Attends les 3 dernières secondes.'],
          'escalation':['Ça devient de pire en pire à chaque seconde.','Je pensais que ça allait se calmer.'],
          'speedrun':['Regarde tout ce qui se passe en quelques secondes.','Tu vas rater un détail si tu clignes des yeux.'],
          'contrast':['Le début ne prépare absolument pas à la suite.','Deux ambiances totalement opposées en quelques secondes.'],
          'clean_story':['Voici exactement comment la situation a dégénéré.','Tout part d’un détail presque invisible.'],
        }
        options=by_strategy.get(strategy,by_strategy['tease_payoff'])
    return options[variant%len(options)]


def _segment(m,fit,zoom,caption=''):
    return {
        'assetId':m['assetId'],'start':round(float(fit['start']),2),'duration':round(float(fit['duration']),2),'zoom':round(zoom,3),
        'caption':caption,'momentScore':round(m['quality']*100,1),'audioScore':round(m['audio'],3),'motion':round(m.get('motion',.4),3),
        'sourceOrder':m['sourceOrder'],'focusX':m.get('focusX',.5),'focusY':m.get('focusY',.5),'focusConfidence':m.get('focusConfidence',0),
        'alignment':fit.get('alignment',[]),'beatSync':fit.get('beatSync',.5),'speech':m.get('speech',''),
    }


def _bound_segment_speeds(plan,sources):
    """Keep styled source windows inside each asset while preserving output duration."""
    durations={str(s.get('id')):max(0.0,float(s.get('duration',0) or 0)) for s in sources}
    for seg in plan.get('segments') or []:
        total=durations.get(str(seg.get('assetId')),0.0);duration=max(0.0,float(seg.get('duration',0) or 0));start=max(0.0,float(seg.get('start',0) or 0))
        speed=max(.85,min(1.25,float(seg.get('speed',1) or 1)))
        if total>0 and duration>0:
            available=max(0.0,total-start);speed=min(speed,max(.85,available/duration))
        seg['speed']=round(speed,3)
    return plan


def make_plan(project,sources,style,profile,context,target,strategy,variant=0,revision=0,intensity='balanced',hook_style='auto'):
    pool=_dedupe(_order(_moments(sources),strategy,variant));pace=_duration(style,profile,strategy,revision,intensity)
    target=max(8,min(35,int(target)));needed=max(4,min(20,math.ceil(target/max(.72,pace*.92))))
    by_id={str(s.get('id')):s for s in sources};segs=[];used_asset_counts={};elapsed=0.0
    unique_assets=len({x['assetId'] for x in pool})
    for i,m in enumerate(pool*4):
        if len(segs)>=needed or elapsed>=target-.28:break
        count=used_asset_counts.get(m['assetId'],0)
        if count>=3 and unique_assets>1:continue
        if segs and str(segs[-1]['assetId'])==str(m['assetId']) and unique_assets>1:
            if i+1<len(pool*4):continue
        remaining=target-elapsed;desired=rhythm_duration(pace,elapsed,target,strategy,intensity)
        source=by_id.get(str(m['assetId']),{'duration':m.get('sourceDuration',0)})
        fit=fit_segment(m,source,desired,remaining,strategy)
        if not fit:continue
        zoom_base=.008 if intensity=='soft' else .015 if intensity=='balanced' else .024
        impact=.012*max(0,min(1,float(m.get('motion',.4))))
        zoom=1.008+min(.075,zoom_base*((i+variant)%3)+impact);caption=''
        if not segs:caption='Ne quitte pas maintenant'
        elif strategy=='escalation' and len(segs) in (2,4):caption='Ça empire…'
        elif strategy=='contrast' and len(segs)==2:caption='Et là, tout change.'
        segs.append(_segment(m,fit,zoom,caption));used_asset_counts[m['assetId']]=count+1;elapsed+=float(fit['duration'])
    if strategy=='tease_payoff' and len(segs)>=3 and pool:
        best=max(pool,key=lambda x:x['quality']+.03*x.get('onsetBonus',0));best_key=(best['assetId'],round(best['start'],1))
        for idx,s in enumerate(segs[:-1]):
            if (s['assetId'],round(float(s['start']),1))==best_key:
                alt=next((m for m in pool if (m['assetId'],round(m['start'],1))!=best_key),None)
                if alt:
                    source=by_id.get(str(alt['assetId']),{'duration':alt.get('sourceDuration',0)})
                    fit=fit_segment(alt,source,float(s['duration']),float(s['duration']),strategy)
                    if fit:segs[idx]=_segment(alt,fit,float(s['zoom']),s.get('caption',''))
                break
        last_duration=float(segs[-1]['duration']);source=by_id.get(str(best['assetId']),{'duration':best.get('sourceDuration',0)})
        fit=fit_segment(best,source,last_duration,last_duration,'tease_payoff')
        if fit:segs[-1]=_segment(best,fit,float(segs[-1]['zoom']),'Voilà le moment')
    return {
        'hook':_hook(project,strategy,variant,hook_style),'strategy':strategy,'segments':segs,'pace':round(pace,2),
        'source':'director-v9.2-style','intensity':intensity,'hookStyle':hook_style,'qualityEngine':'shot-speech-beat-aware',
    }


def predict(plan,style,context,target):
    segs=plan.get('segments',[])
    if not segs:return 0.0,{}
    qualities=[float(s.get('momentScore',35))/100 for s in segs]
    first=statistics.mean(qualities[:min(2,len(qualities))]);avg=statistics.mean(qualities);payoff=max(qualities[-2:] if len(qualities)>1 else qualities)
    diversity=min(1.0,len({s['assetId'] for s in segs})/max(1,min(len(segs),4)))
    duration=sum(float(s['duration']) for s in segs);duration_fit=max(0,1-abs(duration-target)/max(target,1))
    style_pace=float(style.get('pace',2));pace_fit=max(0,1-abs(float(plan.get('pace',2))-style_pace)/max(style_pace,1))
    prior=max(0,min(1,strategy_prior(context,plan.get('strategy',''))));sequence=sequence_quality(segs)
    score=100*(.22*first+.19*avg+.15*payoff+.10*diversity+.09*duration_fit+.07*pace_fit+.06*prior+.12*sequence)
    score=max(0,min(100,score))
    breakdown={'first3s':round(first*100,1),'momentQuality':round(avg*100,1),'payoff':round(payoff*100,1),'diversity':round(diversity*100,1),'durationFit':round(duration_fit*100,1),'styleFit':round(pace_fit*100,1),'memoryPrior':round(prior*100,1),'sequenceQuality':round(sequence*100,1),'styleDiversity':round(float(plan.get('styleDiversity',0))*100,1)}
    return round(score,1),breakdown


def choose_plan(project,sources,style,profile,context,target,variant=0,revision=0,mode='auto',intensity='balanced',hook_style='auto',visual_style='auto'):
    learned=preferred_pace(context);effective=dict(style)
    if learned:effective['pace']=round(.7*float(style.get('pace',2))+.3*learned,2)
    allowed=MODE_STRATEGIES.get(mode,STRATEGIES)
    candidates=[]
    for strategy in allowed:
        plan=make_plan(project,sources,effective,profile,context,target,strategy,variant,revision,intensity,hook_style)
        plan=decorate_plan(plan,visual_style,mode,intensity,variant)
        plan=_bound_segment_speeds(plan,sources)
        score,why=predict(plan,effective,context,target);plan['predictedRetention']=score;plan['prediction']=why;plan['directorMode']=mode;candidates.append(plan)
    candidates.sort(key=lambda x:x['predictedRetention'],reverse=True)
    pick=min(max(0,int(variant)),len(candidates)-1);winner=candidates[pick]
    return winner,[{'strategy':x['strategy'],'score':x['predictedRetention'],'visualStyle':x.get('visualStyle')} for x in candidates]