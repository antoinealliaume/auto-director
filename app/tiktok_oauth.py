# -*- coding: utf-8 -*-
"""Official TikTok OAuth 2.0 connection for Auto Director.

Tokens are encrypted at rest and never returned to browser code. Direct posting is
kept separate and only becomes available when TikTok has granted the required scope.
"""
import base64
import hashlib
import os
import secrets
import time
from datetime import datetime, timedelta, timezone
from typing import Optional
from urllib.parse import urlencode

import httpx
import psycopg
import redis
from cryptography.fernet import Fernet, InvalidToken
from fastapi import Header, HTTPException, Query
from fastapi.responses import HTMLResponse

DATABASE_URL=os.environ.get('DATABASE_URL','')
REDIS_URL=os.environ.get('REDIS_URL','')
CLIENT_KEY=os.environ.get('TIKTOK_CLIENT_KEY','').strip()
CLIENT_SECRET=os.environ.get('TIKTOK_CLIENT_SECRET','').strip()
REDIRECT_URI=os.environ.get('TIKTOK_REDIRECT_URI','https://auto-director-web.onrender.com/api/tiktok/callback').strip()
SCOPES=os.environ.get('TIKTOK_SCOPES','user.info.basic,video.upload,video.publish').strip()
OWNER='studio_owner'
STATE_TTL=600


def db():return psycopg.connect(DATABASE_URL)
def rq():return redis.from_url(REDIS_URL,decode_responses=True)
def require_studio(auth):
    token=auth[7:] if auth and auth.startswith('Bearer ') else ''
    from .main import verify_token
    if not token or not verify_token(token):raise HTTPException(401,'Session invalide')
def configured():return bool(CLIENT_KEY and CLIENT_SECRET and REDIRECT_URI.startswith('https://'))
def _fernet():
    raw=os.environ.get('TIKTOK_TOKEN_ENCRYPTION_KEY','').strip()
    if not raw:raise RuntimeError('TIKTOK_TOKEN_ENCRYPTION_KEY missing')
    key=base64.urlsafe_b64encode(hashlib.sha256(raw.encode()).digest())
    return Fernet(key)
def encrypt(value):return _fernet().encrypt((value or '').encode()).decode()
def decrypt(value):
    try:return _fernet().decrypt((value or '').encode()).decode()
    except InvalidToken as exc:raise RuntimeError('TikTok token encryption key mismatch') from exc

def ensure_schema():
    with db() as c:
        c.execute('''create table if not exists tiktok_connections(
            id text primary key,
            open_id text not null default '',
            access_token_enc text not null,
            refresh_token_enc text not null,
            scopes text not null default '',
            expires_at timestamptz not null,
            refresh_expires_at timestamptz not null,
            created_at timestamptz not null default now(),
            updated_at timestamptz not null default now()
        )''')

def _state_key(state):return 'autodirector:tiktok:oauth:'+hashlib.sha256(state.encode()).hexdigest()
def create_state():
    state=secrets.token_urlsafe(36);rq().set(_state_key(state),'1',ex=STATE_TTL);return state
def consume_state(state):
    if not state:return False
    r=rq();key=_state_key(state)
    try:
        pipe=r.pipeline();pipe.get(key);pipe.delete(key);value,_=pipe.execute();return value=='1'
    except Exception:return False

def _save_tokens(data):
    access=str(data.get('access_token') or '');refresh=str(data.get('refresh_token') or '')
    if not access or not refresh:raise RuntimeError('TikTok did not return complete token bundle')
    now=datetime.now(timezone.utc);expires=now+timedelta(seconds=max(60,int(data.get('expires_in') or 86400)));refresh_exp=now+timedelta(seconds=max(3600,int(data.get('refresh_expires_in') or 31536000)))
    ensure_schema()
    with db() as c:
        c.execute('''insert into tiktok_connections(id,open_id,access_token_enc,refresh_token_enc,scopes,expires_at,refresh_expires_at)
            values(%s,%s,%s,%s,%s,%s,%s)
            on conflict(id) do update set open_id=excluded.open_id,access_token_enc=excluded.access_token_enc,
            refresh_token_enc=excluded.refresh_token_enc,scopes=excluded.scopes,expires_at=excluded.expires_at,
            refresh_expires_at=excluded.refresh_expires_at,updated_at=now()''',
            (OWNER,str(data.get('open_id') or ''),encrypt(access),encrypt(refresh),str(data.get('scope') or ''),expires,refresh_exp))

def connection_status():
    if not configured():return {'configured':False,'connected':False,'scopes':[],'directPostReady':False,'uploadReady':False}
    try:ensure_schema()
    except Exception:return {'configured':True,'connected':False,'scopes':[],'directPostReady':False,'uploadReady':False}
    with db() as c:row=c.execute('select open_id,scopes,expires_at,refresh_expires_at from tiktok_connections where id=%s',(OWNER,)).fetchone()
    if not row:return {'configured':True,'connected':False,'scopes':[],'directPostReady':False,'uploadReady':False}
    scopes=[x.strip() for x in (row[1] or '').split(',') if x.strip()];now=datetime.now(timezone.utc)
    return {'configured':True,'connected':row[3]>now,'scopes':scopes,'directPostReady':'video.publish' in scopes and row[3]>now,'uploadReady':'video.upload' in scopes and row[3]>now,'expiresAt':row[2].isoformat(),'refreshExpiresAt':row[3].isoformat(),'openIdSuffix':(row[0][-6:] if row[0] else '')}

