# -*- coding: utf-8 -*-
import hashlib
import hmac
import os
import secrets
import time
import uuid
from typing import Optional

import psycopg
from fastapi import Header, HTTPException, Query, Request
from fastapi.responses import JSONResponse, Response

import storage_backend as media_store
from storage_schema import ensure_storage_schema


def _env_int(name, default, minimum, maximum):
    try:
        value = int(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(maximum, value))


DATABASE_URL=os.environ.get('DATABASE_URL','')
MEDIA_TTL=_env_int('MEDIA_TICKET_TTL',1800,300,3600)


def db():return psycopg.connect(DATABASE_URL)
def _uuid(value):
    try:return uuid.UUID(str(value))
    except Exception as exc:raise HTTPException(400,'Rendu invalide') from exc
def secret():
    v=os.environ.get('TOKEN_SECRET','')
    if v:return v
    from .main import TOKEN_SECRET
    return TOKEN_SECRET
def sign(raw):return hmac.new(secret().encode(),raw.encode(),hashlib.sha256).hexdigest()
def require_studio(auth):
    token=auth[7:] if auth and auth.startswith('Bearer ') else ''
    from .main import verify_token
    if not token or not verify_token(token):raise HTTPException(401,'Session invalide')
def make_ticket(asset_id):
    raw=f'm.{int(time.time())}.{asset_id}.{secrets.token_urlsafe(16)}';return raw+'.'+sign(raw)
def verify_ticket(ticket,asset_id):
    raw,sep,sig=(ticket or '').rpartition('.')
    if not sep or not hmac.compare_digest(sign(raw),sig):return False
    p=raw.split('.')
    if len(p)!=4 or p[0]!='m' or p[2]!=str(asset_id):return False
    try:age=int(time.time())-int(p[1])
    except Exception:return False
    return 0<=age<=MEDIA_TTL

def _range(total,header):
    if not header.startswith('bytes=') or total<=0:return None
    try:
        spec=header[6:].split(',',1)[0];a,b=spec.split('-',1)
        if not a:length=max(1,int(b));start=max(0,total-length);end=total-1
        else:start=int(a);end=int(b) if b else total-1
        if start<0 or start>=total:return None
        return start,max(start,min(end,total-1))
    except Exception:return None

def attach(app):
    async def ticket(asset_id:str,authorization:Optional[str]=Header(None)):
        require_studio(authorization);aid=_uuid(asset_id)
        with db() as c:row=c.execute("select 1 from assets where id=%s and kind='render'",(aid,)).fetchone()
        if not row:raise HTTPException(404,'Rendu introuvable')
        return JSONResponse({'ticket':make_ticket(aid),'expiresIn':MEDIA_TTL},headers={'Cache-Control':'no-store'})

    async def media(asset_id:str,request:Request,ticket:str=Query(...)):
        aid=_uuid(asset_id)
        if not verify_ticket(ticket,aid):raise HTTPException(401,'Ticket média invalide ou expiré')
        with db() as c:
            ensure_storage_schema(c);row=c.execute("select name,content_type,data,size,storage_key from assets where id=%s and kind='render'",(aid,)).fetchone()
        if not row:raise HTTPException(404,'Rendu introuvable')
        name,ctype,data,size,storage_key=row;total=int(size or 0);safe_name=os.path.basename(name or 'render.mp4').replace('"','_')[:180]
        headers={'Accept-Ranges':'bytes','Cache-Control':'private, max-age=300','Content-Disposition':f'inline; filename="{safe_name}"'};wanted=_range(total,request.headers.get('range',''))
        try:
            if wanted:
                start,end=wanted;part=media_store.get_range(storage_key,start,end) if storage_key else bytes(data or b'')[start:end+1];headers['Content-Range']=f'bytes {start}-{end}/{total}';headers['Content-Length']=str(len(part));return Response(part,status_code=206,media_type=ctype or 'video/mp4',headers=headers)
            payload=media_store.read_asset(storage_key,data);headers['Content-Length']=str(len(payload));return Response(payload,media_type=ctype or 'video/mp4',headers=headers)
        except Exception as exc:raise HTTPException(503,'Média temporairement indisponible') from exc

    app.add_api_route('/api/media-ticket/{asset_id}',ticket,methods=['POST'],include_in_schema=False)
    app.add_api_route('/api/media/{asset_id}',media,methods=['GET'],include_in_schema=False)
