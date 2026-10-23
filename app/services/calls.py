"""Call log persistence: transcripts, summaries and the payload each call submitted."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import CallLog


def upsert_call(db: Session, call_id: str, **fields: Any) -> CallLog:
    """Creates the call row on first sight, then fills in whatever is known.

    Vapi events arrive in no guaranteed order (a tool call can land before the
    status-update), so every writer goes through this idempotent upsert.
    ``None`` values never overwrite data that is already stored.
    """
    call = db.get(CallLog, call_id)
    if call is None:
        call = CallLog(call_id=call_id)
        db.add(call)
    for key, value in fields.items():
        if value is not None:
            setattr(call, key, value)
    db.commit()
    db.refresh(call)
    return call


def list_calls(db: Session, patient_id: uuid.UUID | None = None, limit: int = 100) -> list[CallLog]:
    stmt = select(CallLog)
    if patient_id is not None:
        stmt = stmt.where(CallLog.patient_id == patient_id)
    stmt = stmt.order_by(CallLog.created_at.desc()).limit(limit)
    return list(db.scalars(stmt))


def parse_vapi_time(value: Any) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
