# -*- coding: utf-8 -*-
import hashlib
import hmac
import json
import math
import os
import secrets
import statistics
import time
import uuid
from datetime import datetime, timezone
from typing import Optional

import psycopg
import redis
from fastapi import File, Form, Header, HTTPException, Query, UploadFile
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field
from psycopg.types.json import Jsonb

DATABASE_URL = os.environ.get('DATABASE_URL', '')
REDIS_URL = os.environ.get('REDIS_URL', '')
WORKER_TOKEN_TTL = max(1800, min(24 * 3600, int(os.environ.get('WORKER_TOKEN_TTL', str(12 * 3600)))))
LOCAL_HEARTBEAT_KEY = 'autodirector:worker:local:heartbeat'
QUEUE_KEY = 'auto_director:jobs'
MAX_REMOTE_OUTPUT_MB = max(20, min(250, int(os.environ.get('MAX_REMOTE_OUTPUT_MB', '120'))))


def db():
    return psycopg.connect(DATABASE_URL)


def q():
    return redis.from_url(REDIS_URL, decode_responses=True)


def _secret():
    value = os.environ.get('TOKEN_SECRET', '')
    if value:
        return value
    # Lazy import avoids the app.main import cycle during FastAPI construction.
    from .main import TOKEN_SECRET
    return TOKEN_SECRET


def _sign(raw: str) -> str:
    return hmac.new(_secret().encode(), raw.encode(), hashlib.sha256).hexdigest()


def _studio_token(auth: Optional[str]) -> str:
    token = auth[7:] if auth and auth.startswith('Bearer ') else ''
    if not token:
        raise HTTPException(401, 'Session Studio requise')
    from .main import verify_token
    if not verify_token(token):
        raise HTTPException(401, 'Session Studio invalide ou expirée')
    return token


def _make_worker_token(worker_id: str) -> str:
    issued = int(time.time())
    raw = f'w.{issued}.{worker_id}.{secrets.token_urlsafe(24)}'
    return raw + '.' + _sign(raw)


def _worker_id(auth: Optional[str]) -> str:
    token = auth[7:] if auth and auth.startswith('Bearer ') else ''
    raw, sep, sig = token.rpartition('.')
    if not sep or not hmac.compare_digest(_sign(raw), sig):
        raise HTTPException(401, 'Jeton worker invalide')
    parts = raw.split('.')
    if len(parts) != 4 or parts[0] != 'w':
        raise HTTPException(401, 'Jeton worker invalide')
    try:
        issued = int(parts[1])
    except Exception:
        raise HTTPException(401, 'Jeton worker invalide')
    age = int(time.time()) - issued
    if age < 0 or age > WORKER_TOKEN_TTL:
        raise HTTPException(401, 'Jeton worker expiré')
    return parts[2]


def _ensure_schema():
    with db() as c:
        c.execute('''
            create table if not exists worker_leases(
                job_id uuid primary key references jobs(id) on delete cascade,
                worker_id text not null,
                lease_expires timestamptz not null,
                updated_at timestamptz not null default now()
            )
        ''')
        c.execute('create index if not exists idx_worker_leases_expiry on worker_leases(lease_expires)')


def _lease(job_id: uuid.UUID, worker_id: str, refresh=True):
    _ensure_schema()
    with db() as c:
        row = c.execute(
            'select j.project_id,j.settings,j.status from worker_leases l join jobs j on j.id=l.job_id '
            'where l.job_id=%s and l.worker_id=%s and l.lease_expires>now()',
            (job_id, worker_id),
        ).fetchone()
        if not row:
            raise HTTPException(409, 'Lease worker absent ou expiré')
        if refresh:
            c.execute("update worker_leases set lease_expires=now()+interval '35 minutes',updated_at=now() where job_id=%s and worker_id=%s", (job_id, worker_id))
        return row


