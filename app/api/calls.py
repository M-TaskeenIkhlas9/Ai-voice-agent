"""/calls: read-only view of call logs and transcripts (used by the dashboard)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.envelope import ok
from app.db import get_db
from app.schemas import CallLogOut
from app.services import calls as call_service

router = APIRouter(prefix="/calls", tags=["calls"])


@router.get("")
def list_calls(limit: int = Query(default=50, ge=1, le=500), db: Session = Depends(get_db)):
    calls = call_service.list_calls(db, limit=limit)
    return ok([CallLogOut.model_validate(c).model_dump(mode="json") for c in calls])
