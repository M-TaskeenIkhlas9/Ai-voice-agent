"""/appointments: the clinic schedule (read) and manual booking from the dashboard."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.envelope import ok, parse_query
from app.api.patients import require_api_key
from app.config import get_settings
from app.db import get_db
from app.schemas import AppointmentCreate, AppointmentOut
from app.services import appointments as appointment_service

router = APIRouter(prefix="/appointments", tags=["appointments"])


def _parse_iso_date(raw: str) -> date:
    try:
        return date.fromisoformat(raw)
    except ValueError as exc:
        raise ValueError("must be a date in YYYY-MM-DD format") from exc


@router.get("")
def list_appointments(
    start: str | None = None,
    days: int = Query(default=7, ge=1, le=31),
    db: Session = Depends(get_db),
):
    """Scheduled appointments from `start` (clinic-local date, default today) for `days` days."""
    tz = get_settings().clinic_timezone
    first = parse_query("start", start, _parse_iso_date) or appointment_service.clinic_today(tz)
    rows = appointment_service.list_range(db, first, days, tz)
    return ok([
        {
            **AppointmentOut.model_validate(appt).model_dump(mode="json"),
            "patient_name": f"{patient.first_name} {patient.last_name}",
        }
        for appt, patient in rows
    ])


@router.post("", status_code=201, dependencies=[Depends(require_api_key)])
def create_appointment(body: AppointmentCreate, db: Session = Depends(get_db)):
    appt = appointment_service.book_appointment(
        db,
        patient_id=body.patient_id,
        slot_start=body.slot_start,
        provider_name=body.provider_name,
        tz_name=get_settings().clinic_timezone,
        reason=body.reason,
    )
    return ok(AppointmentOut.model_validate(appt).model_dump(mode="json"), status_code=201)
