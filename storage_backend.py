# -*- coding: utf-8 -*-
"""Private media storage for Auto Director.

The application keeps PostgreSQL as the source of truth for metadata and job state.
Video payloads can live either in PostgreSQL (legacy/fallback) or in any private
S3-compatible object store (AWS S3, Cloudflare R2, MinIO, Spaces, ...).

Object storage is deliberately opt-in: if the required environment variables are
missing, every helper transparently falls back to PostgreSQL bytea storage.
"""
from __future__ import annotations

import hashlib
import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Iterator, Optional


REQUIRED_ENV = (
    "OBJECT_STORAGE_BUCKET",
    "OBJECT_STORAGE_ACCESS_KEY",
    "OBJECT_STORAGE_SECRET_KEY",
)


def configured() -> bool:
    return all(os.environ.get(k, "").strip() for k in REQUIRED_ENV)


def backend_name() -> str:
    return "s3" if configured() else "database"


def _safe_name(name: str) -> str:
    value = Path(name or "asset.bin").name
    value = re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("._")
    return (value or "asset.bin")[:140]


def object_key(project_id, asset_id, kind: str, filename: str) -> str:
    safe_kind = re.sub(r"[^a-z0-9_-]+", "-", str(kind or "asset").lower()).strip("-") or "asset"
    return f"projects/{project_id}/{safe_kind}/{asset_id}/{_safe_name(filename)}"


@lru_cache(maxsize=1)
def _client():
    if not configured():
        raise RuntimeError("Object storage is not configured")
    import boto3
    from botocore.config import Config

    endpoint = os.environ.get("OBJECT_STORAGE_ENDPOINT", "").strip() or None
    region = os.environ.get("OBJECT_STORAGE_REGION", "auto").strip() or "auto"
    style = os.environ.get("OBJECT_STORAGE_ADDRESSING_STYLE", "auto").strip().lower()
    if style not in {"auto", "path", "virtual"}:
        style = "auto"
    return boto3.client(
        "s3",
        endpoint_url=endpoint,
        region_name=region,
        aws_access_key_id=os.environ["OBJECT_STORAGE_ACCESS_KEY"],
        aws_secret_access_key=os.environ["OBJECT_STORAGE_SECRET_KEY"],
        config=Config(signature_version="s3v4", s3={"addressing_style": style}, retries={"max_attempts": 4, "mode": "standard"}),
    )


def bucket() -> str:
    value = os.environ.get("OBJECT_STORAGE_BUCKET", "").strip()
    if not value:
        raise RuntimeError("OBJECT_STORAGE_BUCKET missing")
    return value


def put_bytes(key: str, payload: bytes, content_type: str = "application/octet-stream") -> None:
    _client().put_object(Bucket=bucket(), Key=key, Body=payload, ContentType=content_type or "application/octet-stream")


def put_file(key: str, path: Path, content_type: str = "application/octet-stream") -> None:
    with Path(path).open("rb") as fh:
        _client().upload_fileobj(fh, bucket(), key, ExtraArgs={"ContentType": content_type or "application/octet-stream"})


def get_bytes(key: str) -> bytes:
    obj = _client().get_object(Bucket=bucket(), Key=key)
    try:
        return obj["Body"].read()
    finally:
        try:
            obj["Body"].close()
        except Exception:
            pass


def get_range(key: str, start: int, end: int) -> bytes:
    start = max(0, int(start)); end = max(start, int(end))
    obj = _client().get_object(Bucket=bucket(), Key=key, Range=f"bytes={start}-{end}")
    try:
        return obj["Body"].read()
    finally:
        try:
            obj["Body"].close()
        except Exception:
            pass


def download_to(key: str, destination: Path) -> None:
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("wb") as fh:
        _client().download_fileobj(bucket(), key, fh)


def delete(key: Optional[str]) -> None:
    if key and configured():
        _client().delete_object(Bucket=bucket(), Key=key)


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as fh:
        while True:
            chunk = fh.read(chunk_size)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def read_asset(storage_key: Optional[str], data) -> bytes:
    if storage_key:
        if not configured():
            raise RuntimeError("Asset stored externally but object storage is not configured")
        return get_bytes(storage_key)
    if data is None:
        raise RuntimeError("Asset payload is missing")
    return bytes(data)


def materialize_asset(storage_key: Optional[str], data, destination: Path) -> None:
    if storage_key:
        if not configured():
            raise RuntimeError("Asset stored externally but object storage is not configured")
        download_to(storage_key, destination)
        return
    if data is None:
        raise RuntimeError("Asset payload is missing")
    Path(destination).write_bytes(bytes(data))


def persist_bytes(project_id, asset_id, kind: str, filename: str, payload: bytes, content_type: str):
    """Return (database_payload, storage_key, backend, checksum)."""
    checksum = sha256_bytes(payload)
    if not configured():
        return payload, None, "database", checksum
    key = object_key(project_id, asset_id, kind, filename)
    put_bytes(key, payload, content_type)
    return None, key, "s3", checksum


def persist_file(project_id, asset_id, kind: str, filename: str, path: Path, content_type: str):
    """Return (database_payload, storage_key, backend, checksum)."""
    checksum = sha256_file(path)
    if not configured():
        return Path(path).read_bytes(), None, "database", checksum
    key = object_key(project_id, asset_id, kind, filename)
    put_file(key, path, content_type)
    return None, key, "s3", checksum
