# -*- coding: utf-8 -*-
import gc
import tempfile
import uuid
from pathlib import Path

from psycopg.types.json import Jsonb

import storage_backend as media_store
from storage_schema import ensure_storage_schema
from .config import db, queue, QUEUE_KEY, update_job, cancelled, save_asset_analysis, acquire_job_lock, release_job_lock, RENDER_WIDTH, RENDER_HEIGHT, MAX_REVISIONS, ENGINE_VERSION
from .analysis import analyze_asset, style_fingerprint, content_profile
from .memory import load_context
from .director import choose_plan
from .rendering import render_plan, critic
from .local_ai import enabled as local_ai_enabled, refine_plan, critic_video


class JobCancelled(Exception):pass


def _load_asset_file(work,row,index):
    aid,name,role,metadata=row
    with db() as c:
        ensure_storage_schema(c);data=c.execute('select data,storage_key from assets where id=%s',(aid,)).fetchone()
    if not data:raise RuntimeError('Asset introuvable: '+str(aid))
    ext=Path(name).suffix or '.mp4';path=work/f'a{index}{ext}'
    media_store.materialize_asset(data[1],data[0],path);del data;gc.collect();return path


def _rows(project_id,ids):
    with db() as c:
        sources=c.execute("select id,name,role,metadata from assets where id=any(%s) and project_id=%s and kind='source' and role in ('source','broll','talking_head')",(ids,project_id)).fetchall()
        refs=c.execute("select id,name,role,metadata from assets where project_id=%s and kind='source' and role='reference' order by created_at desc limit 5",(project_id,)).fetchall()
    return sources,refs


def _cleanup_outputs(output_ids):
    if not output_ids:return
    with db() as c:rows=c.execute('select id,storage_key from assets where id=any(%s)',(output_ids,)).fetchall()
    for _,key in rows:
        if key:
            try:media_store.delete(key)
            except Exception:pass
    with db() as c:c.execute('delete from assets where id=any(%s)',(output_ids,))


def _requeue_if_still_queued(jid):
    if queue is None:return
    try:
        with db() as c:row=c.execute('select status from jobs where id=%s',(jid,)).fetchone()
        if row and row[0]=='queued' and queue.lpos(QUEUE_KEY,str(jid)) is None:queue.lpush(QUEUE_KEY,str(jid))
    except Exception:pass


def _check_cancel(jid):
    if cancelled(jid):raise JobCancelled()


