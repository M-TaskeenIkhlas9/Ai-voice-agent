"""Tools the voice agent can call, and their server-side handlers.

Each tool has two halves kept side by side:
  * a JSON-schema definition the LLM sees (in ``TOOL_SCHEMAS``), and
  * a handler that runs the shared service layer (in ``HANDLERS``).

Handlers never raise: every outcome (success, validation error, DB outage) is
returned as a small dict whose wording tells the LLM what to say next. This is
how "the database write failed" becomes a spoken apology instead of silence.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from typing import Any

from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app import validation as v
from app.config import get_settings
from app.errors import ConflictError, DomainValidationError, NotFoundError
from app.schemas import PatientCreate, PatientUpdate, error_details
from app.services import appointments as appointment_service
from app.services import calls as call_service
from app.services import patients as patient_service

log = logging.getLogger("voice.tools")


@dataclass(frozen=True)
class CallContext:
    call_id: str | None
    caller_number: str | None


# --------------------------------------------------------------------------- #
# Schemas shown to the LLM
# --------------------------------------------------------------------------- #

_FIELD_PROPS: dict[str, dict[str, Any]] = {
    "first_name": {"type": "string", "description": "Patient first name, as spelled by the caller."},
    "last_name": {"type": "string", "description": "Patient last name, as spelled by the caller."},
    "date_of_birth": {"type": "string", "description": "Date of birth in MM/DD/YYYY format."},
    "sex": {"type": "string", "enum": list(v.SEX_VALUES)},
    "phone_number": {"type": "string", "description": "10-digit U.S. phone number, digits only."},
    "email": {"type": "string", "description": "Email address (optional)."},
    "address_line_1": {"type": "string", "description": "Street address, e.g. '123 Main St'."},
    "address_line_2": {"type": "string", "description": "Apartment, suite or unit (optional)."},
    "city": {"type": "string"},
    "state": {"type": "string", "description": "2-letter U.S. state abbreviation, e.g. 'TX'."},
    "zip_code": {"type": "string", "description": "5-digit ZIP or ZIP+4 (12345-6789)."},
    "insurance_provider": {"type": "string", "description": "Insurance company name (optional)."},
    "insurance_member_id": {"type": "string", "description": "Insurance member/subscriber ID (optional)."},
    "preferred_language": {"type": "string", "description": "Preferred language (optional, default English)."},
    "emergency_contact_name": {"type": "string", "description": "Emergency contact full name (optional)."},
    "emergency_contact_phone": {"type": "string", "description": "Emergency contact 10-digit phone (optional)."},
}


def _function(name: str, description: str, properties: dict, required: list[str]) -> dict:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {"type": "object", "properties": properties, "required": required},
        },
    }


TOOL_SCHEMAS: list[dict] = [
    _function(
        "lookup_patient_by_phone",
        "Check whether a patient record already exists for a phone number. "
        "Call this as soon as the caller gives their phone number.",
        {"phone_number": _FIELD_PROPS["phone_number"]},
        ["phone_number"],
    ),
    _function(
        "validate_patient_info",
        "Validate and normalize collected patient fields before reading them back. "
        "Pass every field collected so far. Returns per-field errors and any missing required fields.",
        _FIELD_PROPS,
        [],
    ),
    _function(
        "save_patient",
        "Create the new patient record. Only call after the caller has confirmed the read-back.",
        _FIELD_PROPS,
        list(v.REQUIRED_FIELDS),
    ),
    _function(
        "update_patient",
        "Update an existing patient's record after identity was verified and the caller confirmed "
        "the changes. Pass patient_id plus only the fields that changed.",
        {"patient_id": {"type": "string", "description": "patient_id from lookup_patient_by_phone."},
         **_FIELD_PROPS},
        ["patient_id"],
    ),
    _function(
        "get_appointment_slots",
        "Get a few upcoming open appointment times for a first visit.",
        {"preferred_date": {"type": "string",
                            "description": "Optional earliest date the caller wants, MM/DD/YYYY."}},
        [],
    ),
    _function(
        "book_appointment",
        "Book one of the slots returned by get_appointment_slots for a registered patient.",
        {
            "patient_id": {"type": "string", "description": "patient_id returned by save_patient."},
            "slot_start": {"type": "string", "description": "slot_start exactly as returned."},
            "provider_name": {"type": "string", "description": "provider_name exactly as returned."},
            "reason": {"type": "string", "description": "Short reason for the visit (optional)."},
        },
        ["patient_id", "slot_start", "provider_name"],
    ),
]


# --------------------------------------------------------------------------- #
# Handlers
# --------------------------------------------------------------------------- #

_SYSTEM_ERROR = {
    "success": False,
    "error": "system_error",
    "message": "A technical problem prevented this from being saved. Apologize to the caller "
               "and try once more; if it fails again, tell them it could not be saved.",
}
_VALIDATION_MESSAGE = "Nothing was saved. Ask the caller to correct these fields, one at a time."


def _patient_fields(args: dict[str, Any]) -> dict[str, Any]:
    """Keeps only known patient fields with non-blank values."""
    return {
        k: val for k, val in args.items()
        if k in v.FIELD_NORMALIZERS and val is not None and str(val).strip() != ""
    }


def _parse_patient_id(raw: Any) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(raw))
    except ValueError:
        return None


def lookup_patient_by_phone(db: Session, args: dict, ctx: CallContext) -> dict:
    try:
        phone = v.normalize_phone(args.get("phone_number"))
    except ValueError as exc:
        return {"found": False, "valid_phone": False, "error": f"phone number {exc}"}
    matches = patient_service.list_patients(db, phone_number=phone)
    return {
        "found": bool(matches),
        "valid_phone": True,
        # Name is shared so the agent can ask "is this you?"; DOB is only used
        # by the agent to verify identity, never read aloud.
        "patients": [
            {
                "patient_id": str(p.patient_id),
                "first_name": p.first_name,
                "last_name": p.last_name,
                "date_of_birth": v.format_dob(p.date_of_birth),
            }
            for p in matches[:3]
        ],
    }


def validate_patient_info(db: Session, args: dict, ctx: CallContext) -> dict:
    normalized, errors = v.validate_fields(args)
    missing = [f for f in v.REQUIRED_FIELDS if f not in normalized and f not in errors]
    return {
        "valid": not errors and not missing,
        "errors": errors,
        "missing_required_fields": missing,
        "normalized": normalized,
    }


def save_patient(db: Session, args: dict, ctx: CallContext) -> dict:
    payload = _patient_fields(args)
    log.info("save_patient payload", extra={"call_id": ctx.call_id, "payload": payload})
    try:
        data = PatientCreate(**payload)
    except ValidationError as exc:
        return {"success": False, "error": "validation_error", "errors": error_details(exc),
                "message": _VALIDATION_MESSAGE}
    try:
        patient = patient_service.create_patient(db, data)
    except SQLAlchemyError:
        db.rollback()
        log.exception("save_patient failed", extra={"call_id": ctx.call_id})
        return _SYSTEM_ERROR
    _link_call(db, ctx, patient.patient_id, data.model_dump(mode="json"))
    log.info("patient created", extra={"call_id": ctx.call_id, "patient_id": str(patient.patient_id)})
    return {"success": True, "patient_id": str(patient.patient_id), "first_name": patient.first_name}


def update_patient(db: Session, args: dict, ctx: CallContext) -> dict:
    patient_id = _parse_patient_id(args.get("patient_id"))
    if patient_id is None:
        return {"success": False, "error": "invalid_patient_id",
                "message": "Use the patient_id returned by lookup_patient_by_phone."}
    payload = _patient_fields(args)
    log.info("update_patient payload",
             extra={"call_id": ctx.call_id, "patient_id": str(patient_id), "payload": payload})
    try:
        data = PatientUpdate(**payload)
        patient = patient_service.update_patient(db, patient_id, data)
    except ValidationError as exc:
        return {"success": False, "error": "validation_error", "errors": error_details(exc),
                "message": _VALIDATION_MESSAGE}
    except NotFoundError:
        return {"success": False, "error": "not_found",
                "message": "That record no longer exists. Offer to register them as a new patient."}
    except SQLAlchemyError:
        db.rollback()
        log.exception("update_patient failed", extra={"call_id": ctx.call_id})
        return _SYSTEM_ERROR
    _link_call(db, ctx, patient.patient_id, {"update": data.model_dump(mode="json", exclude_unset=True)})
    return {"success": True, "patient_id": str(patient.patient_id), "first_name": patient.first_name}


def get_appointment_slots(db: Session, args: dict, ctx: CallContext) -> dict:
    preferred = None
    if args.get("preferred_date"):
        try:
            # Same date formats as DOB, but future dates are the point here.
            preferred = v.parse_date_of_birth(args["preferred_date"], today=date.max)
        except ValueError:
            preferred = None
    slots = appointment_service.available_slots(db, get_settings().clinic_timezone, preferred)
    if not slots:
        return {"slots": [], "message": "No openings soon. Tell the caller the clinic will call to schedule."}
    return {"slots": slots}


def book_appointment(db: Session, args: dict, ctx: CallContext) -> dict:
    patient_id = _parse_patient_id(args.get("patient_id"))
    if patient_id is None:
        return {"success": False, "error": "invalid_patient_id",
                "message": "Use the patient_id returned by save_patient."}
    try:
        appt = appointment_service.book_appointment(
            db,
            patient_id=patient_id,
            slot_start=str(args.get("slot_start", "")),
            provider_name=str(args.get("provider_name", "")),
            tz_name=get_settings().clinic_timezone,
            reason=args.get("reason"),
        )
    except ConflictError:
        return {"success": False, "error": "slot_taken",
                "message": "That time was just taken. Call get_appointment_slots and offer new times."}
    except (DomainValidationError, NotFoundError) as exc:
        return {"success": False, "error": "invalid_request", "message": str(exc)}
    except SQLAlchemyError:
        db.rollback()
        log.exception("book_appointment failed", extra={"call_id": ctx.call_id})
        return _SYSTEM_ERROR
    log.info("appointment booked",
             extra={"call_id": ctx.call_id, "appointment_id": str(appt.appointment_id)})
    return {"success": True, "appointment_id": str(appt.appointment_id),
            "provider_name": appt.provider_name, "slot_start": args.get("slot_start")}


def _link_call(db: Session, ctx: CallContext, patient_id: uuid.UUID, payload: dict) -> None:
    """Attach the patient to this call's log row. Best-effort: never fails the save."""
    if not ctx.call_id:
        return
    try:
        call_service.upsert_call(
            db, ctx.call_id, patient_id=patient_id, caller_number=ctx.caller_number,
            collected_payload=payload,
        )
    except SQLAlchemyError:
        db.rollback()
        log.exception("failed to link call to patient", extra={"call_id": ctx.call_id})


HANDLERS: dict[str, Callable[[Session, dict, CallContext], dict]] = {
    "lookup_patient_by_phone": lookup_patient_by_phone,
    "validate_patient_info": validate_patient_info,
    "save_patient": save_patient,
    "update_patient": update_patient,
    "get_appointment_slots": get_appointment_slots,
    "book_appointment": book_appointment,
}


def run_tool(db: Session, name: str, args: dict, ctx: CallContext) -> dict:
    handler = HANDLERS.get(name)
    if handler is None:
        return {"error": f"unknown tool '{name}'"}
    try:
        return handler(db, args, ctx)
    except Exception:  # last line of defence: the caller must never hear silence
        db.rollback()
        log.exception("tool crashed", extra={"call_id": ctx.call_id, "tool": name})
        return _SYSTEM_ERROR
