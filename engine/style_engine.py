# -*- coding: utf-8 -*-
"""V9.2 deterministic visual style planning.

This module deliberately stays renderer-agnostic. It enriches Director plans
with a bounded set of visual decisions that the FFmpeg renderer may apply or
safely ignore when a filter is unavailable.
"""
from copy import deepcopy

STYLE_NAMES=('auto','viral','cinematic','kinetic','clean','retro','glitch','meme','dreamy')

PRESETS={
    'viral':{
        'hook':'impact','caption':'punch','grade':'punch','flash':True,
        'transitions':('slideleft','dissolve','wipeleft','fade'),
        'motions':('push','drift','shake','push'),
        'speeds':(1.08,1.00,1.14,.96),
        'accents':('FFE45E','75FBFD','FF6B9D'),
        'transitionDuration':.08,
    },
    'cinematic':{
        'hook':'cinema','caption':'minimal','grade':'cinematic','flash':False,
        'transitions':('dissolve','fade','circleopen','dissolve'),
        'motions':('drift','push','drift','static'),
        'speeds':(.96,1.00,.92,1.04),
        'accents':('F4D8A8','DCE8FF','FFFFFF'),
        'transitionDuration':.16,
    },
    'kinetic':{
        'hook':'impact','caption':'kinetic','grade':'punch','flash':True,
        'transitions':('wipeleft','slideright','slideleft','dissolve'),
        'motions':('shake','push','drift','shake'),
        'speeds':(1.12,.96,1.16,1.02),
        'accents':('8BFF6A','FFE45E','75FBFD'),
        'transitionDuration':.07,
    },
    'clean':{
        'hook':'clean','caption':'subtitle','grade':'clean','flash':False,
        'transitions':('fade','dissolve','fade','dissolve'),
        'motions':('static','drift','static','push'),
        'speeds':(1.00,1.00,1.02,.98),
        'accents':('FFFFFF','DDE7FF','C7F7E8'),
        'transitionDuration':.06,
    },
    'retro':{
        'hook':'retro','caption':'highlight','grade':'retro','flash':False,
        'transitions':('wipeleft','dissolve','wiperight','fade'),
        'motions':('drift','push','static','drift'),
        'speeds':(1.04,.96,1.08,1.00),
        'accents':('FFB56B','F779C5','7DE2D1'),
        'transitionDuration':.10,
    },
    'glitch':{
        'hook':'neon','caption':'neon','grade':'glitch','flash':True,
        'transitions':('dissolve','wipeleft','slideleft','wiperight'),
        'motions':('shake','push','shake','drift'),
        'speeds':(1.15,.94,1.18,1.04),
        'accents':('00F5FF','FF3DF2','D8FF38'),
        'transitionDuration':.065,
    },
    'meme':{
        'hook':'meme','caption':'meme','grade':'meme','flash':True,
        'transitions':('fade','slideleft','dissolve','wipeleft'),
        'motions':('push','shake','static','push'),
        'speeds':(1.10,1.00,1.16,.98),
        'accents':('FFFFFF','FFE45E','FF8A8A'),
        'transitionDuration':.055,
    },
    'dreamy':{
        'hook':'soft','caption':'minimal','grade':'dreamy','flash':False,
        'transitions':('dissolve','fade','circleopen','dissolve'),
        'motions':('drift','drift','push','static'),
        'speeds':(.94,.98,1.00,.92),
        'accents':('FFD7F4','C9DBFF','E5D5FF'),
        'transitionDuration':.18,
    },
}

STRATEGY_POOLS={
    'tease_payoff':('viral','cinematic','kinetic','dreamy'),
    'escalation':('kinetic','viral','glitch','cinematic'),
    'speedrun':('viral','kinetic','glitch','meme'),
    'contrast':('meme','retro','viral','glitch'),
    'clean_story':('clean','cinematic','dreamy','retro'),
}
MODE_PREFERENCES={
    'story':('cinematic','clean','dreamy'),
    'funny':('meme','kinetic','viral'),
    'highlight':('viral','kinetic','glitch'),
    'fast':('kinetic','viral','glitch'),
    'clean':('clean','cinematic','dreamy'),
}


def normalize_style(value):
    value=str(value or 'auto').strip().lower()
    return value if value in STYLE_NAMES else 'auto'


def choose_style(requested='auto',strategy='tease_payoff',mode='auto',variant=0,intensity='balanced'):
    requested=normalize_style(requested)
    if requested!='auto':return requested
    pool=list(STRATEGY_POOLS.get(strategy,STRATEGY_POOLS['tease_payoff']))
    preferred=MODE_PREFERENCES.get(str(mode or 'auto'))
    if preferred:
        ranked=[x for x in preferred if x in pool]+[x for x in pool if x not in preferred]
        pool=ranked or pool
    if intensity=='soft':
        gentle=[x for x in pool if x in {'clean','cinematic','dreamy','retro'}]
        if gentle:pool=gentle+[x for x in pool if x not in gentle]
    elif intensity=='aggressive':
        energetic=[x for x in pool if x in {'viral','kinetic','glitch','meme'}]
        if energetic:pool=energetic+[x for x in pool if x not in energetic]
    return pool[int(variant)%len(pool)]


def _bounded_speed(value,intensity):
    value=float(value)
    if intensity=='soft':return max(.94,min(1.06,value))
    if intensity=='aggressive':return max(.90,min(1.20,value))
    return max(.92,min(1.16,value))


def _motion_zoom(base,motion,intensity):
    z=float(base or 1.02)
    bonus={'static':0.0,'drift':.008,'push':.022,'shake':.032}.get(motion,0.0)
    if intensity=='soft':bonus*=.55
    elif intensity=='aggressive':bonus*=1.25
    return round(max(1.005,min(1.12,z+bonus)),3)


def decorate_plan(plan,requested='auto',mode='auto',intensity='balanced',variant=0):
    """Return a copied plan enriched with bounded V9.2 style decisions."""
    out=deepcopy(plan)
    strategy=str(out.get('strategy') or 'tease_payoff')
    name=choose_style(requested,strategy,mode,variant,intensity)
    preset=PRESETS[name]
    segs=[]
    for i,raw in enumerate(out.get('segments') or []):
        seg=dict(raw)
        motion=preset['motions'][i%len(preset['motions'])]
        speed=_bounded_speed(preset['speeds'][i%len(preset['speeds'])],intensity)
        transition=preset['transitions'][i%len(preset['transitions'])]
        accent=preset['accents'][i%len(preset['accents'])]
        seg.update({
            'visualStyle':name,
            'captionStyle':preset['caption'],
            'hookVisualStyle':preset['hook'],
            'colorGrade':preset['grade'],
            'motionEffect':motion,
            'speed':round(speed,3),
            'transition':transition,
            'transitionDuration':float(preset['transitionDuration']),
            'accentColor':accent,
            'flash':bool(preset['flash'] and i>0 and intensity!='soft'),
            'zoom':_motion_zoom(seg.get('zoom',1.02),motion,intensity),
        })
        segs.append(seg)
    out['segments']=segs
    out['visualStyle']=name
    out['styleEngine']='v9.2'
    out['stylePreset']={
        'hook':preset['hook'],'caption':preset['caption'],'grade':preset['grade'],
        'transitionDuration':preset['transitionDuration'],'flash':preset['flash'],
    }
    if segs:
        unique=len({(s['captionStyle'],s['motionEffect'],s['transition'],s['accentColor']) for s in segs})
        out['styleDiversity']=round(unique/len(segs),3)
    else:out['styleDiversity']=0.0
    return out
