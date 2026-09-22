# -*- coding: utf-8 -*-
import os
import tempfile
import uuid
from pathlib import Path
from typing import Optional

import psycopg
from fastapi import File, Form, Header, HTTPException, Query, UploadFile
from fastapi.responses import JSONResponse, Response
from psycopg.types.json import Jsonb

import storage_backend as media_store
from storage_schema import ensure_storage_schema


def _bounded_env_int(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(maximum, value))


DATABASE_URL = os.environ.get('DATABASE_URL', '')
MAX_UPLOAD_MB = _bounded_env_int('MAX_UPLOAD_MB', 80, 10, 500)


def db():
    return psycopg.connect(DATABASE_URL)


def require_studio(authorization=None, token=None):
    from .main import require_auth
    require_auth(authorization, token)


def _delete_keys(keys):
    for key in keys:
        if key:
            try:
                media_store.delete(key)
            except Exception as exc:
                raise HTTPException(503, 'Stockage média temporairement indisponible') from exc


def attach(app):
    async def upload_asset(file: UploadFile = File(...), project_id: str = Form(...), role: str = Form('source'), authorization: Optional[str] = Header(None)):
        require_studio(authorization)
        if role not in {'source', 'reference', 'broll', 'talking_head'}:
            role = 'source'
        try:
            pid = uuid.UUID(project_id)
        except Exception:
            raise HTTPException(400, 'Projet invalide')
        with db() as c:
            ensure_storage_schema(c)
            if not c.execute('select 1 from projects where id=%s', (pid,)).fetchone():
                raise HTTPException(404, 'Projet introuvable')

        filename = Path(file.filename or 'video.mp4').name[:180]
        content_type = file.content_type or 'video/mp4'
        aid = uuid.uuid4(); limit = MAX_UPLOAD_MB * 1024 * 1024; total = 0
        tmp_path = None; storage_key = None
        try:
            with tempfile.NamedTemporaryFile(prefix='ad_upload_', suffix=Path(filename).suffix or '.bin', delete=False) as tmp:
                tmp_path = Path(tmp.name)
                while True:
                    chunk = await file.read(1024 * 1024)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > limit:
                        raise HTTPException(413, f'Fichier > {MAX_UPLOAD_MB} Mo')
                    tmp.write(chunk)
            if total <= 0:
                raise HTTPException(400, 'Fichier vide')

            data, storage_key, backend, checksum = media_store.persist_file(pid, aid, 'source', filename, tmp_path, content_type)
            metadata = {
                'medal': 'medal' in filename.lower(),
                'originalName': filename,
                'storageBackend': backend,
                'checksumSha256': checksum,
            }
            try:
                with db() as c:
                    ensure_storage_schema(c)
                    c.execute(
                        "insert into assets(id,project_id,name,content_type,size,role,kind,data,metadata,storage_key,storage_backend,checksum_sha256) values(%s,%s,%s,%s,%s,%s,'source',%s,%s,%s,%s,%s)",
                        (aid, pid, filename, content_type, total, role, data, Jsonb(metadata), storage_key, backend, checksum),
                    )
            except Exception:
                if storage_key:
                    try: media_store.delete(storage_key)
                    except Exception: pass
                raise
            return {'id': str(aid), 'name': filename, 'size': total, 'role': role, 'storage': backend}
        finally:
            if tmp_path:
                try: tmp_path.unlink(missing_ok=True)
                except Exception: pass

    async def delete_asset(asset_id: str, authorization: Optional[str] = Header(None)):
        require_studio(authorization)
        try: aid = uuid.UUID(asset_id)
        except Exception: raise HTTPException(400, 'Fichier invalide')
        with db() as c:
            ensure_storage_schema(c)
            row = c.execute('select storage_key from assets where id=%s', (aid,)).fetchone()
        if not row:
            raise HTTPException(404, 'Fichier introuvable')
        _delete_keys([row[0]])
        with db() as c:
            deleted = c.execute('delete from assets where id=%s returning id', (aid,)).fetchone()
        if not deleted:
            raise HTTPException(404, 'Fichier introuvable')
        return {'ok': True}

    async def delete_project(project_id: str, authorization: Optional[str] = Header(None)):
        require_studio(authorization)
        try: pid = uuid.UUID(project_id)
        except Exception: raise HTTPException(400, 'Projet invalide')
        with db() as c:
            ensure_storage_schema(c)
            rows = c.execute('select storage_key from assets where project_id=%s and storage_key is not null', (pid,)).fetchall()
            exists = c.execute('select 1 from projects where id=%s', (pid,)).fetchone()
        if not exists:
            raise HTTPException(404, 'Projet introuvable')
        _delete_keys([x[0] for x in rows])
        with db() as c:
            c.execute('delete from projects where id=%s', (pid,))
        return {'ok': True}

    async def download(asset_id: str, authorization: Optional[str] = Header(None), token: Optional[str] = Query(None)):
        require_studio(authorization, token)
        try: aid = uuid.UUID(asset_id)
        except Exception: raise HTTPException(400, 'Fichier invalide')
        with db() as c:
            ensure_storage_schema(c)
            row = c.execute('select name,content_type,data,storage_key from assets where id=%s', (aid,)).fetchone()
        if not row:
            raise HTTPException(404, 'Introuvable')
        try:
            payload = media_store.read_asset(row[3], row[2])
        except Exception as exc:
            raise HTTPException(503, 'Média temporairement indisponible') from exc
        return Response(payload, media_type=row[1] or 'application/octet-stream', headers={'Content-Disposition': f'inline; filename="{Path(row[0]).name}"', 'Cache-Control': 'private, max-age=300'})

    async def status(authorization: Optional[str] = Header(None)):
        require_studio(authorization)
        with db() as c:
            ensure_storage_schema(c)
            stats = c.execute("select count(*),coalesce(sum(size),0),count(*) filter(where storage_key is not null),coalesce(sum(size) filter(where storage_key is not null),0) from assets").fetchone()
        return JSONResponse({
            'mode': media_store.backend_name(),
            'externalConfigured': media_store.configured(),
            'assets': int(stats[0]),
            'bytes': int(stats[1]),
            'externalAssets': int(stats[2]),
            'externalBytes': int(stats[3]),
        }, headers={'Cache-Control': 'no-store'})

    # Attached before app.main defines its legacy routes, so these hardened handlers win.
    app.add_api_route('/api/assets', upload_asset, methods=['POST'], include_in_schema=False)
    app.add_api_route('/api/assets/{asset_id}', delete_asset, methods=['DELETE'], include_in_schema=False)
    app.add_api_route('/api/projects/{project_id}', delete_project, methods=['DELETE'], include_in_schema=False)
    app.add_api_route('/api/assets/{asset_id}/download', download, methods=['GET'], include_in_schema=False)
    app.add_api_route('/api/storage/status', status, methods=['GET'], include_in_schema=False)