def _memory_context(project_id):
    with db() as c:
        rows = c.execute('''
            select a.name,a.metadata,coalesce(sum(f.views),0),coalesce(sum(f.likes),0),
                   coalesce(sum(f.comments),0),coalesce(sum(f.shares),0),
                   coalesce(avg(f.completion),0),coalesce(sum(f.conversions),0),coalesce(sum(f.revenue),0)
            from assets a left join feedback f on f.asset_id=a.id
            where a.project_id=%s and a.kind='render'
            group by a.id,a.name,a.metadata order by coalesce(sum(f.views),0) desc limit 30
        ''', (project_id,)).fetchall()
        try:
            trends = c.execute("select label,coalesce(source_url,''),notes from trends order by created_at desc limit 10").fetchall()
        except Exception:
            trends = []
    perf = []
    strategy_values = {}
    for name, meta, views, likes, comments, shares, completion, conversions, revenue in rows:
        views = int(views or 0)
        engagement = (float(likes or 0) + 2 * float(comments or 0) + 4 * float(shares or 0)) / max(views, 1)
        completion = float(completion or 0)
        value = min(2.0, math.log1p(views) / 10.0) + 4.0 * engagement + 2.5 * completion + .2 * float(conversions or 0) + .02 * float(revenue or 0)
        meta = meta if isinstance(meta, dict) else {}
        strategy = str(meta.get('strategy', ''))
        if strategy:
            strategy_values.setdefault(strategy, []).append(value)
        perf.append({'name': name, 'views': views, 'completion': round(completion, 3), 'engagement': round(engagement, 4), 'strategy': strategy, 'hook': str(meta.get('hook', ''))[:120], 'pace': meta.get('pace'), 'value': round(value, 3)})
    winning = sorted(((k, statistics.mean(v)) for k, v in strategy_values.items()), key=lambda x: x[1], reverse=True)[:5]
    return {'performance': sorted(perf, key=lambda x: x['value'], reverse=True)[:10], 'winningStrategies': [{'strategy': k, 'score': round(v, 3)} for k, v in winning], 'trends': [{'label': x[0], 'url': x[1], 'notes': x[2]} for x in trends]}


class WorkerSessionIn(BaseModel):
    label: str = Field(default='windows-pc', max_length=80)


class HeartbeatIn(BaseModel):
    engine: str = Field(default='8.6', max_length=32)
    profile: str = Field(default='safe-unknown', max_length=80)
    resolution: list[int] = Field(default_factory=lambda: [720, 1280])
    fps: int = 30
    ffmpegThreads: int = 2
    localAI: bool = False
    model: Optional[str] = Field(default=None, max_length=120)


class ProgressIn(BaseModel):
    stage: str = Field(default='running', max_length=80)
    progress: int = 0
    message: str = Field(default='', max_length=500)
    score: Optional[float] = None
    revision: Optional[int] = None
    strategy: Optional[str] = Field(default=None, max_length=120)
    brief: Optional[dict] = None


class CompleteIn(BaseModel):
    score: float = 0
    revisionCount: int = 0
    strategy: str = Field(default='', max_length=120)
    message: str = Field(default='Rendu local terminé', max_length=500)


class FailIn(BaseModel):
    error: str = Field(default='Erreur worker local', max_length=500)


