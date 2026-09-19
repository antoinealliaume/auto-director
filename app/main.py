# -*- coding: utf-8 -*-
"""Auto Director Studio API.

V9.2 keeps PostgreSQL as the durable source of truth, Redis as the volatile
queue/coordination layer, and attaches each production feature explicitly.
"""
from contextlib import asynccontextmanager
import hashlib
import hmac
import os
import secrets
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, Optional

import psycopg
import redis
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from psycopg.types.json import Jsonb

import storage_backend as media_store
from storage_schema import ensure_storage_schema
from .job_history import serialize_events
from .job_lifecycle import normalize_status
from .manual_export import export_manifest
from .structured_logging import log_event, reset_request_id, set_request_id

APP_VERSION = "9.3.0"
ENGINE_VERSION = "9.2"
DATABASE_URL = os.environ["DATABASE_URL"]
REDIS_URL = os.environ["REDIS_URL"]
STUDIO_PASSWORD = os.environ.get("STUDIO_PASSWORD", "").strip()
E2E_PASSWORD = os.environ.get("E2E_PASSWORD", "").strip()
_TOKEN_SECRET_ENV = os.environ.get("TOKEN_SECRET", "").strip()
TOKEN_SECRET = _TOKEN_SECRET_ENV or secrets.token_hex(32)
TOKEN_TTL_SECONDS = max(3600, min(30 * 24 * 3600, int(os.environ.get("TOKEN_TTL_SECONDS", str(7 * 24 * 3600)))))
MAX_UPLOAD_MB = max(10, min(500, int(os.environ.get("MAX_UPLOAD_MB", "80"))))
BASE_DIR = Path(__file__).resolve().parent
QUEUE_KEY = "auto_director:jobs"
RELEASE_COMMIT = os.environ.get("RENDER_GIT_COMMIT", "").strip()

queue = redis.from_url(REDIS_URL, decode_responses=True)


def db():
    return psycopg.connect(DATABASE_URL)


def now():
    return datetime.now(timezone.utc)


def parse_uuid(value: str, label: str = "Identifiant") -> uuid.UUID:
    try:
        return uuid.UUID(str(value))
    except Exception as exc:
        raise HTTPException(400, f"{label} invalide") from exc


def sign(value: str) -> str:
    return hmac.new(TOKEN_SECRET.encode(), value.encode(), hashlib.sha256).hexdigest()


def make_token() -> str:
    issued = int(now().timestamp())
    raw = f"{issued}.{secrets.token_urlsafe(30)}"
    return raw + "." + sign(raw)


def verify_token(token: str) -> bool:
    parts = (token or "").rsplit(".", 1)
    if len(parts) != 2 or not hmac.compare_digest(sign(parts[0]), parts[1]):
        return False
    try:
        issued = int(parts[0].split(".", 1)[0])
    except Exception:
        return False
    age = int(now().timestamp()) - issued
    return 0 <= age <= TOKEN_TTL_SECONDS


def require_auth(authorization: Optional[str] = None, token: Optional[str] = None):
    value = token or (authorization[7:] if authorization and authorization.startswith("Bearer ") else "")
    if not value or not verify_token(value):
        raise HTTPException(401, "Session invalide ou expirée")


