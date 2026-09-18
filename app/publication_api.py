# -*- coding: utf-8 -*-
import uuid
from datetime import datetime, timezone
from typing import Optional

import psycopg
from fastapi import Header, HTTPException
from pydantic import BaseModel, Field
from psycopg.types.json import Jsonb

from .tiktok_oauth import connection_status

DATABASE_URL=__import__('os').environ.get('DATABASE_URL','')


def db(): return psycopg.connect(DATABASE_URL)
def require_studio(auth):
    token=auth[7:] if auth and auth.startswith('Bearer ') else ''
    from .main import verify_token
    if not token or not verify_token(token):raise HTTPException(401,'Session invalide')


def ensure_schema():
    with db() as c:
        c.execute('''create table if not exists publications(
            id uuid primary key,
            asset_id uuid not null references assets(id) on delete cascade,
            platform text not null default 'tiktok',
            status text not null default 'draft',
            caption text not null default '',
            hashtags jsonb not null default '[]'::jsonb,
            cta text not null default '',
            scheduled_at timestamptz,
            published_at timestamptz,
            external_id text not null default '',
            error text not null default '',
            created_at timestamptz not null default now(),
            updated_at timestamptz not null default now()
        )''')
        c.execute('create index if not exists idx_publications_status_schedule on publications(status,scheduled_at)')
        c.execute('create index if not exists idx_publications_asset on publications(asset_id)')


def _pack(aid):
    with db() as c:
        row=c.execute("select a.name,p.name,j.strategy,j.critic_score from assets a left join projects p on p.id=a.project_id left join jobs j on a.id=any(j.output_asset_ids) where a.id=%s and a.kind='render' order by j.updated_at desc nulls last limit 1",(aid,)).fetchone()
    if not row:raise HTTPException(404,'Rendu introuvable')
    filename,project,strategy,score=row;project=project or 'ce projet';strategy=strategy or 'dynamic_scene_reveal'
    caption=f'Ce moment sur {project}… 👀 Tu aurais fait quoi ?'
    tags=['#gaming','#tiktokgaming','#fyp','#viral']
    low=project.lower()
    if 'gmod' in low or 'garry' in low:tags=['#gmod','#garrysmod','#darkrp','#gaming']
    return {'assetId':str(aid),'filename':filename,'caption':caption,'hashtags':tags,'cta':'Dis-moi ce que tu aurais fait 👇','strategy':strategy,'score':score}


def _serialize(row):
    return {
        'id':str(row[0]),'assetId':str(row[1]),'assetName':row[2],'projectName':row[3],
        'platform':row[4],'status':row[5],'caption':row[6],'hashtags':row[7] or [],'cta':row[8],
        'scheduledAt':row[9].isoformat() if row[9] else None,'publishedAt':row[10].isoformat() if row[10] else None,
        'externalId':row[11],'error':row[12],'createdAt':row[13].isoformat(),'updatedAt':row[14].isoformat(),
    }

class PrepareIn(BaseModel):
    caption:Optional[str]=Field(default=None,max_length=2200)
    hashtags:Optional[list[str]]=None
    cta:Optional[str]=Field(default=None,max_length=300)

class UpdateIn(BaseModel):
    caption:Optional[str]=Field(default=None,max_length=2200)
    hashtags:Optional[list[str]]=None
    cta:Optional[str]=Field(default=None,max_length=300)

class ScheduleIn(BaseModel):
    scheduledAt:datetime


def _clean_tags(tags):
    out=[]
    for tag in tags or []:
        t=''.join(str(tag).strip().split())[:80]
        if not t:continue
        if not t.startswith('#'):t='#'+t
        if t not in out:out.append(t)
        if len(out)>=12:break
    return out


