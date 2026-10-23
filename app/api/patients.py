"""/patients REST endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Header
from sqlalchemy.orm import Session

from app import validation as v
from app.api.envelope import ok, parse_query, parse_uuid
from app.config import get_settings
from app.db import get_db
from app.errors import UnauthorizedError
from app.schemas import (
    AppointmentOut,
    CallLogOut,
    PatientCreate,
    PatientOut,
    PatientUpdate,
    iso_utc,
)
from app.services import appointments as appointment_service
from app.services import calls as call_service
from app.services import patients as patient_service

router = APIRouter(prefix="/patients", tags=["patients"])


def require_api_key(x_api_key: str | None = Header(default=None)) -> None:
    """Write endpoints need X-API-Key, but only if API_KEY is configured."""
    expected = get_settings().api_key
    if expected and x_api_key != expected:
        raise UnauthorizedError("Missing or invalid X-API-Key header")


def _out(patient) -> dict:
    return PatientOut.model_validate(patient).model_dump(mode="json")


@router.get("")
def list_patients(
    last_name: str | None = None,
    date_of_birth: str | None = None,
    phone_number: str | None = None,
    db: Session = Depends(get_db),
):
    patients = patient_service.list_patients(
        db,
        last_name=parse_query("last_name", last_name, v.normalize_name),
        date_of_birth=parse_query("date_of_birth", date_of_birth, v.parse_date_of_birth),
        phone_number=parse_query("phone_number", phone_number, v.normalize_phone),
    )
    return ok([_out(p) for p in patients])


@router.get("/{patient_id}")
def get_patient(patient_id: str, db: Session = Depends(get_db)):
    return ok(_out(patient_service.get_patient(db, parse_uuid(patient_id))))


@router.post("", status_code=201, dependencies=[Depends(require_api_key)])
def create_patient(body: PatientCreate, db: Session = Depends(get_db)):
    return ok(_out(patient_service.create_patient(db, body)), status_code=201)


@router.put("/{patient_id}", dependencies=[Depends(require_api_key)])
def update_patient(patient_id: str, body: PatientUpdate, db: Session = Depends(get_db)):
    return ok(_out(patient_service.update_patient(db, parse_uuid(patient_id), body)))


@router.delete("/{patient_id}", dependencies=[Depends(require_api_key)])
def delete_patient(patient_id: str, db: Session = Depends(get_db)):
    patient = patient_service.soft_delete_patient(db, parse_uuid(patient_id))
    return ok({"patient_id": str(patient.patient_id), "deleted_at": iso_utc(patient.deleted_at)})


@router.get("/{patient_id}/calls")
def list_patient_calls(patient_id: str, db: Session = Depends(get_db)):
    pid = parse_uuid(patient_id)
    patient_service.get_patient(db, pid)
    calls = call_service.list_calls(db, patient_id=pid)
    return ok([CallLogOut.model_validate(c).model_dump(mode="json") for c in calls])


@router.get("/{patient_id}/appointments")
def list_patient_appointments(patient_id: str, db: Session = Depends(get_db)):
    pid = parse_uuid(patient_id)
    patient_service.get_patient(db, pid)
    appts = appointment_service.list_for_patient(db, pid)
    return ok([AppointmentOut.model_validate(a).model_dump(mode="json") for a in appts])
