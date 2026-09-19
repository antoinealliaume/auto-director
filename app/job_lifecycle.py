"""Small, dependency-free rules shared by the API and both workers."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any


JOB_STATES = frozenset({"queued", "claimed", "running", "completed", "failed", "cancelled"})
TERMINAL_STATES = frozenset({"completed", "failed", "cancelled"})
ACTIVE_STATES = frozenset({"queued", "claimed", "running"})
LEGACY_STATE_ALIASES = {"done": "completed"}
ALLOWED_TRANSITIONS = {
    "queued": frozenset({"claimed", "cancelled"}),
    "claimed": frozenset({"running", "queued", "failed", "cancelled"}),
    "running": frozenset({"queued", "completed", "failed", "cancelled"}),
    "completed": frozenset(),
    "failed": frozenset({"queued"}),
    "cancelled": frozenset({"queued"}),
}

WORKER_PROTOCOL = 2
MIN_WORKER_ENGINE = (9, 2)
MAX_AUTOMATIC_ATTEMPTS = 2
DEFAULT_JOB_TIMEOUT_SECONDS = 45 * 60


def normalize_status(value: Any) -> str:
    status = str(value or "").strip().lower()
    return LEGACY_STATE_ALIASES.get(status, status)


def can_transition(current: Any, target: Any) -> bool:
    source = normalize_status(current)
    destination = normalize_status(target)
    return destination == source or destination in ALLOWED_TRANSITIONS.get(source, frozenset())


def claimable(status: Any) -> bool:
    """The SQL claim uses the same predicate, preventing a second claimant."""
    return normalize_status(status) == "queued"


def recoverable(status: Any, *, has_live_lease: bool, age_seconds: int, timeout_seconds: int = DEFAULT_JOB_TIMEOUT_SECONDS) -> bool:
    return normalize_status(status) in {"claimed", "running"} and not has_live_lease and age_seconds >= timeout_seconds


def parse_engine_version(value: Any) -> tuple[int, int] | None:
    try:
        parts = str(value).strip().split(".")
        return int(parts[0]), int(parts[1])
    except (TypeError, ValueError, IndexError):
        return None


def worker_compatibility(engine: Any, protocol: Any) -> dict[str, Any]:
    parsed = parse_engine_version(engine)
    try:
        actual_protocol = int(protocol)
    except (TypeError, ValueError):
        actual_protocol = 0
    compatible = bool(parsed and parsed >= MIN_WORKER_ENGINE and actual_protocol == WORKER_PROTOCOL)
    reasons: list[str] = []
    if actual_protocol != WORKER_PROTOCOL:
        reasons.append(f"protocol {actual_protocol or 'missing'} (expected {WORKER_PROTOCOL})")
    if not parsed or parsed < MIN_WORKER_ENGINE:
        reasons.append(f"engine {engine or 'missing'} (minimum {MIN_WORKER_ENGINE[0]}.{MIN_WORKER_ENGINE[1]})")
    return {
        "compatible": compatible,
        "reason": "; ".join(reasons),
        "expectedProtocol": WORKER_PROTOCOL,
        "minimumEngine": ".".join(map(str, MIN_WORKER_ENGINE)),
    }


def retry_delay_seconds(attempt: int) -> int:
    """Short, bounded exponential backoff: 15s, 30s, then 60s."""
    return min(60, 15 * (2 ** max(0, int(attempt) - 1)))


def retry_plan(settings: dict[str, Any] | None, *, now: datetime | None = None) -> dict[str, Any]:
    current = dict(settings or {})
    attempt = max(0, int(current.get("automaticAttempts") or 0)) + 1
    allowed = attempt <= MAX_AUTOMATIC_ATTEMPTS
    delay = retry_delay_seconds(attempt)
    when = (now or datetime.now(timezone.utc)) + timedelta(seconds=delay)
    current["automaticAttempts"] = attempt
    current["nextAttemptAt"] = when.isoformat() if allowed else None
    return {"allowed": allowed, "attempt": attempt, "delaySeconds": delay, "settings": current}


def deadline_exceeded(started_at: datetime, timeout_seconds: int = DEFAULT_JOB_TIMEOUT_SECONDS, *, now: datetime | None = None) -> bool:
    if started_at.tzinfo is None:
        started_at = started_at.replace(tzinfo=timezone.utc)
    return (now or datetime.now(timezone.utc)) >= started_at + timedelta(seconds=max(1, int(timeout_seconds)))
