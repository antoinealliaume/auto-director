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

DATABASE_URL=os.environ.get('DATABASE_URL','')
MEDIA_TTL=max(300,min(3600,int(os.environ.get('MEDIA_TICKET_TTL','1800'))))


def db():return psycopg.connect(DATABASE_URL)
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
    raw=f'm.{int(time.time())}.{asset_id}.{secrets.token_urlsafe(16)}'
    return raw+'.'+sign(raw)
def verify_ticket(ticket,asset_id):
    raw,sep,sig=(ticket or '').rpartition('.')
    if not sep or not hmac.compare_digest(sign(raw),sig):return False
    p=raw.split('.')
    if len(p)!=4 or p[0]!='m' or p[2]!=str(asset_id):return False
    try:age=int(time.time())-int(p[1])
    except Exception:return False
    return 0<=age<=MEDIA_TTL


def attach(app):
    async def ticket(asset_id:str,authorization:Optional[str]=Header(None)):
        require_studio(authorization);aid=uuid.UUID(asset_id)
        with db() as c:row=c.execute("select 1 from assets where id=%s and kind='render'",(aid,)).fetchone()
        if not row:raise HTTPException(404,'Rendu introuvable')
        return JSONResponse({'ticket':make_ticket(aid),'expiresIn':MEDIA_TTL},headers={'Cache-Control':'no-store'})

    async def media(asset_id:str,request:Request,ticket:str=Query(...)):
        aid=uuid.UUID(asset_id)
        if not verify_ticket(ticket,aid):raise HTTPException(401,'Ticket média invalide ou expiré')
        with db() as c:row=c.execute("select name,content_type,data,size from assets where id=%s and kind='render'",(aid,)).fetchone()
        if not row:raise HTTPException(404,'Rendu introuvable')
        name,ctype,data,size=row;blob=bytes(data);total=len(blob)
        headers={'Accept-Ranges':'bytes','Cache-Control':'private, max-age=300','Content-Disposition':f'inline; filename="{os.path.basename(name)}"'}
        range_header=request.headers.get('range','')
        if range_header.startswith('bytes='):
            try:
                spec=range_header[6:].split(',',1)[0];a,b=spec.split('-',1)
                start=int(a) if a else max(0,total-int(b));end=int(b) if b else total-1
                start=max(0,min(start,total-1));end=max(start,min(end,total-1));part=blob[start:end+1]
                headers['Content-Range']=f'bytes {start}-{end}/{total}'
                return Response(part,status_code=206,media_type=ctype or 'video/mp4',headers=headers)
            except Exception:pass
        return Response(blob,media_type=ctype or 'video/mp4',headers=headers)

    app.add_api_route('/api/media-ticket/{asset_id}',ticket,methods=['POST'],include_in_schema=False)
    app.add_api_route('/api/media/{asset_id}',media,methods=['GET'],include_in_schema=False)