def init_db():
    with db() as c:
        c.execute(
            """
            create table if not exists projects(
                id uuid primary key,
                name text not null,
                description text not null default '',
                created_at timestamptz not null default now()
            );
            create table if not exists assets(
                id uuid primary key,
                project_id uuid references projects(id) on delete cascade,
                name text not null,
                content_type text not null,
                size bigint not null,
                role text not null default 'source',
                kind text not null default 'source',
                data bytea,
                metadata jsonb not null default '{}'::jsonb,
                storage_key text,
                storage_backend text not null default 'database',
                checksum_sha256 text,
                created_at timestamptz not null default now()
            );
            create table if not exists jobs(
                id uuid primary key,
                project_id uuid references projects(id) on delete cascade,
                status text not null,
                stage text not null default 'queued',
                progress int not null default 0,
                message text not null default '',
                variants int not null default 1,
                settings jsonb not null default '{}'::jsonb,
                output_asset_ids uuid[] not null default '{}',
                critic_score double precision,
                revision_count int not null default 0,
                strategy text not null default '',
                creative_brief jsonb not null default '{}'::jsonb,
                created_at timestamptz not null default now(),
                updated_at timestamptz not null default now()
            );
            create table if not exists feedback(
                id uuid primary key,
                asset_id uuid references assets(id) on delete cascade,
                views bigint default 0,
                likes bigint default 0,
                comments bigint default 0,
                shares bigint default 0,
                completion double precision default 0,
                conversions bigint default 0,
                revenue double precision default 0,
                created_at timestamptz not null default now()
            );
            create table if not exists trends(
                id uuid primary key,
                label text not null,
                source_url text not null default '',
                notes text not null default '',
                created_at timestamptz not null default now()
            );
            create table if not exists job_events(
                id bigserial primary key,
                job_id uuid references jobs(id) on delete cascade,
                stage text not null,
                message text not null,
                created_at timestamptz not null default now()
            );
            create table if not exists worker_leases(
                job_id uuid primary key references jobs(id) on delete cascade,
                worker_id text not null,
                lease_expires timestamptz not null,
                updated_at timestamptz not null default now()
            );
            """
        )
        migrations = [
            "alter table projects add column if not exists description text not null default ''",
            "alter table assets add column if not exists metadata jsonb not null default '{}'::jsonb",
            "alter table assets add column if not exists storage_key text",
            "alter table assets add column if not exists storage_backend text not null default 'database'",
            "alter table assets add column if not exists checksum_sha256 text",
            "alter table assets alter column data drop not null",
            "alter table jobs add column if not exists critic_score double precision",
            "alter table jobs add column if not exists revision_count int not null default 0",
            "alter table jobs add column if not exists strategy text not null default ''",
            "alter table jobs add column if not exists creative_brief jsonb not null default '{}'::jsonb",
            "alter table trends add column if not exists source_url text not null default ''",
        ]
        for sql in migrations:
            c.execute(sql)
        c.execute(
            """with ranked as (
                select id,row_number() over(partition by asset_id order by created_at desc,id::text desc) rn
                from feedback where asset_id is not null
            ) delete from feedback where id in (select id from ranked where rn>1)"""
        )
        c.execute("create unique index if not exists uq_feedback_asset on feedback(asset_id)")
        c.execute("create index if not exists idx_jobs_status_created on jobs(status,created_at)")
        c.execute("create index if not exists idx_assets_project_kind on assets(project_id,kind,created_at)")
        c.execute("create index if not exists idx_worker_leases_expiry on worker_leases(lease_expires)")
        ensure_storage_schema(c)


@asynccontextmanager
async def lifespan(_app):
    init_db()
    yield


