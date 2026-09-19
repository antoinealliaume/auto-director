"""Pure worker status diagnostics shared by the status endpoint and tests."""
from __future__ import annotations

import time
from typing import Any


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
