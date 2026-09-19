"""Consistent JSON logs without adding a logging dependency."""
from __future__ import annotations

import json
import logging
from contextvars import ContextVar, Token
from typing import Any


logger = logging.getLogger("auto_director")
_request_id: ContextVar[str | None] = ContextVar("auto_director_request_id", default=None)


def set_request_id(value: str | None) -> Token:
    return _request_id.set(value)


def reset_request_id(token: Token) -> None:
    _request_id.reset(token)


def log_event(event: str, *, level: int = logging.INFO, request_id: str | None = None, job_id: str | None = None, **fields: Any) -> None:
    payload = {"event": event}
    request_id = request_id or _request_id.get()
    if request_id:
        payload["request_id"] = request_id
    if job_id:
        payload["job_id"] = str(job_id)
    payload.update({key: value for key, value in fields.items() if value is not None})
    logger.log(level, json.dumps(payload, ensure_ascii=False, default=str, separators=(",", ":")))