app = FastAPI(title="Auto Director Studio", version=APP_VERSION, lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")


@app.middleware("http")
async def request_context(request: Request, call_next):
    request_id = (request.headers.get("x-request-id") or uuid.uuid4().hex)[:80]
    request_token = set_request_id(request_id)
    try:
        response = await call_next(request)
    except Exception:
        log_event("request.failed", request_id=request_id, method=request.method, path=request.url.path)
        raise
    else:
        response.headers["X-Request-ID"] = request_id
        log_event("request.completed", request_id=request_id, method=request.method, path=request.url.path, status=response.status_code)
        return response
    finally:
        reset_request_id(request_token)


@app.get("/", response_class=HTMLResponse)
def index():
    return FileResponse(BASE_DIR / "static" / "index.html")


@app.get("/health")
def health():
    db_ok = queue_ok = False
    try:
        with db() as c:
            c.execute("select 1")
            db_ok = True
    except Exception:
        pass
    try:
        queue_ok = bool(queue.ping())
    except Exception:
        pass
    config_ok = bool(STUDIO_PASSWORD and _TOKEN_SECRET_ENV)
    return {
        "ok": db_ok and queue_ok and config_ok,
        "database": db_ok,
        "queue": queue_ok,
        "configuration": config_ok,
        "version": APP_VERSION,
        "engine": ENGINE_VERSION,
        "releaseCommit": RELEASE_COMMIT[:12] or None,
        "environment": "render" if os.environ.get("RENDER") == "true" else "local",
        "publicationMode": "manual-only",
        "ai": "director-v9.2-style",
        "maxUploadMb": MAX_UPLOAD_MB,
    }


@app.get("/health/deep")
def deep_health():
    report = {"databaseRead": False, "databaseWrite": False, "queue": False, "configuration": bool(STUDIO_PASSWORD and _TOKEN_SECRET_ENV)}
    try:
        with db() as c:
            c.execute("select 1")
            report["databaseRead"] = True
            c.execute("create temporary table _ad_health(x int)")
            c.execute("insert into _ad_health values (1)")
            report["databaseWrite"] = c.execute("select count(*) from _ad_health").fetchone()[0] == 1
    except Exception as exc:
        report["databaseError"] = str(exc)[:240]
    try:
        report["queue"] = bool(queue.ping())
    except Exception as exc:
        report["queueError"] = str(exc)[:240]
    report["ok"] = all(report[k] for k in ("databaseRead", "databaseWrite", "queue", "configuration"))
    return report


class Login(BaseModel):
    password: str = Field(min_length=1, max_length=500)


@app.post("/api/login")
def login(x: Login):
    if not STUDIO_PASSWORD:
        raise HTTPException(503, "Mot de passe Studio non configuré")
    allowed = hmac.compare_digest(x.password, STUDIO_PASSWORD)
    if E2E_PASSWORD:
        allowed = allowed or hmac.compare_digest(x.password, E2E_PASSWORD)
    if not allowed:
        raise HTTPException(401, "Mot de passe incorrect")
    return {"token": make_token(), "expiresIn": TOKEN_TTL_SECONDS, "version": APP_VERSION}


def serialize_row(row, keys):
    out = {}
    for k, v in zip(keys, row):
        if isinstance(v, uuid.UUID):
            v = str(v)
        elif isinstance(v, list) and v and isinstance(v[0], uuid.UUID):
            v = [str(x) for x in v]
        elif hasattr(v, "isoformat"):
            v = v.isoformat()
        out[k] = v
    return out


@app.get("/api/dashboard")
def dashboard(authorization: Optional[str] = Header(None)):
    require_auth(authorization)
    with db() as c:
        projects = c.execute("select id,name,description,created_at from projects order by created_at desc").fetchall()
        assets = c.execute("select id,project_id,name,content_type,size,role,kind,metadata,created_at from assets order by created_at desc limit 500").fetchall()
        jobs = c.execute("select id,project_id,status,stage,progress,message,variants,output_asset_ids,critic_score,revision_count,strategy,creative_brief,created_at,updated_at from jobs order by created_at desc limit 150").fetchall()
        trends = c.execute("select id,label,source_url,notes,created_at from trends order by created_at desc limit 80").fetchall()
        feedback_count = c.execute("select count(*) from feedback").fetchone()[0]
    return {
        "version": APP_VERSION,
        "releaseCommit": RELEASE_COMMIT[:12] or None,
        "publicationMode": "manual-only",
        "projects": [serialize_row(x, ["id", "name", "description", "createdAt"]) for x in projects],
        "assets": [serialize_row(x, ["id", "projectId", "name", "contentType", "size", "role", "kind", "metadata", "createdAt"]) for x in assets],
        "jobs": [
            {**serialize_row(x, ["id", "projectId", "status", "stage", "progress", "message", "variants", "outputAssetIds", "criticScore", "revisionCount", "strategy", "creativeBrief", "createdAt", "updatedAt"]), "status": normalize_status(x[2])}
            for x in jobs
        ],
        "trends": [serialize_row(x, ["id", "label", "sourceUrl", "notes", "createdAt"]) for x in trends],
        "feedbackCount": feedback_count,
    }


class ProjectIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=500)


@app.post("/api/projects")
def create_project(x: ProjectIn, authorization: Optional[str] = Header(None)):
    require_auth(authorization)
    name = " ".join(x.name.split()).strip()
    if not name:
        raise HTTPException(400, "Le nom du projet est requis")
    pid = uuid.uuid4()
    with db() as c:
        c.execute("insert into projects(id,name,description) values(%s,%s,%s)", (pid, name, x.description.strip()))
    return {"id": str(pid), "name": name, "description": x.description.strip()}


class RoleIn(BaseModel):
    role: str


