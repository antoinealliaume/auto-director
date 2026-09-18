# -*- coding: utf-8 -*-
import gc, tempfile, uuid
from pathlib import Path
from psycopg.types.json import Jsonb
from .config import db, update_job, cancelled, save_asset_analysis, acquire_job_lock, release_job_lock, RENDER_WIDTH, RENDER_HEIGHT, MAX_REVISIONS, ENGINE_VERSION
from .analysis import analyze_asset, style_fingerprint, content_profile
from .memory import load_context
from .director import choose_plan
from .rendering import render_plan, critic

def _load_asset_file(work,row,index):
    aid,name,role,metadata=row
    with db() as c:data=c.execute('select data from assets where id=%s',(aid,)).fetchone()
    if not data:raise RuntimeError('Asset introuvable: '+str(aid))
    ext=Path(name).suffix or '.mp4';path=work/f'a{index}{ext}';path.write_bytes(bytes(data[0]));del data;gc.collect()
    return path

def _rows(project_id,ids):
    with db() as c:
        sources=c.execute("select id,name,role,metadata from assets where id=any(%s) and project_id=%s and kind='source' and role in ('source','broll','talking_head')",(ids,project_id)).fetchall()
        refs=c.execute("select id,name,role,metadata from assets where project_id=%s and kind='source' and role='reference' order by created_at desc limit 5",(project_id,)).fetchall()
    return sources,refs

def process_job(jid):
    if not acquire_job_lock(jid):return
    try:
        with db() as c:
            row=c.execute('select project_id,variants,settings,status from jobs where id=%s',(jid,)).fetchone()
            if not row:return
            project_id,variants,settings,status=row
            if status=='cancelled':return
            project=c.execute('select name from projects where id=%s',(project_id,)).fetchone()
        ids=[uuid.UUID(x) for x in settings.get('assetIds',[])]
        sources_rows,ref_rows=_rows(project_id,ids)
        if not sources_rows:raise RuntimeError('Aucun rush source exploitable')
        update_job(jid,'running','analysis',6,'V8 Moment Ranker: analyse des rushs')
        context=load_context(project_id)
        with tempfile.TemporaryDirectory(prefix='autodirector_v8_') as td:
            work=Path(td);paths={};sources=[];refs=[];all_rows=[('source',x) for x in sources_rows]+[('reference',x) for x in ref_rows]
            for index,(group,row) in enumerate(all_rows):
                if cancelled(jid):return
                aid,name,role,meta=row;path=_load_asset_file(work,row,index);paths[str(aid)]=path
                analysis,changed=analyze_asset(path,str(aid),name,role,meta)
                if changed:save_asset_analysis(str(aid),meta,analysis)
                (sources if group=='source' else refs).append(analysis)
                progress=7+int(12*(index+1)/max(1,len(all_rows)));update_job(jid,'running','analysis',progress,f'Analyse {index+1}/{len(all_rows)}: {name[:50]}')
            style=style_fingerprint(refs);profile=content_profile(sources);target=max(8,min(35,int(settings.get('targetDuration',18))))
            captions=bool(settings.get('captions',True));voice=settings.get('voiceover','auto');auto_revision=bool(settings.get('autoRevision',True))
            brief={'engine':ENGINE_VERSION,'project':project[0] if project else 'Auto Director','targetDuration':target,'sourceCount':len(sources),'referenceCount':len(refs),'styleFingerprint':style,'contentProfile':profile,'performanceMemory':context.get('winningStrategies',[])}
            update_job(jid,'running','director',20,'V8 Director: simulation de 5 strategies',brief=brief)
            output_ids=[];scores=[];total_revisions=0;last_strategy=''
            for variant in range(max(1,min(3,int(variants)))):
                if cancelled(jid):return
                plan,simulations=choose_plan(brief['project'],sources,style,profile,context,target,variant,0)
                last_strategy=plan['strategy'];brief_v={**brief,'selectedStrategy':plan['strategy'],'simulations':simulations,'predictedRetention':plan.get('predictedRetention')}
                update_job(jid,'running','director',23+variant*20,f"V8 Director V{variant+1}: {plan['strategy']} ({plan.get('predictedRetention',0)}/100)",strategy=last_strategy,brief=brief_v)
                initial=work/f'AutoDirector_V8_{variant+1}.mp4';render_plan(work,plan,paths,initial,captions,voice)
                score,diag=critic(initial,target,plan);final=initial;revision_count=0
                if auto_revision and score<82 and MAX_REVISIONS>0:
                    update_job(jid,'running','revision',min(88,42+variant*18),f'V8 Critic: revision automatique, score {score}/100')
                    plan2,_=choose_plan(brief['project'],sources,style,profile,context,target,variant,1)
                    revised=work/f'AutoDirector_V8_{variant+1}_R1.mp4';render_plan(work,plan2,paths,revised,captions,voice);score2,diag2=critic(revised,target,plan2)
                    if score2>=score:
                        final,plan,score,diag=revised,plan2,score2,diag2;revision_count=1;total_revisions+=1;last_strategy=plan['strategy']
                meta={'engineVersion':ENGINE_VERSION,'score':score,'duration':diag.get('duration'),'strategy':plan['strategy'],'hook':plan['hook'],'pace':plan.get('pace'),'predictedRetention':plan.get('predictedRetention'),'revisionCount':revision_count,'referenceCount':len(refs),'segmentCount':len(plan['segments']),'critic':diag,'styleFingerprint':style,'resolution':[RENDER_WIDTH,RENDER_HEIGHT]}
                blob=final.read_bytes();aid=uuid.uuid4()
                with db() as c:c.execute("insert into assets(id,project_id,name,content_type,size,role,kind,data,metadata) values(%s,%s,%s,'video/mp4',%s,'render','render',%s,%s)",(aid,project_id,final.name,len(blob),blob,Jsonb(meta)))
                del blob;gc.collect();output_ids.append(aid);scores.append(score)
                update_job(jid,'running','render',min(94,55+variant*16),f'Variante {variant+1} terminee: {score}/100',score=max(scores),revision=total_revisions,strategy=last_strategy)
            with db() as c:c.execute("update jobs set status='done',stage='complete',progress=100,message='V8 termine - galerie prete',output_asset_ids=%s,critic_score=%s,revision_count=%s,strategy=%s,updated_at=now() where id=%s",(output_ids,max(scores) if scores else 0,total_revisions,last_strategy,jid))
    except Exception as e:
        print('V8 JOB FAILED',jid,repr(e),flush=True)
        try:update_job(jid,'failed','error',0,str(e)[:500])
        except Exception:pass
    finally:release_job_lock(jid)
