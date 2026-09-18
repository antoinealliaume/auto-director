# -*- coding: utf-8 -*-
"""Official TikTok Content Posting / Direct Post integration.

Server-side renders are transferred with PULL_FROM_URL, guarded by a short-lived
asset-specific signature. Direct Post is hard-gated on verified URL-prefix config,
video.publish scope, creator-info validation and explicit user consent.
"""
import hashlib
import hmac
import os
import secrets
import time
import uuid
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import quote

import httpx
import psycopg
from fastapi import Header, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

import storage_backend as media_store
from storage_schema import ensure_storage_schema
from .tiktok_oauth import connection_status, get_access_token

DATABASE_URL=os.environ.get('DATABASE_URL','')
BASE_URL=os.environ.get('TIKTOK_PUBLIC_BASE_URL','https://auto-director-web.onrender.com').rstrip('/')
PULL_VERIFIED=os.environ.get('TIKTOK_PULL_URL_VERIFIED','0')=='1'
PULL_TTL=max(900,min(3600,int(os.environ.get('TIKTOK_PULL_URL_TTL','3600'))))


def db():return psycopg.connect(DATABASE_URL)
def require_studio(auth):
    token=auth[7:] if auth and auth.startswith('Bearer ') else ''
    from .main import verify_token
    if not token or not verify_token(token):raise HTTPException(401,'Session invalide')
def _signing_secret():
    value=os.environ.get('TIKTOK_TOKEN_ENCRYPTION_KEY','').strip()
    if not value:raise RuntimeError('TikTok signing key missing')
    return value.encode()
def _sig(raw):return hmac.new(_signing_secret(),raw.encode(),hashlib.sha256).hexdigest()
def make_pull_token(asset_id):
    raw=f'{int(time.time())+PULL_TTL}.{asset_id}.{secrets.token_urlsafe(18)}'
    return raw+'.'+_sig(raw)
def verify_pull_token(token,asset_id):
    raw,sep,sig=(token or '').rpartition('.')
    if not sep or not hmac.compare_digest(_sig(raw),sig):return False
    p=raw.split('.')
    if len(p)!=3 or p[1]!=str(asset_id):return False
    try:return int(p[0])>=int(time.time())
    except Exception:return False
def pull_url(asset_id):return f'{BASE_URL}/api/tiktok/pull/{asset_id}?token={quote(make_pull_token(asset_id),safe="")}'

def _api_error(payload):
    err=(payload or {}).get('error') or {}
    code=str(err.get('code') or 'ok')
    if code!='ok':raise HTTPException(502,'TikTok API: '+str(err.get('message') or code)[:300])

def _truncate_utf16(text,limit=2200):
    out=[];units=0
    for ch in str(text or ''):
        need=2 if ord(ch)>0xFFFF else 1
        if units+need>limit:break
        out.append(ch);units+=need
    return ''.join(out).strip()

def _title(caption,tags,cta):
    parts=[str(caption or '').strip(),' '.join(str(x).strip() for x in (tags or []) if str(x).strip()),str(cta or '').strip()]
    return _truncate_utf16('\n'.join(x for x in parts if x),2200)

async def creator_info_call():
    status=connection_status()
    if not status.get('directPostReady'):raise HTTPException(409,'TikTok video.publish non autorisé.')
    try:access=get_access_token()
    except Exception as exc:raise HTTPException(409,str(exc)[:300])
    async with httpx.AsyncClient(timeout=30) as c:
        r=await c.post('https://open.tiktokapis.com/v2/post/publish/creator_info/query/',headers={'Authorization':'Bearer '+access,'Content-Type':'application/json; charset=UTF-8'},json={})
    if r.status_code>=400:raise HTTPException(502,'TikTok creator_info indisponible')
    payload=r.json();_api_error(payload);data=payload.get('data') or {}
    return {
        'username':data.get('creator_username') or '',
        'nickname':data.get('creator_nickname') or '',
        'avatarUrl':data.get('creator_avatar_url') or '',
        'privacyLevels':data.get('privacy_level_options') or [],
        'commentDisabled':bool(data.get('comment_disabled')),
        'duetDisabled':bool(data.get('duet_disabled')),
        'stitchDisabled':bool(data.get('stitch_disabled')),
        'maxDurationSec':int(data.get('max_video_post_duration_sec') or 0),
    }

