import hashlib
import hmac
import json
import os
import secrets
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import psycopg
import redis
from fastapi import FastAPI, File, Form, Header, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, Response, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from psycopg.types.json import Jsonb

DATABASE_URL = os.environ["DATABASE_URL"]
REDIS_URL = os.environ["REDIS_URL"]
STUDIO_PASSWORD = os.environ.get("STUDIO_PASSWORD", "change-me-now")
E2E_PASSWORD = os.environ.get("E2E_PASSWORD", "")
TOKEN_SECRET = os.environ.get("TOKEN_SECRET", secrets.token_hex(32))
MAX_UPLOAD_MB = int(os.environ.get("MAX_UPLOAD_MB", "80"))
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
AI_MODEL = os.environ.get("AI_MODEL", "gpt-5.6-luna")
TOKEN_TTL_SECONDS = int(os.environ.get("TOKEN_TTL_SECONDS", str(30 * 24 * 3600)))
BASE_DIR = Path(__file__).resolve().parent

app = FastAPI(title="Auto Director Studio", version="8.4")
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
queue = redis.from_url(REDIS_URL, decode_responses=True)


def db():
    return psycopg.connect(DATABASE_URL)


def now():
    return datetime.now(timezone.utc)


def sign(value: str) -> str:
    return hmac.new(TOKEN_SECRET.encode(), value.encode(), hashlib.sha256).hexdigest()


def make_token() -> str:
    issued = int(now().timestamp())
    raw = f"{issued}.{secrets.token_urlsafe(30)}"
    return raw + "." + sign(raw)


