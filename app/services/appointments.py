"""Mock first-appointment scheduling (bonus feature).

Availability is generated, not stored: weekdays, 9am-4pm hourly, for a small
fixed roster of providers, minus anything already booked. Only bookings are
persisted.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.errors import ConflictError, DomainValidationError
from app.models import Appointment
from app.services.patients import get_patient

PROVIDERS = ("Dr. Sarah Chen", "Dr. Michael Okafor")
CLINIC_HOURS = range(9, 17)  # slot start hours, local time
DAYS_AHEAD = 10


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def available_slots(
    db: Session,
    tz_name: str,
    preferred_date: date | None = None,
    limit: int = 4,
    now: datetime | None = None,
) -> list[dict]:
    tz = ZoneInfo(tz_name)
    now_local = (now or datetime.now(timezone.utc)).astimezone(tz)
    booked = {
        (a.provider_name, _as_utc(a.starts_at))
        for a in db.scalars(select(Appointment).where(Appointment.status == "scheduled"))
    }

    start_day = max(preferred_date or now_local.date(), now_local.date())
    slots: list[dict] = []
    for offset in range(DAYS_AHEAD):
        day = start_day + timedelta(days=offset)
        if day.weekday() >= 5:
            continue
        for hour in CLINIC_HOURS:
            local_start = datetime.combine(day, time(hour), tzinfo=tz)
            # Need at least two hours' notice.
            if local_start < now_local + timedelta(hours=2):
                continue
            for provider in PROVIDERS:
                start_utc = local_start.astimezone(timezone.utc)
                if (provider, start_utc) in booked:
                    continue
                slots.append({
                    "slot_start": local_start.isoformat(),
                    "provider_name": provider,
                    "spoken": local_start.strftime("%A, %B %-d at %-I:%M %p").replace(":00 ", " "),
                })
                if len(slots) >= limit:
                    return slots
    return slots


def book_appointment(
    db: Session,
    patient_id: uuid.UUID,
    slot_start: str,
    provider_name: str,
    tz_name: str,
    reason: str | None = None,
) -> Appointment:
    get_patient(db, patient_id)  # 404s for unknown/deleted patients
    if provider_name not in PROVIDERS:
        raise DomainValidationError("Unknown provider", {"provider_name": f"must be one of {PROVIDERS}"})
    try:
        start = datetime.fromisoformat(slot_start)
    except ValueError as exc:
        raise DomainValidationError("Invalid slot", {"slot_start": "must be an ISO-8601 datetime"}) from exc
    if start.tzinfo is None:
        start = start.replace(tzinfo=ZoneInfo(tz_name))
    start_utc = start.astimezone(timezone.utc)
    if start_utc <= datetime.now(timezone.utc):
        raise DomainValidationError("Slot is in the past", {"slot_start": "must be in the future"})

    appt = Appointment(
        patient_id=patient_id, provider_name=provider_name, starts_at=start_utc, reason=reason
    )
    db.add(appt)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise ConflictError("That time was just booked by someone else") from exc
    db.refresh(appt)
    return appt


def list_for_patient(db: Session, patient_id: uuid.UUID) -> list[Appointment]:
    stmt = (
        select(Appointment)
        .where(Appointment.patient_id == patient_id)
        .order_by(Appointment.starts_at)
    )
    return list(db.scalars(stmt))