@app.patch("/api/assets/{asset_id}/role")
def set_role(asset_id: str, x: RoleIn, authorization: Optional[str] = Header(None)):
    require_auth(authorization)
    if x.role not in {"source", "reference", "broll", "talking_head"}:
        raise HTTPException(400, "Rôle invalide")
    aid = parse_uuid(asset_id, "Rush")
    with db() as c:
        row = c.execute("update assets set role=%s where id=%s and kind='source' returning id", (x.role, aid)).fetchone()
    if not row:
        raise HTTPException(404, "Rush introuvable")
    return {"ok": True, "role": x.role}


class JobIn(BaseModel):
    projectId: str
    assetIds: list[str]
    variants: int = 1
    captions: bool = True
    voiceover: Literal["auto", "on", "off"] = "auto"
    autoRevision: bool = True
    targetDuration: int = 18
    directorMode: Literal["auto", "story", "funny", "highlight", "fast", "clean"] = "auto"
    editIntensity: Literal["soft", "balanced", "aggressive"] = "balanced"
    hookStyle: Literal["auto", "curiosity", "payoff", "direct"] = "auto"
    visualStyle: Literal["auto", "viral", "cinematic", "kinetic", "clean", "retro", "glitch", "meme", "dreamy"] = "auto"


@app.post("/api/jobs")
def create_job(x: JobIn, authorization: Optional[str] = Header(None)):
    require_auth(authorization)
    pid = parse_uuid(x.projectId, "Projet")
    raw_ids = list(dict.fromkeys(str(a) for a in x.assetIds))[:30]
    if not raw_ids:
        raise HTTPException(400, "Sélectionne au moins un rush")
    ids = [parse_uuid(a, "Rush") for a in raw_ids]
    with db() as c:
        if not c.execute("select 1 from projects where id=%s", (pid,)).fetchone():
            raise HTTPException(404, "Projet introuvable")
        valid = c.execute(
            "select id from assets where project_id=%s and id=any(%s) and kind='source' and role in ('source','broll','talking_head')",
            (pid, ids),
        ).fetchall()
        if len(valid) != len(ids):
            raise HTTPException(400, "La sélection contient une référence ou un rush invalide")
        jid = uuid.uuid4()
        settings = {
            "assetIds": [str(a) for a in ids],
            "captions": bool(x.captions),
            "voiceover": x.voiceover,
            "autoRevision": bool(x.autoRevision),
            "targetDuration": max(8, min(35, int(x.targetDuration))),
            "directorMode": x.directorMode,
            "editIntensity": x.editIntensity,
            "hookStyle": x.hookStyle,
            "visualStyle": x.visualStyle,
            "automaticAttempts": 0,
            "publicationMode": "manual-only",
        }
        c.execute(
            "insert into jobs(id,project_id,status,stage,progress,message,variants,settings) values(%s,%s,'queued','queued',0,%s,%s,%s)",
            (jid, pid, "Job accepté · en attente du worker", max(1, min(3, x.variants)), Jsonb(settings)),
        )
        c.execute("insert into job_events(job_id,stage,message) values(%s,'queued','Job créé')", (jid,))
    queue_signalled = False
    try:
        queue.lpush(QUEUE_KEY, str(jid))
        queue_signalled = True
    except Exception:
        pass
    log_event("job.queued", job_id=str(jid), queue_signalled=queue_signalled)
    return {"id": str(jid), "status": "queued", "durable": True, "queueSignalled": queue_signalled, "publicationMode": "manual-only"}


def _clear_runtime_job_state(jid: uuid.UUID):
    try:
        queue.lrem(QUEUE_KEY, 0, str(jid))
        queue.delete("autodirector:lock:" + str(jid))
    except Exception:
        pass
    with db() as c:
        c.execute("delete from worker_leases where job_id=%s", (jid,))


def _delete_job_outputs(jid: uuid.UUID):
    with db() as c:
        row = c.execute("select output_asset_ids from jobs where id=%s", (jid,)).fetchone()
        ids = list(row[0] or []) if row else []
        storage_rows = c.execute("select id,storage_key from assets where id=any(%s)", (ids,)).fetchall() if ids else []
    for _, key in storage_rows:
        if key:
            try:
                media_store.delete(key)
            except Exception:
                pass
    if ids:
        with db() as c:
            c.execute("delete from assets where id=any(%s)", (ids,))