def verify_token(token: str) -> bool:
    parts = token.rsplit(".", 1)
    if len(parts) != 2 or not hmac.compare_digest(sign(parts[0]), parts[1]):
        return False
    try:
        issued = int(parts[0].split(".", 1)[0])
    except Exception:
        return False
    return 0 <= int(now().timestamp()) - issued <= TOKEN_TTL_SECONDS


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
                data bytea not null,
                metadata jsonb not null default '{}'::jsonb,
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
            """
        )
        migrations = [
            "alter table projects add column if not exists description text not null default ''",
            "alter table assets add column if not exists metadata jsonb not null default '{}'::jsonb",
            "alter table jobs add column if not exists critic_score double precision",
            "alter table jobs add column if not exists revision_count int not null default 0",
            "alter table jobs add column if not exists strategy text not null default ''",
            "alter table jobs add column if not exists creative_brief jsonb not null default '{}'::jsonb",
        ]
        for sql in migrations:
            c.execute(sql)


@app.on_event("startup")
def startup():
    init_db()


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
    return {"ok": db_ok and queue_ok, "database": db_ok, "queue": queue_ok, "version": "8.4", "ai": "openai" if OPENAI_API_KEY else "local-fallback", "aiModel": AI_MODEL if OPENAI_API_KEY else None, "maxUploadMb": MAX_UPLOAD_MB}


@app.get("/health/deep")
def deep_health():
    report = {"databaseRead": False, "databaseWrite": False, "queue": False}
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
    report["ok"] = all(report[k] for k in ("databaseRead", "databaseWrite", "queue"))
    return report


class Login(BaseModel):
    password: str


@app.post("/api/login")
def login(x: Login):
    allowed = hmac.compare_digest(x.password, STUDIO_PASSWORD)
    if E2E_PASSWORD:
        allowed = allowed or hmac.compare_digest(x.password, E2E_PASSWORD)
    if not allowed:
        raise HTTPException(401, "Mot de passe incorrect")
    return {"token": make_token()}


@app.get("/api/worker/bootstrap")
def worker_bootstrap(authorization: Optional[str] = Header(None)):
    require_auth(authorization)
    payload = {
        "databaseUrl": DATABASE_URL,
        "redisUrl": REDIS_URL,
        "workerKind": "local",
        "engine": "8.4",
        "issuedAt": now().isoformat(),
    }
    return JSONResponse(payload, headers={"Cache-Control": "no-store, private", "Pragma": "no-cache"})


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
        assets = c.execute("select id,project_id,name,content_type,size,role,kind,metadata,created_at from assets order by created_at desc limit 400").fetchall()
        jobs = c.execute("select id,project_id,status,stage,progress,message,variants,output_asset_ids,critic_score,revision_count,strategy,creative_brief,created_at,updated_at from jobs order by created_at desc limit 200").fetchall()
        trends = c.execute("select id,label,source_url,notes,created_at from trends order by created_at desc limit 50").fetchall()
        feedback_count = c.execute("select count(*) from feedback").fetchone()[0]
    return {"projects": [serialize_row(x, ["id", "name", "description", "createdAt"]) for x in projects], "assets": [serialize_row(x, ["id", "projectId", "name", "contentType", "size", "role", "kind", "metadata", "createdAt"]) for x in assets], "jobs": [serialize_row(x, ["id", "projectId", "status", "stage", "progress", "message", "variants", "outputAssetIds", "criticScore", "revisionCount", "strategy", "creativeBrief", "createdAt", "updatedAt"]) for x in jobs], "trends": [serialize_row(x, ["id", "label", "sourceUrl", "notes", "createdAt"]) for x in trends], "feedbackCount": feedback_count}


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


@app.delete("/api/projects/{project_id}")
def delete_project(project_id: str, authorization: Optional[str] = Header(None)):
    require_auth(authorization)
    with db() as c:
        deleted = c.execute("delete from projects where id=%s returning id", (uuid.UUID(project_id),)).fetchone()
    if not deleted:
        raise HTTPException(404, "Projet introuvable")
    return {"ok": True}


@app.post("/api/assets")
async def upload_asset(file: UploadFile = File(...), project_id: str = Form(...), role: str = Form("source"), authorization: Optional[str] = Header(None)):
    require_auth(authorization)
    if role not in {"source", "reference", "broll", "talking_head"}:
        role = "source"
    try:
        pid = uuid.UUID(project_id)
    except Exception:
        raise HTTPException(400, "Projet invalide")
    with db() as c:
        if not c.execute("select 1 from projects where id=%s", (pid,)).fetchone():
            raise HTTPException(404, "Projet introuvable")
    chunks = []
    total = 0
    limit = MAX_UPLOAD_MB * 1024 * 1024
    while True:
        chunk = await file.read(1024 * 1024)
        if not chunk:
            break
        total += len(chunk)
        if total > limit:
            raise HTTPException(413, f"Fichier > {MAX_UPLOAD_MB} Mo")
        chunks.append(chunk)
    data = b"".join(chunks)
    if not data:
        raise HTTPException(400, "Fichier vide")
    filename = Path(file.filename or "video.mp4").name[:180]
    aid = uuid.uuid4()
    metadata = {"medal": "medal" in filename.lower(), "originalName": filename}
    with db() as c:
        c.execute("insert into assets(id,project_id,name,content_type,size,role,kind,data,metadata) values(%s,%s,%s,%s,%s,%s,'source',%s,%s)", (aid, pid, filename, file.content_type or "video/mp4", len(data), role, data, Jsonb(metadata)))
    return {"id": str(aid), "name": filename, "size": len(data), "role": role}


class RoleIn(BaseModel):
    role: str


@app.patch("/api/assets/{asset_id}/role")
def set_role(asset_id: str, x: RoleIn, authorization: Optional[str] = Header(None)):
    require_auth(authorization)
    if x.role not in {"source", "reference", "broll", "talking_head"}:
        raise HTTPException(400, "Rôle invalide")
    with db() as c:
        row = c.execute("update assets set role=%s where id=%s and kind='source' returning id", (x.role, uuid.UUID(asset_id))).fetchone()
    if not row:
        raise HTTPException(404, "Rush introuvable")
    return {"ok": True, "role": x.role}


@app.delete("/api/assets/{asset_id}")
def delete_asset(asset_id: str, authorization: Optional[str] = Header(None)):
    require_auth(authorization)
    with db() as c:
        row = c.execute("delete from assets where id=%s returning id", (uuid.UUID(asset_id),)).fetchone()
    if not row:
        raise HTTPException(404, "Fichier introuvable")
    return {"ok": True}


@app.get("/api/assets/{asset_id}/download")
def download(asset_id: str, authorization: Optional[str] = Header(None), token: Optional[str] = Query(None)):
    require_auth(authorization, token)
    with db() as c:
        row = c.execute("select name,content_type,data from assets where id=%s", (uuid.UUID(asset_id),)).fetchone()
    if not row:
        raise HTTPException(404, "Introuvable")
    return Response(bytes(row[2]), media_type=row[1], headers={"Content-Disposition": f'inline; filename="{Path(row[0]).name}"', "Cache-Control": "private, max-age=3600"})


class JobIn(BaseModel):
    projectId: str
    assetIds: list[str]
    variants: int = 1
    captions: bool = True
    voiceover: str = "auto"
    autoRevision: bool = True
    targetDuration: int = 18


@app.post("/api/jobs")
def create_job(x: JobIn, authorization: Optional[str] = Header(None)):
    require_auth(authorization)
    pid = uuid.UUID(x.projectId)
    asset_ids = list(dict.fromkeys(x.assetIds))[:30]
    if not asset_ids:
        raise HTTPException(400, "Sélectionne au moins un rush")
    with db() as c:
        if not c.execute("select 1 from projects where id=%s", (pid,)).fetchone():
            raise HTTPException(404, "Projet introuvable")
        count = c.execute("select count(*) from assets where project_id=%s and id=any(%s) and kind='source'", (pid, [uuid.UUID(a) for a in asset_ids])).fetchone()[0]
        if count != len(asset_ids):
            raise HTTPException(400, "Un ou plusieurs rushs sont invalides")
        jid = uuid.uuid4()
        settings = {"assetIds": asset_ids, "captions": bool(x.captions), "voiceover": x.voiceover if x.voiceover in {"auto", "on", "off"} else "auto", "autoRevision": bool(x.autoRevision), "targetDuration": max(8, min(35, int(x.targetDuration)))}
        c.execute("insert into jobs(id,project_id,status,stage,progress,message,variants,settings) values(%s,%s,'queued','queued',0,%s,%s,%s)", (jid, pid, "Job accepté · en attente du worker", max(1, min(3, x.variants)), Jsonb(settings)))
        c.execute("insert into job_events(job_id,stage,message) values(%s,'queued','Job créé')", (jid,))
    queue.lpush("auto_director:jobs", str(jid))
    return {"id": str(jid), "status": "queued"}


@app.post("/api/jobs/{job_id}/cancel")
def cancel_job(job_id: str, authorization: Optional[str] = Header(None)):
    require_auth(authorization)
    with db() as c:
        row = c.execute("update jobs set status='cancelled',stage='cancelled',message='Annulé',updated_at=now() where id=%s and status in ('queued','running') returning id", (uuid.UUID(job_id),)).fetchone()
    if not row:
        raise HTTPException(409, "Ce job ne peut plus être annulé")
    return {"ok": True}


@app.post("/api/jobs/{job_id}/retry")
def retry_job(job_id: str, authorization: Optional[str] = Header(None)):
    require_auth(authorization)
    jid = uuid.UUID(job_id)
    with db() as c:
        row = c.execute("update jobs set status='queued',stage='queued',progress=0,message='Relancé',updated_at=now() where id=%s and status in ('failed','cancelled') returning id", (jid,)).fetchone()
    if not row:
        raise HTTPException(409, "Ce job ne peut pas être relancé")
    queue.lpush("auto_director:jobs", str(jid))
    return {"ok": True}


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
    with db() as c:
        if not c.execute("select 1 from assets where id=%s and kind='render'", (uuid.UUID(asset_id),)).fetchone():
            raise HTTPException(404, "Rendu introuvable")
        c.execute("insert into feedback(id,asset_id,views,likes,comments,shares,completion,conversions,revenue) values(%s,%s,%s,%s,%s,%s,%s,%s,%s)", (uuid.uuid4(), uuid.UUID(asset_id), max(0, x.views), max(0, x.likes), max(0, x.comments), max(0, x.shares), max(0, min(1, x.completion)), max(0, x.conversions), max(0, x.revenue)))
    return {"ok": True}


@app.get("/api/learning")
def learning(authorization: Optional[str] = Header(None)):
    require_auth(authorization)
    with db() as c:
        totals = c.execute("select count(*),coalesce(sum(views),0),coalesce(sum(likes),0),coalesce(sum(shares),0),coalesce(avg(completion),0),coalesce(sum(conversions),0),coalesce(sum(revenue),0) from feedback").fetchone()
        top = c.execute("select a.name,coalesce(sum(f.views),0) views,coalesce(avg(f.completion),0) completion from feedback f join assets a on a.id=f.asset_id group by a.name order by views desc limit 8").fetchall()
    return {"count": totals[0], "views": totals[1], "likes": totals[2], "shares": totals[3], "completion": totals[4], "conversions": totals[5], "revenue": totals[6], "top": [{"name": x[0], "views": x[1], "completion": x[2]} for x in top]}


class TrendIn(BaseModel):
    label: str = Field(min_length=1, max_length=120)
    sourceUrl: str = Field(default="", max_length=500)
    notes: str = Field(default="", max_length=1500)


@app.post("/api/trends")
def add_trend(x: TrendIn, authorization: Optional[str] = Header(None)):
    require_auth(authorization)
    tid = uuid.uuid4()
    with db() as c:
        c.execute("insert into trends(id,label,source_url,notes) values(%s,%s,%s,%s)", (tid, x.label.strip(), x.sourceUrl.strip(), x.notes.strip()))
    return {"id": str(tid), "label": x.label.strip()}


@app.get("/api/publication/{asset_id}")
def publication_pack(asset_id: str, authorization: Optional[str] = Header(None)):
    require_auth(authorization)
    with db() as c:
        row = c.execute("select a.name,p.name,j.strategy,j.critic_score from assets a left join projects p on p.id=a.project_id left join jobs j on a.id=any(j.output_asset_ids) where a.id=%s and a.kind='render' order by j.updated_at desc limit 1", (uuid.UUID(asset_id),)).fetchone()
    if not row:
        raise HTTPException(404, "Rendu introuvable")
    filename, project, strategy, score = row
    project = project or "ce projet"
    strategy = strategy or "dynamic_scene_reveal"
    caption = f"Ce moment sur {project}… 👀 Tu aurais fait quoi ?"
    tags = ["#gaming", "#tiktokgaming", "#fyp", "#viral"]
    if "gmod" in project.lower() or "garry" in project.lower():
        tags = ["#gmod", "#garrysmod", "#darkrp", "#gaming"]
    return {"assetId": asset_id, "filename": filename, "caption": caption, "hashtags": tags, "cta": "Dis-moi ce que tu aurais fait 👇", "strategy": strategy, "score": score}
