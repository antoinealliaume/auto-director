# -*- coding: utf-8 -*-
import math
import statistics

from .memory import strategy_prior, preferred_pace

STRATEGIES=('tease_payoff','escalation','speedrun','contrast','clean_story')


def _moments(sources):
    out=[]
    for source_order,s in enumerate(sources):
        duration=max(0.0,float(s.get('duration',0) or 0))
        for rank,m in enumerate(s.get('moments',[])[:6]):
            out.append({
                'assetId':s['id'],'start':float(m.get('start',0)),'quality':float(m.get('score',35))/100.0,
                'motion':float(m.get('motion',.4)),'audio':float(m.get('audio',.3)),'rank':rank,
                'role':s.get('role','source'),'sourceOrder':source_order,'sourceDuration':duration,
            })
    if not out:
        for source_order,s in enumerate(sources):
            out.append({'assetId':s['id'],'start':0.0,'quality':.35,'motion':.3,'audio':.2,'rank':0,'role':s.get('role','source'),'sourceOrder':source_order,'sourceDuration':float(s.get('duration',0) or 0)})
    return out


def _duration(style,profile,strategy,revision=0):
    pace=float(style.get('pace',2.0))
    if strategy=='speedrun':pace*=.68
    elif strategy=='tease_payoff':pace*=.86
    elif strategy=='clean_story':pace*=1.22
    elif strategy=='contrast':pace*=.95
    if profile.get('tempo')=='chaotic':pace*=.86
    if revision:pace*=.82
    return max(.85,min(3.4,pace))


