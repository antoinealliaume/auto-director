# -*- coding: utf-8 -*-
"""Authenticated same-origin worker status for the private Studio UI."""
import json
import os
from typing import Optional

import redis
from fastapi import Header, HTTPException
from fastapi.responses import JSONResponse

REDIS_URL = os.environ.get('REDIS_URL','')
LOCAL_KEY = 'autodirector:worker:local:heartbeat'
CLOUD_KEY = 'autodirector:worker:cloud:heartbeat'
QUEUE_KEY = 'auto_director:jobs'


def _redis():
    return redis.from_url(REDIS_URL,decode_responses=True)


def _read(q,key):
    try:
        raw=q.get(key)
        if not raw:return None
        value=json.loads(raw)
        return value if isinstance(value,dict) else None
    except Exception:return None


def worker_status_payload():
    try:
        q=_redis();q.ping();local=_read(q,LOCAL_KEY);cloud=_read(q,CLOUD_KEY)
        try:depth=int(q.llen(QUEUE_KEY))
        except Exception:depth=None
        active=local or cloud;kind='local' if local else ('cloud' if cloud else None)
        return {'ok':bool(active),'activeWorker':kind,'worker':active,'localWorkerOnline':bool(local),'cloudWorkerOnline':bool(cloud),'localWorker':local,'cloudWorker':cloud,'queueDepth':depth}
    except Exception:
        return {'ok':False,'activeWorker':None,'worker':None,'localWorkerOnline':False,'cloudWorkerOnline':False,'localWorker':None,'cloudWorker':None,'queueDepth':None,'error':'queue-unavailable'}


def attach(app):
    async def endpoint(authorization:Optional[str]=Header(None)):
        token=authorization[7:] if authorization and authorization.startswith('Bearer ') else ''
        try:
            from .main import verify_token
            valid=bool(token and verify_token(token))
        except Exception:valid=False
        if not valid:raise HTTPException(401,'Session Studio requise')
        return JSONResponse(worker_status_payload(),headers={'Cache-Control':'no-store, max-age=0'})
    app.add_api_route('/api/worker-status',endpoint,methods=['GET'],include_in_schema=False)