def process_job(jid):
    if not acquire_job_lock(jid):
        _requeue_if_still_queued(jid);return
    output_ids=[]
    try:
        with db() as c:
            row=c.execute('select project_id,variants,settings,status from jobs where id=%s',(jid,)).fetchone()
            if not row:return
            project_id,variants,settings,status=row
            if status=='cancelled':return
            project=c.execute('select name from projects where id=%s',(project_id,)).fetchone()
        settings=settings or {}
        ids=[uuid.UUID(x) for x in settings.get('assetIds',[])]
        sources_rows,ref_rows=_rows(project_id,ids)
        if not sources_rows:raise RuntimeError('Aucun rush source exploitable')
        update_job(jid,'running','analysis',6,'V9.2 Moment Ranker · analyse des rushs')
        context=load_context(project_id)
        with tempfile.TemporaryDirectory(prefix='autodirector_v92_') as td:
            work=Path(td);paths={};sources=[];refs=[];all_rows=[('source',x) for x in sources_rows]+[('reference',x) for x in ref_rows]
            for index,(group,row) in enumerate(all_rows):
                _check_cancel(jid)
                aid,name,role,meta=row;path=_load_asset_file(work,row,index);paths[str(aid)]=path
                analysis,changed=analyze_asset(path,str(aid),name,role,meta)
                if changed:save_asset_analysis(str(aid),meta,analysis)
                (sources if group=='source' else refs).append(analysis)
                progress=7+int(12*(index+1)/max(1,len(all_rows)));update_job(jid,'running','analysis',progress,f'Analyse {index+1}/{len(all_rows)} · {name[:50]}')
            style=style_fingerprint(refs);profile=content_profile(sources);target=max(8,min(35,int(settings.get('targetDuration',18))))
            captions=bool(settings.get('captions',True));voice=settings.get('voiceover','auto');auto_revision=bool(settings.get('autoRevision',True))
            mode=str(settings.get('directorMode','auto'));intensity=str(settings.get('editIntensity','balanced'));hook_style=str(settings.get('hookStyle','auto'));visual_style=str(settings.get('visualStyle','auto'))
            brief={'engine':ENGINE_VERSION,'project':project[0] if project else 'Auto Director','targetDuration':target,'sourceCount':len(sources),'referenceCount':len(refs),'styleFingerprint':style,'contentProfile':profile,'performanceMemory':context.get('winningStrategies',[]),'localAI':local_ai_enabled(),'storage':media_store.backend_name(),'directorMode':mode,'editIntensity':intensity,'hookStyle':hook_style,'visualStyle':visual_style}
            update_job(jid,'running','director',20,f'V9.2 Director · mode {mode} · style {visual_style}',brief=brief)
            scores=[];total_revisions=0;last_strategy=''
            for variant in range(max(1,min(3,int(variants)))):
                _check_cancel(jid)
                plan,simulations=choose_plan(brief['project'],sources,style,profile,context,target,variant,0,mode,intensity,hook_style,visual_style)
                plan,local_plan_diag=refine_plan(brief['project'],plan,sources,paths,work)
                last_strategy=plan['strategy'];brief_v={**brief,'selectedStrategy':plan['strategy'],'selectedVisualStyle':plan.get('visualStyle'),'styleDiversity':plan.get('styleDiversity'),'simulations':simulations,'predictedRetention':plan.get('predictedRetention'),'localAIDirector':local_plan_diag}
                director_label='VLM local + V9.2' if local_ai_enabled() else 'Director V9.2'
                update_job(jid,'running','director',23+variant*20,f"{director_label} · V{variant+1} · {plan['strategy']} · {plan.get('visualStyle','auto')} · {plan.get('predictedRetention',0)}/100",strategy=last_strategy,brief=brief_v)
                initial=work/f'AutoDirector_V92_{variant+1}.mp4';render_plan(work,plan,paths,initial,captions,voice)
                _check_cancel(jid)
                score,diag=critic(initial,target,plan);score,vlm_diag=critic_video(initial,score,plan,work);diag={**diag,'localVLM':vlm_diag}
                final=initial;revision_count=0
                if auto_revision and score<82 and MAX_REVISIONS>0:
                    update_job(jid,'running','revision',min(88,42+variant*18),f'V9.2 Critic · révision automatique · score {score}/100')
                    plan2,_=choose_plan(brief['project'],sources,style,profile,context,target,variant,1,mode,intensity,hook_style,visual_style)
                    plan2,local_plan_diag2=refine_plan(brief['project'],plan2,sources,paths,work)
                    revised=work/f'AutoDirector_V92_{variant+1}_R1.mp4';render_plan(work,plan2,paths,revised,captions,voice)
                    _check_cancel(jid)
                    score2,diag2=critic(revised,target,plan2);score2,vlm_diag2=critic_video(revised,score2,plan2,work);diag2={**diag2,'localVLM':vlm_diag2,'localAIDirector':local_plan_diag2}
                    if score2>=score:final,plan,score,diag=revised,plan2,score2,diag2;revision_count=1;total_revisions+=1;last_strategy=plan['strategy']
                aid=uuid.uuid4();storage_key=None
                meta={'engineVersion':ENGINE_VERSION,'score':score,'duration':diag.get('duration'),'strategy':plan['strategy'],'hook':plan['hook'],'pace':plan.get('pace'),'predictedRetention':plan.get('predictedRetention'),'revisionCount':revision_count,'referenceCount':len(refs),'segmentCount':len(plan['segments']),'critic':diag,'styleFingerprint':style,'resolution':[RENDER_WIDTH,RENDER_HEIGHT],'localAI':local_ai_enabled(),'directorMode':mode,'editIntensity':intensity,'hookStyle':hook_style,'visualStyle':plan.get('visualStyle',visual_style),'styleEngine':plan.get('styleEngine'),'styleDiversity':plan.get('styleDiversity')}
                data,storage_key,backend,checksum=media_store.persist_file(project_id,aid,'render',final.name,final,'video/mp4');meta={**meta,'storageBackend':backend,'checksumSha256':checksum}
                try:
                    with db() as c:
                        ensure_storage_schema(c);c.execute("insert into assets(id,project_id,name,content_type,size,role,kind,data,metadata,storage_key,storage_backend,checksum_sha256) values(%s,%s,%s,'video/mp4',%s,'render','render',%s,%s,%s,%s,%s)",(aid,project_id,final.name,final.stat().st_size,data,Jsonb(meta),storage_key,backend,checksum))
                except Exception:
                    if storage_key:
                        try:media_store.delete(storage_key)
                        except Exception:pass
                    raise
                if data is not None:del data
                gc.collect();output_ids.append(aid);scores.append(score)
                update_job(jid,'running','render',min(94,55+variant*16),f"Variante {variant+1} · {plan.get('visualStyle','auto')} · {score}/100",score=max(scores),revision=total_revisions,strategy=last_strategy)
            with db() as c:c.execute("update jobs set status='done',stage='complete',progress=100,message='V9.2 terminé · galerie prête',output_asset_ids=%s,critic_score=%s,revision_count=%s,strategy=%s,updated_at=now() where id=%s",(output_ids,max(scores) if scores else 0,total_revisions,last_strategy,jid))
    except JobCancelled:
        _cleanup_outputs(output_ids);print('V9.2 JOB CANCELLED',jid,flush=True)
    except Exception as e:
        _cleanup_outputs(output_ids);print('V9.2 JOB FAILED',jid,repr(e),flush=True)
        try:update_job(jid,'failed','error',0,str(e)[:500])
        except Exception:pass
    finally:release_job_lock(jid)
