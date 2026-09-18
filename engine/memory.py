# -*- coding: utf-8 -*-
import math, statistics
from .config import db

def load_context(project_id):
    with db() as c:
        rows=c.execute("""
        select a.name,a.metadata,coalesce(sum(f.views),0),coalesce(sum(f.likes),0),
               coalesce(sum(f.comments),0),coalesce(sum(f.shares),0),
               coalesce(avg(f.completion),0),coalesce(sum(f.conversions),0),coalesce(sum(f.revenue),0)
        from assets a left join feedback f on f.asset_id=a.id
        where a.project_id=%s and a.kind='render'
        group by a.id,a.name,a.metadata order by coalesce(sum(f.views),0) desc limit 30
        """,(project_id,)).fetchall()
        try:trends=c.execute("select label,coalesce(source_url,''),notes from trends order by created_at desc limit 10").fetchall()
        except Exception:trends=[]
    perf=[];strategy_values={}
    for name,meta,views,likes,comments,shares,completion,conversions,revenue in rows:
        views=int(views or 0);likes=float(likes or 0);comments=float(comments or 0);shares=float(shares or 0)
        completion=float(completion or 0);conversions=float(conversions or 0);revenue=float(revenue or 0)
        engagement=(likes+2*comments+4*shares)/max(views,1)
        value=min(2.0,math.log1p(views)/10.0)+4.0*engagement+2.5*completion+.2*conversions+.02*revenue
        strategy=(meta or {}).get('strategy','') if isinstance(meta,dict) else ''
        hook=(meta or {}).get('hook','') if isinstance(meta,dict) else ''
        pace=(meta or {}).get('pace') if isinstance(meta,dict) else None
        if strategy:strategy_values.setdefault(strategy,[]).append(value)
        perf.append({'name':name,'views':views,'completion':round(completion,3),'engagement':round(engagement,4),'strategy':strategy,'hook':str(hook)[:120],'pace':pace,'value':round(value,3)})
    winning=sorted(((k,statistics.mean(v)) for k,v in strategy_values.items()),key=lambda x:x[1],reverse=True)[:5]
    return {'performance':sorted(perf,key=lambda x:x['value'],reverse=True)[:10],'winningStrategies':[{'strategy':k,'score':round(v,3)} for k,v in winning],'trends':[{'label':x[0],'url':x[1],'notes':x[2]} for x in trends]}

def strategy_prior(context,strategy):
    winners=context.get('winningStrategies',[]) if isinstance(context,dict) else []
    if not winners:return 0.0
    best=max([float(x.get('score',0)) for x in winners] or [1])
    for row in winners:
        if row.get('strategy')==strategy:
            return min(1.0,float(row.get('score',0))/max(best,.01))
    return 0.0

def preferred_pace(context):
    rows=context.get('performance',[]) if isinstance(context,dict) else []
    weighted=[]
    for row in rows[:8]:
        pace=row.get('pace');value=float(row.get('value',0))
        if pace is not None:
            try:weighted.append((float(pace),max(.1,value)))
            except Exception:pass
    if not weighted:return None
    total=sum(w for _,w in weighted)
    return sum(p*w for p,w in weighted)/max(total,.01)