def attach(app):
    async def capabilities(authorization:Optional[str]=Header(None)):
        require_studio(authorization);s=connection_status()
        return {'platform':'tiktok','officialOAuthConfigured':s.get('configured',False),'oauthConnected':s.get('connected',False),'autoPublishReady':s.get('directPostReady',False),'uploadReady':s.get('uploadReady',False),'scopes':s.get('scopes',[]),'mode':'official-api-only','note':'OAuth TikTok officiel et scope video.publish requis pour Direct Post.'}

    async def list_publications(authorization:Optional[str]=Header(None)):
        require_studio(authorization);ensure_schema()
        with db() as c:
            rows=c.execute('''select q.id,q.asset_id,a.name,p.name,q.platform,q.status,q.caption,q.hashtags,q.cta,q.scheduled_at,q.published_at,q.external_id,q.error,q.created_at,q.updated_at
                from publications q join assets a on a.id=q.asset_id left join projects p on p.id=a.project_id
                order by q.created_at desc limit 100''').fetchall()
        return {'items':[_serialize(r) for r in rows]}

    async def prepare(asset_id:str,x:PrepareIn,authorization:Optional[str]=Header(None)):
        require_studio(authorization);ensure_schema()
        try:aid=uuid.UUID(asset_id)
        except Exception:raise HTTPException(400,'Rendu invalide')
        pack=_pack(aid);caption=x.caption.strip() if x.caption is not None else pack['caption'];tags=_clean_tags(x.hashtags if x.hashtags is not None else pack['hashtags']);cta=x.cta.strip() if x.cta is not None else pack['cta'];qid=uuid.uuid4()
        with db() as c:
            c.execute("insert into publications(id,asset_id,platform,status,caption,hashtags,cta) values(%s,%s,'tiktok','ready',%s,%s,%s)",(qid,aid,caption,Jsonb(tags),cta))
        return {'id':str(qid),'status':'ready','pack':{**pack,'caption':caption,'hashtags':tags,'cta':cta}}

    async def update(publication_id:str,x:UpdateIn,authorization:Optional[str]=Header(None)):
        require_studio(authorization);ensure_schema()
        try:qid=uuid.UUID(publication_id)
        except Exception:raise HTTPException(400,'Publication invalide')
        sets=[];vals=[]
        if x.caption is not None:sets.append('caption=%s');vals.append(x.caption.strip())
        if x.hashtags is not None:sets.append('hashtags=%s');vals.append(Jsonb(_clean_tags(x.hashtags)))
        if x.cta is not None:sets.append('cta=%s');vals.append(x.cta.strip())
        if not sets:return {'ok':True}
        sets.append('updated_at=now()');vals.append(qid)
        with db() as c:row=c.execute('update publications set '+','.join(sets)+' where id=%s returning id',vals).fetchone()
        if not row:raise HTTPException(404,'Publication introuvable')
        return {'ok':True}

    async def schedule(publication_id:str,x:ScheduleIn,authorization:Optional[str]=Header(None)):
        require_studio(authorization);ensure_schema()
        try:qid=uuid.UUID(publication_id)
        except Exception:raise HTTPException(400,'Publication invalide')
        when=x.scheduledAt
        if when.tzinfo is None:when=when.replace(tzinfo=timezone.utc)
        if when <= datetime.now(timezone.utc):raise HTTPException(400,'Choisis une date future')
        with db() as c:row=c.execute("update publications set status='scheduled',scheduled_at=%s,error='',updated_at=now() where id=%s and status in ('ready','scheduled','failed') returning id",(when,qid)).fetchone()
        if not row:raise HTTPException(409,'Cette publication ne peut pas être planifiée')
        return {'ok':True,'status':'scheduled','scheduledAt':when.isoformat()}

    async def publish(publication_id:str,authorization:Optional[str]=Header(None)):
        require_studio(authorization);ensure_schema()
        try:qid=uuid.UUID(publication_id)
        except Exception:raise HTTPException(400,'Publication invalide')
        with db() as c:row=c.execute('select status from publications where id=%s',(qid,)).fetchone()
        if not row:raise HTTPException(404,'Publication introuvable')
        s=connection_status()
        if not s.get('configured'):raise HTTPException(409,'Application TikTok Developer non configurée. Le contenu reste prêt dans la file.')
        if not s.get('connected'):raise HTTPException(409,'Connecte ton compte TikTok via OAuth officiel avant publication.')
        if not s.get('directPostReady'):raise HTTPException(409,'Le compte est connecté, mais le scope TikTok video.publish n’est pas autorisé.')
        # Direct Post additionally requires creator-info driven privacy/interaction choices
        # and explicit user consent. The API intentionally stays locked until that UI is active.
        raise HTTPException(409,'TikTok est connecté. Il reste à valider les paramètres Direct Post avant l’envoi automatique.')

    app.add_api_route('/api/publications/capabilities',capabilities,methods=['GET'],include_in_schema=False)
    app.add_api_route('/api/publications',list_publications,methods=['GET'],include_in_schema=False)
    app.add_api_route('/api/publications/prepare/{asset_id}',prepare,methods=['POST'],include_in_schema=False)
    app.add_api_route('/api/publications/{publication_id}',update,methods=['PATCH'],include_in_schema=False)
    app.add_api_route('/api/publications/{publication_id}/schedule',schedule,methods=['POST'],include_in_schema=False)
    app.add_api_route('/api/publications/{publication_id}/publish',publish,methods=['POST'],include_in_schema=False)