@app.post("/api/jobs/{job_id}/cancel")
def cancel_job(job_id: str, authorization: Optional[str] = Header(None)):
    require_auth(authorization)
    jid = parse_uuid(job_id, "Job")
    with db() as c:
        row = c.execute(
            "update jobs set status='cancelled',stage='cancelled',message='Annulé',updated_at=now() where id=%s and status in ('queued','claimed','running') returning id",
            (jid,),
        ).fetchone()
    if not row:
        raise HTTPException(409, "Ce job ne peut plus être annulé")
    _clear_runtime_job_state(jid)
    log_event("job.cancelled", job_id=str(jid))
    return {"ok": True}


@app.post("/api/jobs/{job_id}/retry")
def retry_job(job_id: str, authorization: Optional[str] = Header(None)):
    require_auth(authorization)
    jid = parse_uuid(job_id, "Job")
    with db() as c:
        row = c.execute("select status from jobs where id=%s", (jid,)).fetchone()
    if not row:
        raise HTTPException(404, "Job introuvable")
    if row[0] not in {"failed", "cancelled"}:
        raise HTTPException(409, "Ce job ne peut pas être relancé")
    _clear_runtime_job_state(jid)
    _delete_job_outputs(jid)
    with db() as c:
        c.execute(
            """update jobs set status='queued',stage='queued',progress=0,message='Relancé manuellement',
               output_asset_ids='{}',critic_score=0,revision_count=0,strategy='',creative_brief='{}'::jsonb,
               settings=jsonb_set(settings-'nextAttemptAt','{automaticAttempts}','0'::jsonb,true),updated_at=now()
               where id=%s""",
            (jid,),
        )
        c.execute("insert into job_events(job_id,stage,message) values(%s,'queued','Job relancé')", (jid,))
    try:
        queue.lpush(QUEUE_KEY, str(jid))
    except Exception:
        pass
    log_event("job.retry.manual", job_id=str(jid))
    return {"ok": True}


@app.get("/api/jobs/{job_id}/events")
def job_events(job_id: str, authorization: Optional[str] = Header(None)):
    """Return a bounded, chronological timeline for one job."""
    require_auth(authorization)
    jid = parse_uuid(job_id, "Job")
    with db() as c:
        job = c.execute("select status,stage,progress,updated_at from jobs where id=%s", (jid,)).fetchone()
        if not job:
            raise HTTPException(404, "Job introuvable")
        rows = c.execute(
            "select stage,message,created_at from job_events where job_id=%s order by created_at asc,id asc limit 200",
            (jid,),
        ).fetchall()
    return {
        "jobId": str(jid),
        "status": normalize_status(job[0]),
        "stage": job[1],
        "progress": job[2],
        "updatedAt": job[3].isoformat(),
        "events": serialize_events(rows),
    }


class FeedbackIn(BaseModel):
    views: int = 0
    likes: int = 0
    comments: int = 0
    shares: int = 0
    completion: float = 0
    conversions: int = 0
    revenue: float = 0


@app.post("/api/feedback/{asset_id}")
def feedback(asset_id: str, x: FeedbackIn, authorization: Optional[str] = Header(None)):
    require_auth(authorization)
    aid = parse_uuid(asset_id, "Rendu")
    with db() as c:
        if not c.execute("select 1 from assets where id=%s and kind='render'", (aid,)).fetchone():
            raise HTTPException(404, "Rendu introuvable")
        c.execute(
            """insert into feedback(id,asset_id,views,likes,comments,shares,completion,conversions,revenue)
               values(%s,%s,%s,%s,%s,%s,%s,%s,%s)
               on conflict(asset_id) do update set views=excluded.views,likes=excluded.likes,comments=excluded.comments,
               shares=excluded.shares,completion=excluded.completion,conversions=excluded.conversions,revenue=excluded.revenue,created_at=now()""",
            (
                uuid.uuid4(), aid, max(0, x.views), max(0, x.likes), max(0, x.comments), max(0, x.shares),
                max(0, min(1, x.completion)), max(0, x.conversions), max(0, x.revenue),
            ),
        )
    return {"ok": True}


