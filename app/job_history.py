"""Presentation helpers for the existing job_events table."""
from __future__ import annotations

from typing import Iterable


def serialize_events(rows: Iterable[tuple]) -> list[dict]:
    return [
        {
            "stage": str(stage or "unknown"),
            "message": str(message or ""),
            "createdAt": created_at.isoformat(),
        }
        for stage, message, created_at in rows
    ]
