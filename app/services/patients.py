"""Patient CRUD with soft delete."""

from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.errors import DomainValidationError, NotFoundError
from app.models import Patient, utcnow
from app.schemas import NON_NULLABLE_FIELDS, PatientCreate, PatientUpdate


def create_patient(db: Session, data: PatientCreate) -> Patient:
    patient = Patient(**data.model_dump())
    db.add(patient)
    db.commit()
    db.refresh(patient)
    return patient


def get_patient(db: Session, patient_id: uuid.UUID) -> Patient:
    patient = db.get(Patient, patient_id)
    if patient is None or patient.deleted_at is not None:
        raise NotFoundError(f"Patient {patient_id} not found")
    return patient


def list_patients(
    db: Session,
    *,
    last_name: str | None = None,
    date_of_birth: date | None = None,
    phone_number: str | None = None,
) -> list[Patient]:
    stmt = select(Patient).where(Patient.deleted_at.is_(None))
    if last_name:
        stmt = stmt.where(func.lower(Patient.last_name) == last_name.strip().lower())
    if date_of_birth:
        stmt = stmt.where(Patient.date_of_birth == date_of_birth)
    if phone_number:
        stmt = stmt.where(Patient.phone_number == phone_number)
    stmt = stmt.order_by(Patient.created_at.desc())
    return list(db.scalars(stmt))


def update_patient(db: Session, patient_id: uuid.UUID, data: PatientUpdate) -> Patient:
    patient = get_patient(db, patient_id)
    changes = data.model_dump(exclude_unset=True)
    nulled = {k: f"{k} is required and cannot be null" for k, val in changes.items()
              if val is None and k in NON_NULLABLE_FIELDS}
    if nulled:
        raise DomainValidationError("Required fields cannot be cleared", nulled)
    for field, value in changes.items():
        setattr(patient, field, value)
    if changes:
        patient.updated_at = utcnow()
    db.commit()
    db.refresh(patient)
    return patient


def soft_delete_patient(db: Session, patient_id: uuid.UUID) -> Patient:
    patient = get_patient(db, patient_id)
    patient.deleted_at = utcnow()
    db.commit()
    db.refresh(patient)
    return patient
