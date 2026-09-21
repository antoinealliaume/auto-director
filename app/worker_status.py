# -*- coding: utf-8 -*-
"""Authenticated same-origin worker status for the private Studio UI."""
import json
import os
from typing import Optional

import redis
import psycopg
from fastapi import Header, HTTPException
from fastapi.responses import JSONResponse

REDIS_URL = os.environ.get('REDIS_URL','')
LOCAL_KEY = 'autodirector:worker:local:heartbeat'
CLOUD_KEY = 'autodirector:worker:cloud:heartbeat'
QUEUE_KEY = 'auto_director:jobs'
RETRY_KEY = 'auto_director:jobs:retry'
DATABASE_URL = os.environ.get('DATABASE_URL','')
EXPECTED_AGENT_VERSION = '2.8'
INSTALLER_URL = '/static/INSTALL_AUTO_DIRECTOR_WORKER.bat?v=2.8'
from .worker_diagnostics import diagnostic_state,select_active_worker,with_heartbeat_age


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
        q=_redis();q.ping();local=with_heartbeat_age(_read(q,LOCAL_KEY));cloud=with_heartbeat_age(_read(q,CLOUD_KEY))
        try:depth=int(q.llen(QUEUE_KEY))
        except Exception:depth=None
        try:retry_depth=int(q.zcard(RETRY_KEY))
        except Exception:retry_depth=None
        kind,active,compatibility=select_active_worker(local,cloud)
        current=None
        try:
            with psycopg.connect(DATABASE_URL) as c:
                row=c.execute("select id,status,stage,progress,message,updated_at from jobs where status in ('claimed','running') order by updated_at desc limit 1").fetchone()
            if row:current={'id':str(row[0]),'status':row[1],'stage':row[2],'progress':row[3],'message':row[4],'updatedAt':row[5].isoformat()}
        except Exception:pass
        diagnostic=diagnostic_state(active=active,compatibility=compatibility,queue_depth=depth,retry_depth=retry_depth,current_job=current)
        return {'ok':bool(active and compatibility and compatibility['compatible']),'api':'online','activeWorker':kind,'worker':active,'compatibility':compatibility,'diagnostic':diagnostic,'currentJob':current,'localWorkerOnline':bool(local),'cloudWorkerOnline':bool(cloud),'localWorker':local,'cloudWorker':cloud,'queueDepth':depth,'retryDepth':retry_depth,'workerUpdate':{'expectedAgentVersion':EXPECTED_AGENT_VERSION,'installerUrl':INSTALLER_URL,'automaticInstall':False},'publicationMode':'manual-only'}
    except Exception:
        return {'ok':False,'activeWorker':None,'worker':None,'localWorkerOnline':False,'cloudWorkerOnline':False,'localWorker':None,'cloudWorker':None,'queueDepth':None,'retryDepth':None,'diagnostic':{'level':'unavailable','message':'Diagnostics worker indisponibles.','queued':0,'delayedRetries':0},'workerUpdate':{'expectedAgentVersion':EXPECTED_AGENT_VERSION,'installerUrl':INSTALLER_URL,'automaticInstall':False},'publicationMode':'manual-only','error':'queue-unavailable'}


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