class DirectPostIn(BaseModel):
    privacyLevel:str
    allowComment:bool=True
    allowDuet:bool=True
    allowStitch:bool=True
    isAigc:bool=False
    consent:bool=False


def _publication(publication_id):
    ensure_storage_schema()
    with db() as c:
        row=c.execute('''select q.id,q.asset_id,q.caption,q.hashtags,q.cta,q.status,a.name,a.content_type,a.data,a.size,a.storage_key,a.metadata
            from publications q join assets a on a.id=q.asset_id where q.id=%s and a.kind='render' ''',(publication_id,)).fetchone()
    if not row:raise HTTPException(404,'Publication ou rendu introuvable')
    return row

def ensure_storage_schema():
    with db() as c:
        from storage_schema import ensure_storage_schema as _ensure
        _ensure(c)

def _stream_asset(storage_key,data,total,chunk=1024*1024):
    if storage_key:
        start=0
        while start<total:
            end=min(total-1,start+chunk-1);yield media_store.get_range(storage_key,start,end);start=end+1
    else:
        blob=memoryview(bytes(data or b''))
        for start in range(0,len(blob),chunk):yield bytes(blob[start:start+chunk])


def attach(app):
    async def readiness(authorization:Optional[str]=Header(None)):
        require_studio(authorization);s=connection_status()
        return {**s,'pullUrlVerified':PULL_VERIFIED,'pullUrlPrefix':BASE_URL+'/api/tiktok/pull/','directPostOperational':bool(s.get('directPostReady') and PULL_VERIFIED)}

    async def creator_info(authorization:Optional[str]=Header(None)):
        require_studio(authorization);return await creator_info_call()

    async def pull_media(asset_id:str,request:Request,token:str=Query(...)):
        try:aid=uuid.UUID(asset_id)
        except Exception:raise HTTPException(404,'Media introuvable')
        if not verify_pull_token(token,aid):raise HTTPException(401,'Lien média TikTok invalide ou expiré')
        with db() as c:
            from storage_schema import ensure_storage_schema as _ensure;_ensure(c)
            row=c.execute("select content_type,data,size,storage_key from assets where id=%s and kind='render'",(aid,)).fetchone()
        if not row:raise HTTPException(404,'Media introuvable')
        ctype,data,size,key=row;total=int(size or 0)
        return StreamingResponse(_stream_asset(key,data,total),media_type=ctype or 'video/mp4',headers={'Content-Length':str(total),'Cache-Control':'private, no-store','X-Content-Type-Options':'nosniff'})

    async def direct_post(publication_id:str,x:DirectPostIn,authorization:Optional[str]=Header(None)):
        require_studio(authorization)
        if not x.consent:raise HTTPException(400,'Ton consentement explicite est requis avant l’envoi à TikTok.')
        if not PULL_VERIFIED:raise HTTPException(409,'Le préfixe média doit être vérifié dans TikTok Developer avant Direct Post.')
        s=connection_status()
        if not s.get('directPostReady'):raise HTTPException(409,'TikTok video.publish non autorisé.')
        try:qid=uuid.UUID(publication_id)
        except Exception:raise HTTPException(400,'Publication invalide')
        creator=await creator_info_call()
        if x.privacyLevel not in creator['privacyLevels']:raise HTTPException(400,'Niveau de confidentialité TikTok non autorisé pour ce compte.')
        if creator['commentDisabled'] and x.allowComment:raise HTTPException(400,'Les commentaires sont désactivés pour ce créateur.')
        if creator['duetDisabled'] and x.allowDuet:raise HTTPException(400,'Duet est désactivé pour ce créateur.')
        if creator['stitchDisabled'] and x.allowStitch:raise HTTPException(400,'Stitch est désactivé pour ce créateur.')
        row=_publication(qid);_,aid,caption,tags,cta,status,name,ctype,data,size,key,metadata=row
        duration=float((metadata or {}).get('duration') or 0) if isinstance(metadata,dict) else 0
        if creator['maxDurationSec'] and duration and duration>creator['maxDurationSec']:raise HTTPException(400,'La vidéo dépasse la durée maximale autorisée par ce compte TikTok.')
        title=_title(caption,tags,cta);access=get_access_token();video_url=pull_url(aid)
        body={'post_info':{'title':title,'privacy_level':x.privacyLevel,'disable_duet':not x.allowDuet,'disable_comment':not x.allowComment,'disable_stitch':not x.allowStitch,'is_aigc':bool(x.isAigc)},'source_info':{'source':'PULL_FROM_URL','video_url':video_url}}
        async with httpx.AsyncClient(timeout=45) as client:
            r=await client.post('https://open.tiktokapis.com/v2/post/publish/video/init/',headers={'Authorization':'Bearer '+access,'Content-Type':'application/json; charset=UTF-8'},json=body)
        if r.status_code>=400:raise HTTPException(502,'TikTok Direct Post a refusé l’initialisation.')
        payload=r.json();_api_error(payload);publish_id=str((payload.get('data') or {}).get('publish_id') or '')
        if not publish_id:raise HTTPException(502,'TikTok n’a pas renvoyé de publish_id.')
        with db() as c:c.execute("update publications set status='publishing',external_id=%s,error='',updated_at=now() where id=%s",(publish_id,qid))
        return {'ok':True,'status':'publishing','publishId':publish_id,'message':'Vidéo envoyée à TikTok. Le traitement et la modération sont asynchrones.'}

    async def fetch_status(publication_id:str,authorization:Optional[str]=Header(None)):
        require_studio(authorization)
        try:qid=uuid.UUID(publication_id)
        except Exception:raise HTTPException(400,'Publication invalide')
        with db() as c:row=c.execute('select external_id from publications where id=%s',(qid,)).fetchone()
        if not row:raise HTTPException(404,'Publication introuvable')
        publish_id=str(row[0] or '')
        if not publish_id:raise HTTPException(409,'Cette publication n’a pas encore de publish_id TikTok.')
        access=get_access_token()
        async with httpx.AsyncClient(timeout=30) as client:
            r=await client.post('https://open.tiktokapis.com/v2/post/publish/status/fetch/',headers={'Authorization':'Bearer '+access,'Content-Type':'application/json; charset=UTF-8'},json={'publish_id':publish_id})
        if r.status_code>=400:raise HTTPException(502,'Statut TikTok indisponible')
        payload=r.json();_api_error(payload);data=payload.get('data') or {};remote=str(data.get('status') or '')
        local='publishing';fail=''
        if remote=='PUBLISH_COMPLETE':local='published'
        elif remote=='FAILED':local='failed';fail=str(data.get('fail_reason') or 'Échec TikTok')[:500]
        with db() as c:
            if local=='published':c.execute("update publications set status='published',published_at=coalesce(published_at,now()),error='',updated_at=now() where id=%s",(qid,))
            elif local=='failed':c.execute("update publications set status='failed',error=%s,updated_at=now() where id=%s",(fail,qid))
            else:c.execute("update publications set status='publishing',updated_at=now() where id=%s",(qid,))
        return {'status':local,'tiktokStatus':remote,'failReason':fail,'uploadedBytes':data.get('uploaded_bytes'),'postIds':data.get('publicaly_available_post_id') or []}

    app.add_api_route('/api/tiktok/readiness',readiness,methods=['GET'],include_in_schema=False)
    app.add_api_route('/api/tiktok/creator-info',creator_info,methods=['GET'],include_in_schema=False)
    app.add_api_route('/api/tiktok/pull/{asset_id}',pull_media,methods=['GET'],include_in_schema=False)
    app.add_api_route('/api/tiktok/direct-post/{publication_id}',direct_post,methods=['POST'],include_in_schema=False)
    app.add_api_route('/api/tiktok/post-status/{publication_id}',fetch_status,methods=['POST'],include_in_schema=False)
