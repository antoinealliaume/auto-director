"""Pure worker routing/status diagnostics shared by runtime, status endpoint and tests."""
from __future__ import annotations

import time
from typing import Any

from .job_lifecycle import worker_compatibility


def heartbeat_age_seconds(worker: dict[str, Any] | None, *, now: int | None = None) -> int | None:
    if not worker:
        return None
    try:
        updated = int(worker.get("updatedAt"))
    except (TypeError, ValueError):
        return None
    return max(0, int(now if now is not None else time.time()) - updated)


def with_heartbeat_age(worker: dict[str, Any] | None, *, now: int | None = None) -> dict[str, Any] | None:
    if not worker:
        return None
    return {**worker, "heartbeatAgeSeconds": heartbeat_age_seconds(worker, now=now)}


def heartbeat_compatibility(worker: dict[str, Any] | None) -> dict[str, Any] | None:
    if not worker:
        return None
    return worker_compatibility(worker.get("engine"), worker.get("protocol"))


def heartbeat_compatible(worker: dict[str, Any] | None) -> bool:
    compatibility = heartbeat_compatibility(worker)
    starting = str((worker or {}).get("profile") or "").strip().lower() == "starting"
    return bool(compatibility and compatibility.get("compatible") and not starting)


def select_active_worker(local: dict[str, Any] | None, cloud: dict[str, Any] | None) -> tuple[str | None, dict[str, Any] | None, dict[str, Any] | None]:
    """Prefer a ready, compatible local worker, otherwise keep the cloud fallback active."""
    local_compatibility = heartbeat_compatibility(local)
    if local and heartbeat_compatible(local):
        return "local", local, local_compatibility
    cloud_compatibility = heartbeat_compatibility(cloud)
    if cloud:
        return "cloud", cloud, cloud_compatibility
    if local:
        return "local", local, local_compatibility
    return None, None, None


def diagnostic_state(*, active: dict[str, Any] | None, compatibility: dict[str, Any] | None,
                     queue_depth: int | None, retry_depth: int | None, current_job: dict[str, Any] | None) -> dict[str, Any]:
    queued = max(0, int(queue_depth or 0))
    delayed = max(0, int(retry_depth or 0))
    if not active:
        level = "offline" if queued or delayed else "idle"
        message = "Aucun worker actif ; les jobs restent sauvegardés." if level == "offline" else "Aucun worker actif et aucune tâche en attente."
    elif not compatibility or not compatibility.get("compatible"):
        level, message = "incompatible", "Le worker actif doit être mis à jour avant de recevoir un job."
    elif current_job:
        level, message = "busy", "Le worker traite actuellement un job."
    else:
        level, message = "ready", "Le worker est compatible et prêt."
    return {"level": level, "message": message, "queued": queued, "delayedRetries": delayed}