def _order(pool,strategy,variant):
    quality=sorted(pool,key=lambda x:(x['quality'],x['motion']+.35*x['audio']),reverse=True)
    if strategy=='escalation':ordered=sorted(pool,key=lambda x:x['quality'])
    elif strategy=='contrast':
        hi=quality[:];lo=sorted(pool,key=lambda x:x['quality']);ordered=[];seen=set()
        while hi or lo:
            for arr in (hi,lo):
                if not arr:continue
                x=arr.pop(0);key=(x['assetId'],round(x['start'],1))
                if key not in seen:ordered.append(x);seen.add(key)
    elif strategy=='clean_story':ordered=sorted(pool,key=lambda x:(x['sourceOrder'],x['start']))
    elif strategy=='speedrun':ordered=sorted(pool,key=lambda x:(x['motion']+.25*x['audio']+.35*x['quality']),reverse=True)
    else:
        top=quality[:max(3,len(quality)//2)];ordered=top[1:]+quality[len(top):]+quality[:1]
    if ordered and variant:ordered=ordered[variant%len(ordered):]+ordered[:variant%len(ordered)]
    return ordered


def _dedupe(seq):
    out=[];last_by_asset={};seen=set()
    for m in seq:
        a=m['assetId'];t=m['start'];key=(a,round(t,1))
        if key in seen:continue
        if a in last_by_asset and abs(t-last_by_asset[a])<.9:continue
        out.append(m);seen.add(key);last_by_asset[a]=t
    return out


def _hook(project,strategy,variant):
    name=(project or 'ce moment')[:45]
    options={
      'tease_payoff':[f'La fin sur {name} est impossible à prédire.','Attends les 3 dernières secondes.'],
      'escalation':['Ça devient de pire en pire à chaque seconde.','Je pensais que ça allait se calmer.'],
      'speedrun':['Regarde tout ce qui se passe en quelques secondes.','Tu vas rater un détail si tu clignes des yeux.'],
      'contrast':['Le début ne prépare absolument pas à la suite.','Deux ambiances totalement opposées en quelques secondes.'],
      'clean_story':['Voici exactement comment la situation a dégénéré.','Tout part d’un détail presque invisible.'],
    }
    arr=options.get(strategy,options['tease_payoff']);return arr[variant%len(arr)]


def _segment(m,duration,zoom,caption=''):
    return {
        'assetId':m['assetId'],'start':round(m['start'],2),'duration':round(duration,2),'zoom':round(zoom,3),
        'caption':caption,'momentScore':round(m['quality']*100,1),'audioScore':round(m['audio'],3),
        'sourceOrder':m['sourceOrder'],
    }


def make_plan(project,sources,style,profile,context,target,strategy,variant=0,revision=0):
    pool=_dedupe(_order(_moments(sources),strategy,variant));pace=_duration(style,profile,strategy,revision)
    target=max(8,min(35,int(target)));needed=max(3,min(16,math.ceil(target/pace)))
    segs=[];used_asset_counts={};elapsed=0.0
    for i,m in enumerate(pool*3):
        if len(segs)>=needed or elapsed>=target-.3:break
        count=used_asset_counts.get(m['assetId'],0)
        if count>=3 and len({x['assetId'] for x in pool})>1:continue
        remaining=target-elapsed
        available=(m['sourceDuration']-m['start']-.05) if m['sourceDuration']>0 else pace
        if available<.65:continue
        duration=min(pace,max(.65,remaining),available)
        if duration<.65:continue
        zoom=1.015+min(.065,.018*((i+variant)%4));caption=''
        if not segs:caption='Ne quitte pas maintenant'
        elif strategy=='escalation' and len(segs) in (2,4):caption='Ça empire…'
        segs.append(_segment(m,duration,zoom,caption));used_asset_counts[m['assetId']]=count+1;elapsed+=duration
    if strategy=='tease_payoff' and len(segs)>=3 and pool:
        best=max(pool,key=lambda x:x['quality']);best_key=(best['assetId'],round(best['start'],1))
        # Keep the strongest moment for the payoff instead of spoiling it earlier.
        for idx,s in enumerate(segs[:-1]):
            if (s['assetId'],round(float(s['start']),1))==best_key:
                alt=next((m for m in pool if (m['assetId'],round(m['start'],1))!=best_key and m['sourceDuration']-m['start']>.7),None)
                if alt:
                    segs[idx]=_segment(alt,min(float(s['duration']),max(.7,alt['sourceDuration']-alt['start']-.05)),float(s['zoom']),s.get('caption',''))
                break
        last_duration=float(segs[-1]['duration']);available=(best['sourceDuration']-best['start']-.05) if best['sourceDuration']>0 else last_duration
        segs[-1]=_segment(best,min(last_duration,max(.65,available)),float(segs[-1]['zoom']),'Voilà le moment')
    return {'hook':_hook(project,strategy,variant),'strategy':strategy,'segments':segs,'pace':round(pace,2),'source':'director-v8'}


def predict(plan,style,context,target):
    segs=plan.get('segments',[])
    if not segs:return 0.0,{}
    qualities=[float(s.get('momentScore',35))/100 for s in segs]
    first=statistics.mean(qualities[:min(2,len(qualities))]);avg=statistics.mean(qualities);payoff=max(qualities[-2:] if len(qualities)>1 else qualities)
    diversity=min(1.0,len({s['assetId'] for s in segs})/max(1,min(len(segs),4)))
    duration=sum(float(s['duration']) for s in segs);duration_fit=max(0,1-abs(duration-target)/max(target,1))
    style_pace=float(style.get('pace',2));pace_fit=max(0,1-abs(float(plan.get('pace',2))-style_pace)/max(style_pace,1))
    prior=max(0,min(1,strategy_prior(context,plan.get('strategy',''))))
    score=100*(.24*first+.22*avg+.16*payoff+.12*diversity+.10*duration_fit+.08*pace_fit+.08*prior)
    score=max(0,min(100,score))
    breakdown={'first3s':round(first*100,1),'momentQuality':round(avg*100,1),'payoff':round(payoff*100,1),'diversity':round(diversity*100,1),'durationFit':round(duration_fit*100,1),'styleFit':round(pace_fit*100,1),'memoryPrior':round(prior*100,1)}
    return round(score,1),breakdown


def choose_plan(project,sources,style,profile,context,target,variant=0,revision=0):
    learned=preferred_pace(context);effective=dict(style)
    if learned:effective['pace']=round(.7*float(style.get('pace',2))+.3*learned,2)
    candidates=[]
    for strategy in STRATEGIES:
        plan=make_plan(project,sources,effective,profile,context,target,strategy,variant,revision)
        score,why=predict(plan,effective,context,target);plan['predictedRetention']=score;plan['prediction']=why;candidates.append(plan)
    candidates.sort(key=lambda x:x['predictedRetention'],reverse=True)
    pick=min(max(0,int(variant)),len(candidates)-1);winner=candidates[pick]
    return winner,[{'strategy':x['strategy'],'score':x['predictedRetention']} for x in candidates]