@app.get("/api/learning")
def learning(authorization: Optional[str] = Header(None)):
    require_auth(authorization)
    with db() as c:
        totals = c.execute("select count(*),coalesce(sum(views),0),coalesce(sum(likes),0),coalesce(sum(shares),0),coalesce(avg(completion),0),coalesce(sum(conversions),0),coalesce(sum(revenue),0) from feedback").fetchone()
        top = c.execute("select a.name,coalesce(f.views,0),coalesce(f.completion,0) from feedback f join assets a on a.id=f.asset_id order by f.views desc limit 8").fetchall()
    return {
        "count": totals[0], "views": totals[1], "likes": totals[2], "shares": totals[3], "completion": totals[4],
        "conversions": totals[5], "revenue": totals[6],
        "top": [{"name": x[0], "views": x[1], "completion": x[2]} for x in top],
    }


class TrendIn(BaseModel):
    label: str = Field(min_length=1, max_length=120)
    sourceUrl: str = Field(default="", max_length=500)
    notes: str = Field(default="", max_length=1500)


@app.post("/api/trends")
def add_trend(x: TrendIn, authorization: Optional[str] = Header(None)):
    require_auth(authorization)
    label = " ".join(x.label.split()).strip()
    if not label:
        raise HTTPException(400, "Le nom de la tendance est requis")
    tid = uuid.uuid4()
    with db() as c:
        c.execute("insert into trends(id,label,source_url,notes) values(%s,%s,%s,%s)", (tid, label, x.sourceUrl.strip(), x.notes.strip()))
    return {"id": str(tid), "label": label}


@app.get("/api/publication/{asset_id}")
def publication_pack(asset_id: str, authorization: Optional[str] = Header(None)):
    require_auth(authorization)
    aid = parse_uuid(asset_id, "Rendu")
    with db() as c:
        row = c.execute(
            "select a.name,p.name,j.strategy,j.critic_score from assets a left join projects p on p.id=a.project_id left join jobs j on a.id=any(j.output_asset_ids) where a.id=%s and a.kind='render' order by j.updated_at desc nulls last limit 1",
            (aid,),
        ).fetchone()
    if not row:
        raise HTTPException(404, "Rendu introuvable")
    filename, project, strategy, score = row
    project = project or "ce projet"
    strategy = strategy or "dynamic_scene_reveal"
    caption = f"Ce moment sur {project}… 👀 Tu aurais fait quoi ?"
    tags = ["#gaming", "#tiktokgaming", "#fyp", "#viral"]
    if "gmod" in project.lower() or "garry" in project.lower():
        tags = ["#gmod", "#garrysmod", "#darkrp", "#gaming"]
    return {
        "assetId": str(aid), "filename": filename, "caption": caption, "hashtags": tags,
        "cta": "Dis-moi ce que tu aurais fait 👇", "strategy": strategy, "score": score,
    }


@app.get("/api/exports/{asset_id}")
def manual_export(asset_id: str, authorization: Optional[str] = Header(None)):
    """Describe an export without initiating any platform publication."""
    require_auth(authorization)
    aid = parse_uuid(asset_id, "Rendu")
    with db() as c:
        row = c.execute(
            """select a.name,a.size,a.created_at,coalesce(p.name,'Auto Director'),j.id,j.critic_score,j.strategy,
                      coalesce(array_position(j.output_asset_ids,a.id),1),a.checksum_sha256,a.metadata
               from assets a
               left join projects p on p.id=a.project_id
               left join jobs j on a.id=any(j.output_asset_ids)
               where a.id=%s and a.kind='render'
               order by j.updated_at desc nulls last limit 1""",
            (aid,),
        ).fetchone()
    if not row:
        raise HTTPException(404, "Rendu introuvable")
    name, size, created_at, project, job_id, score, strategy, variant, checksum, metadata = row
    return export_manifest(
        asset_id=str(aid), project=project, source_name=name, size=size, created_at=created_at,
        job_id=str(job_id) if job_id else None, score=score, strategy=strategy, variant=variant,
        checksum_sha256=checksum, metadata=metadata,
    )


from .security import attach as attach_security
from .worker_status import attach as attach_worker_status
from .local_worker_api2 import attach as attach_local_worker_api
from .media_api import attach as attach_media_api
from .storage_api import attach as attach_storage_api
from .tiktok_oauth import attach as attach_tiktok_oauth
from .tiktok_posting import attach as attach_tiktok_posting
from .publication_api import attach as attach_publication_api

attach_security(app)
attach_worker_status(app)
attach_local_worker_api(app)
attach_media_api(app)
attach_storage_api(app)
attach_tiktok_oauth(app)
attach_tiktok_posting(app)
attach_publication_api(app)