def get_access_token():
    if not configured():raise RuntimeError('TikTok OAuth application is not configured')
    ensure_schema()
    with db() as c:row=c.execute('select access_token_enc,refresh_token_enc,expires_at,refresh_expires_at from tiktok_connections where id=%s',(OWNER,)).fetchone()
    if not row:raise RuntimeError('TikTok account is not connected')
    now=datetime.now(timezone.utc)
    if row[3]<=now:raise RuntimeError('TikTok authorization expired; reconnect required')
    if row[2]>now+timedelta(minutes=15):return decrypt(row[0])
    refresh=decrypt(row[1])
    with httpx.Client(timeout=30) as c:
        r=c.post('https://open.tiktokapis.com/v2/oauth/token/',data={'client_key':CLIENT_KEY,'client_secret':CLIENT_SECRET,'grant_type':'refresh_token','refresh_token':refresh},headers={'Content-Type':'application/x-www-form-urlencoded','Cache-Control':'no-cache'})
        r.raise_for_status();data=r.json()
    if data.get('error'):raise RuntimeError(str(data.get('error_description') or data['error']))
    _save_tokens(data);return str(data['access_token'])


def attach(app):
    async def status(authorization:Optional[str]=Header(None)):
        require_studio(authorization);return connection_status()

    async def connect(authorization:Optional[str]=Header(None)):
        require_studio(authorization)
        if not configured():raise HTTPException(409,'Application TikTok Developer non configurée.')
        try:_fernet()
        except Exception:raise HTTPException(503,'Chiffrement des tokens TikTok non configuré.')
        state=create_state();params={'client_key':CLIENT_KEY,'response_type':'code','scope':SCOPES,'redirect_uri':REDIRECT_URI,'state':state}
        return {'authorizationUrl':'https://www.tiktok.com/v2/auth/authorize/?'+urlencode(params),'expiresIn':STATE_TTL}

    async def callback(code:Optional[str]=Query(None),state:Optional[str]=Query(None),error:Optional[str]=Query(None),error_description:Optional[str]=Query(None)):
        if error:return HTMLResponse(f'<!doctype html><meta charset="utf-8"><title>TikTok</title><h2>Connexion TikTok refusée</h2><p>{str(error_description or error)[:300]}</p><p>Tu peux fermer cette page.</p>',status_code=400)
        if not configured() or not code or not consume_state(state or ''):return HTMLResponse('<!doctype html><meta charset="utf-8"><title>TikTok</title><h2>Connexion TikTok invalide ou expirée.</h2>',status_code=400)
        try:
            async with httpx.AsyncClient(timeout=30) as c:
                r=await c.post('https://open.tiktokapis.com/v2/oauth/token/',data={'client_key':CLIENT_KEY,'client_secret':CLIENT_SECRET,'code':code,'grant_type':'authorization_code','redirect_uri':REDIRECT_URI},headers={'Content-Type':'application/x-www-form-urlencoded','Cache-Control':'no-cache'})
                r.raise_for_status();data=r.json()
            if data.get('error'):raise RuntimeError(str(data.get('error_description') or data['error']))
            _save_tokens(data)
        except Exception as exc:
            return HTMLResponse('<!doctype html><meta charset="utf-8"><title>TikTok</title><h2>Connexion TikTok impossible.</h2><p>'+str(exc)[:300]+'</p>',status_code=502)
        return HTMLResponse('<!doctype html><meta charset="utf-8"><title>TikTok connecté</title><style>body{font-family:system-ui;background:#090b12;color:#fff;padding:60px;text-align:center}a{color:#aeb5ff}</style><h2>TikTok est connecté ✅</h2><p>Les tokens sont chiffrés côté serveur. Tu peux revenir au Studio.</p><p><a href="/">Retour au Studio</a></p>')

    async def disconnect(authorization:Optional[str]=Header(None)):
        require_studio(authorization);ensure_schema();access=None
        with db() as c:row=c.execute('select access_token_enc from tiktok_connections where id=%s',(OWNER,)).fetchone()
        if row:
            try:access=decrypt(row[0])
            except Exception:pass
        if access and configured():
            try:
                async with httpx.AsyncClient(timeout=20) as c:await c.post('https://open.tiktokapis.com/v2/oauth/revoke/',data={'client_key':CLIENT_KEY,'client_secret':CLIENT_SECRET,'token':access},headers={'Content-Type':'application/x-www-form-urlencoded','Cache-Control':'no-cache'})
            except Exception:pass
        with db() as c:c.execute('delete from tiktok_connections where id=%s',(OWNER,))
        return {'ok':True}

    app.add_api_route('/api/tiktok/status',status,methods=['GET'],include_in_schema=False)
    app.add_api_route('/api/tiktok/connect',connect,methods=['POST'],include_in_schema=False)
    app.add_api_route('/api/tiktok/callback',callback,methods=['GET'],include_in_schema=False)
    app.add_api_route('/api/tiktok/disconnect',disconnect,methods=['POST'],include_in_schema=False)