def attach(app):
    async def create_worker_session(x: WorkerSessionIn, authorization: Optional[str] = Header(None)):
        _studio_token(authorization)
        worker_id = uuid.uuid4().hex
        return JSONResponse({'workerToken': _make_worker_token(worker_id), 'workerId': worker_id, 'expiresIn': WORKER_TOKEN_TTL, 'protocol': 1}, headers={'Cache-Control': 'no-store'})

    async def heartbeat(x: HeartbeatIn, authorization: Optional[str] = Header(None)):
        wid = _worker_id(authorization)
        payload = {
            'kind': 'local', 'engine': x.engine, 'profile': x.profile,
            'resolution': [max(480, min(1080, int((x.resolution or [720, 1280])[0]))), max(854, min(1920, int((x.resolution or [720, 1280, 1280])[1])))],
            'fps': max(24, min(30, int(x.fps))), 'ffmpegThreads': max(1, min(6, int(x.ffmpegThreads))),
            'localAI': bool(x.localAI), 'model': x.model if x.localAI else None,
            'workerId': wid, 'updatedAt': int(time.time()), 'transport': 'https',
        }
        try:
            q().set(LOCAL_HEARTBEAT_KEY, json.dumps(payload), ex=20)
        except Exception as exc:
            raise HTTPException(503, 'Queue heartbeat indisponible') from exc
        return {'ok': True}

    async def claim(authorization: Optional[str] = Header(None)):
        wid = _worker_id(authorization)
        _ensure_schema()
        lock_key = None
        selected = None
        with db() as c:
            c.execute('delete from worker_leases where lease_expires<=now()')
            candidates = c.execute("select id,project_id,variants,settings from jobs where status='queued' order by created_at asc for update skip locked limit 10").fetchall()
            r = q()
            for row in candidates:
                jid = row[0]
                lk = 'autodirector:lock:' + str(jid)
                if r.set(lk, 'remote:' + wid, nx=True, ex=3600):
                    lock_key = lk
                    selected = row
                    c.execute("update jobs set status='running',stage='local_claim',progress=1,message='Pris par le worker PC',updated_at=now() where id=%s", (jid,))
                    c.execute("insert into worker_leases(job_id,worker_id,lease_expires) values(%s,%s,now()+interval '35 minutes') on conflict(job_id) do update set worker_id=excluded.worker_id,lease_expires=excluded.lease_expires,updated_at=now()", (jid, wid))
                    break
        if not selected:
            return JSONResponse({'job': None}, status_code=200)
        jid, project_id, variants, settings = selected
        try:
            q().lrem(QUEUE_KEY, 0, str(jid))
        except Exception:
            pass
        try:
            with db() as c:
                project = c.execute('select name from projects where id=%s', (project_id,)).fetchone()
                wanted = [uuid.UUID(str(x)) for x in (settings or {}).get('assetIds', [])]
                selected_assets = c.execute("select id,name,role,size,content_type,metadata from assets where project_id=%s and kind='source' and id=any(%s)", (project_id, wanted)).fetchall() if wanted else []
                refs = c.execute("select id,name,role,size,content_type,metadata from assets where project_id=%s and kind='source' and role='reference' order by created_at desc limit 5", (project_id,)).fetchall()
            seen = set()
            assets = []
            for row in list(selected_assets) + list(refs):
                if row[0] in seen:
                    continue
                seen.add(row[0])
                assets.append({'id': str(row[0]), 'name': row[1], 'role': row[2], 'size': int(row[3]), 'contentType': row[4], 'metadata': row[5] or {}})
            return {'job': {'id': str(jid), 'projectId': str(project_id), 'projectName': project[0] if project else 'Auto Director', 'variants': int(variants), 'settings': settings or {}, 'assets': assets, 'context': _memory_context(project_id)}}
        except Exception:
            if lock_key:
                try: q().delete(lock_key)
                except Exception: pass
            with db() as c:
                c.execute("update jobs set status='queued',stage='queued',message='Replacé en file après erreur de claim',updated_at=now() where id=%s", (jid,))
                c.execute('delete from worker_leases where job_id=%s', (jid,))
            raise

    async def asset(jobId: str = Query(...), asset_id: str = '', authorization: Optional[str] = Header(None)):
        wid = _worker_id(authorization)
        jid = uuid.UUID(jobId)
        project_id, settings, status = _lease(jid, wid)
        aid = uuid.UUID(asset_id)
        allowed_ids = {str(x) for x in (settings or {}).get('assetIds', [])}
        with db() as c:
            row = c.execute("select name,content_type,data,role from assets where id=%s and project_id=%s and kind='source'", (aid, project_id)).fetchone()
        if not row or (str(aid) not in allowed_ids and row[3] != 'reference'):
            raise HTTPException(404, 'Asset worker introuvable')
        return Response(bytes(row[2]), media_type=row[1], headers={'Content-Disposition': f'attachment; filename="{row[0]}"', 'Cache-Control': 'no-store'})

    async def progress(job_id: str, x: ProgressIn, authorization: Optional[str] = Header(None)):
        wid = _worker_id(authorization)
        jid = uuid.UUID(job_id)
        _, _, status = _lease(jid, wid)
        if status == 'cancelled':
            raise HTTPException(409, 'Job annulé')
        sets = ['status=\'running\'', 'stage=%s', 'progress=%s', 'message=%s', 'updated_at=now()']
        vals = [x.stage, max(0, min(99, int(x.progress))), x.message[:500]]
        if x.score is not None:
            sets.append('critic_score=%s'); vals.append(float(x.score))
        if x.revision is not None:
            sets.append('revision_count=%s'); vals.append(max(0, int(x.revision)))
        if x.strategy is not None:
            sets.append('strategy=%s'); vals.append(x.strategy[:120])
        if x.brief is not None:
            sets.append('creative_brief=%s'); vals.append(Jsonb(x.brief))
        vals.append(jid)
        with db() as c:
            c.execute('update jobs set ' + ','.join(sets) + ' where id=%s', vals)
            c.execute('insert into job_events(job_id,stage,message) values(%s,%s,%s)', (jid, x.stage, x.message[:500]))
        return {'ok': True}

    async def state(job_id: str, authorization: Optional[str] = Header(None)):
        wid = _worker_id(authorization)
        jid = uuid.UUID(job_id)
        _lease(jid, wid, refresh=False)
        with db() as c:
            row = c.execute('select status,stage,progress from jobs where id=%s', (jid,)).fetchone()
        return {'status': row[0], 'stage': row[1], 'progress': row[2]} if row else {'status': 'missing'}

    async def output(job_id: str, file: UploadFile = File(...), metadata_json: str = Form('{}'), authorization: Optional[str] = Header(None)):
        wid = _worker_id(authorization)
        jid = uuid.UUID(job_id)
        project_id, _, status = _lease(jid, wid)
        if status == 'cancelled':
            raise HTTPException(409, 'Job annulé')
        limit = MAX_REMOTE_OUTPUT_MB * 1024 * 1024
        chunks = []
        total = 0
        while True:
            part = await file.read(1024 * 1024)
            if not part:
                break
            total += len(part)
            if total > limit:
                raise HTTPException(413, f'Rendu > {MAX_REMOTE_OUTPUT_MB} Mo')
            chunks.append(part)
        if not chunks:
            raise HTTPException(400, 'Rendu vide')
        try:
            meta = json.loads(metadata_json) if metadata_json else {}
            if not isinstance(meta, dict):
                meta = {}
        except Exception:
            meta = {}
        aid = uuid.uuid4()
        name = os.path.basename(file.filename or f'AutoDirector_{aid}.mp4')[:180]
        blob = b''.join(chunks)
        with db() as c:
            c.execute("insert into assets(id,project_id,name,content_type,size,role,kind,data,metadata) values(%s,%s,%s,'video/mp4',%s,'render','render',%s,%s)", (aid, project_id, name, len(blob), blob, Jsonb(meta)))
            c.execute("update jobs set output_asset_ids=array_append(output_asset_ids,%s),updated_at=now() where id=%s and not (%s=any(output_asset_ids))", (aid, jid, aid))
        return {'ok': True, 'assetId': str(aid), 'size': len(blob)}

    async def complete(job_id: str, x: CompleteIn, authorization: Optional[str] = Header(None)):
        wid = _worker_id(authorization)
        jid = uuid.UUID(job_id)
        _lease(jid, wid)
        with db() as c:
            c.execute("update jobs set status='done',stage='complete',progress=100,message=%s,critic_score=%s,revision_count=%s,strategy=%s,updated_at=now() where id=%s", (x.message[:500], max(0, min(100, float(x.score))), max(0, int(x.revisionCount)), x.strategy[:120], jid))
            c.execute('delete from worker_leases where job_id=%s', (jid,))
        try: q().delete('autodirector:lock:' + str(jid))
        except Exception: pass
        return {'ok': True}

    async def fail(job_id: str, x: FailIn, authorization: Optional[str] = Header(None)):
        wid = _worker_id(authorization)
        jid = uuid.UUID(job_id)
        _lease(jid, wid, refresh=False)
        with db() as c:
            c.execute("update jobs set status='failed',stage='error',progress=0,message=%s,updated_at=now() where id=%s", (x.error[:500], jid))
            c.execute('delete from worker_leases where job_id=%s', (jid,))
        try: q().delete('autodirector:lock:' + str(jid))
        except Exception: pass
        return {'ok': True}

    app.add_api_route('/api/local-worker/session', create_worker_session, methods=['POST'], include_in_schema=False)
    app.add_api_route('/api/local-worker/heartbeat', heartbeat, methods=['POST'], include_in_schema=False)
    app.add_api_route('/api/local-worker/jobs/claim', claim, methods=['POST'], include_in_schema=False)
    app.add_api_route('/api/local-worker/assets/{asset_id}', asset, methods=['GET'], include_in_schema=False)
    app.add_api_route('/api/local-worker/jobs/{job_id}/progress', progress, methods=['POST'], include_in_schema=False)
    app.add_api_route('/api/local-worker/jobs/{job_id}/state', state, methods=['GET'], include_in_schema=False)
    app.add_api_route('/api/local-worker/jobs/{job_id}/output', output, methods=['POST'], include_in_schema=False)
    app.add_api_route('/api/local-worker/jobs/{job_id}/complete', complete, methods=['POST'], include_in_schema=False)
    app.add_api_route('/api/local-worker/jobs/{job_id}/fail', fail, methods=['POST'], include_in_schema=False)
