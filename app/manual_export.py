"""Helpers for explicit, user-initiated video exports."""
from __future__ import annotations

import re
import unicodedata
from datetime import datetime


def export_filename(project: str, variant: int, created_at: datetime | None = None) -> str:
    """Build a readable cross-platform filename without changing stored assets."""
    ascii_name = unicodedata.normalize("NFKD", project or "Auto Director").encode("ascii", "ignore").decode()
    slug = re.sub(r"[^A-Za-z0-9]+", "-", ascii_name).strip("-").lower()[:64] or "auto-director"
    stamp = (created_at or datetime.now()).strftime("%Y%m%d")
    return f"{slug}_{stamp}_v{max(1, int(variant or 1))}.mp4"


def export_manifest(*, asset_id: str, project: str, source_name: str, size: int, created_at: datetime,
                    job_id: str | None, score: float | None, strategy: str | None, variant: int,
                    checksum_sha256: str | None = None, metadata: dict | None = None) -> dict:
    details = metadata if isinstance(metadata, dict) else {}
    resolution = details.get("resolution")
    if not isinstance(resolution, list) or len(resolution) != 2:
        resolution = None
    return {
        "assetId": asset_id,
        "filename": export_filename(project, variant, created_at),
        "sourceName": source_name,
        "sizeBytes": int(size or 0),
        "createdAt": created_at.isoformat(),
        "jobId": job_id,
        "score": score,
        "strategy": strategy or "",
        "durationSeconds": details.get("duration"),
        "resolution": resolution,
        "fps": details.get("fps"),
        "checksumSha256": checksum_sha256 or details.get("checksumSha256") or None,
        "integrity": "checksum-available" if checksum_sha256 or details.get("checksumSha256") else "not-recorded",
        "status": "ready_for_manual_publication",
        "publicationMode": "manual-only",
        "downloadEndpoint": f"/api/assets/{asset_id}/download",
    }
