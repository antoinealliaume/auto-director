# -*- coding: utf-8 -*-
import hashlib
import json
import os

import redis
from fastapi.responses import JSONResponse

from .job_lifecycle import MIN_WORKER_ENGINE
from .v9_api import attach as attach_v9

REDIS_URL = os.environ.get('REDIS_URL', '')
LOGIN_LIMIT = max(5, min(30, int(os.environ.get('LOGIN_LIMIT', '10'))))
LOGIN_WINDOW = max(60, min(3600, int(os.environ.get('LOGIN_WINDOW_SECONDS', '600'))))
GLOBAL_LOGIN_LIMIT = max(50, min(500, int(os.environ.get('GLOBAL_LOGIN_LIMIT', '120'))))
LOCAL_HEARTBEAT = 'autodirector:worker:local:heartbeat'


def _queue():
    return redis.from_url(REDIS_URL, decode_responses=True) if REDIS_URL else None


def _source_id(request):
    forwarded = (request.headers.get('x-forwarded-for') or '').split(',', 1)[0].strip()
    host = forwarded or (request.client.host if request.client else 'unknown')
    return hashlib.sha256(host.encode()).hexdigest()[:20]


def _studio_authorized(request):
    auth = request.headers.get('authorization') or ''
    token = auth[7:] if auth.startswith('Bearer ') else ''
    if not token:return False
    try:
        from .main import verify_token
        return bool(verify_token(token))
    except Exception:return False


def _worker_engine(request):
    try:
        from .local_worker_api2 import require_worker
        wid=require_worker(request.headers.get('authorization'));q=_queue();raw=q.get(LOCAL_HEARTBEAT) if q else None;info=json.loads(raw) if raw else {}
        if str(info.get('workerId') or '')!=str(wid):return (0,0),info
        parts=str(info.get('engine') or '0').strip().split('.')
        major=int(parts[0]) if parts and parts[0].isdigit() else 0;minor=int(parts[1]) if len(parts)>1 and parts[1].isdigit() else 0
        return (major,minor),info
    except Exception:return (0,0),{}


def attach(app):
    attach_v9(app)

    @app.middleware('http')
    async def security_middleware(request, call_next):
        path=request.url.path
        if path=='/api/worker/bootstrap':
            return JSONResponse({'detail':'Legacy worker bootstrap disabled. Use the HTTPS local-worker protocol.'},status_code=410,headers={'Cache-Control':'no-store'})

        # Keep the early upgrade response aligned with the canonical worker contract.
        # Otherwise a 9.1 worker can be told that 9.1 is sufficient before the claim
        # endpoint rejects it because the actual minimum is newer.
        if path=='/api/local-worker/jobs/claim' and request.method=='POST':
            version,_info=_worker_engine(request)
            if version<MIN_WORKER_ENGINE:
                return JSONResponse({'job':None,'upgradeRequired':True,'minimumEngine':'.'.join(map(str,MIN_WORKER_ENGINE)),'minimumAgent':'2.6'},status_code=200,headers={'Cache-Control':'no-store'})

        if path=='/health/deep' and not _studio_authorized(request):
            return JSONResponse({'detail':'Authentification requise'},status_code=401,headers={'Cache-Control':'no-store'})

        q=None;source_key=global_key=None
        if path=='/api/login' and request.method=='POST':
            try:
                q=_queue();source_key='autodirector:security:login_failures:'+_source_id(request);global_key='autodirector:security:login_failures:global'
                source_hits=int(q.get(source_key) or 0) if q else 0;global_hits=int(q.get(global_key) or 0) if q else 0
                if q and (source_hits>=LOGIN_LIMIT or global_hits>=GLOBAL_LOGIN_LIMIT):
                    return JSONResponse({'detail':'Trop de tentatives. Réessaie dans quelques minutes.'},status_code=429,headers={'Retry-After':str(LOGIN_WINDOW),'Cache-Control':'no-store'})
            except Exception:q=None

        response=await call_next(request)
        if path=='/api/login' and request.method=='POST' and q and source_key and global_key:
            try:
                if response.status_code==401:
                    for key in (source_key,global_key):
                        n=q.incr(key)
                        if n==1:q.expire(key,LOGIN_WINDOW)
                elif 200<=response.status_code<300:q.delete(source_key)
            except Exception:pass

        response.headers['X-Content-Type-Options']='nosniff';response.headers['X-Frame-Options']='DENY';response.headers['Referrer-Policy']='no-referrer';response.headers['Permissions-Policy']='camera=(), microphone=(), geolocation=()';response.headers['Cross-Origin-Opener-Policy']='same-origin';response.headers['Strict-Transport-Security']='max-age=31536000; includeSubDomains'
        response.headers['Content-Security-Policy']=("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; media-src 'self' blob:; connect-src 'self' http://127.0.0.1:8765; object-src 'none'; base-uri 'self'; frame-ancestors 'none'")
        if path.startswith('/api/') or path=='/health/deep':response.headers['Cache-Control']='no-store, max-age=0'
        return response
