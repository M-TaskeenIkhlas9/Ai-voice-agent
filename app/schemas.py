"""Pydantic request/response schemas for the REST API.

Validation delegates to app/validation.py so the API and the voice agent share
one rulebook. Unknown fields are rejected (extra="forbid") to catch typos.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict, ValidationError, field_serializer, field_validator

from app import validation as v


def iso_utc(value: datetime | None) -> str | None:
    if value is None:
        return None
    # SQLite drops tzinfo; everything we store is UTC.
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def error_details(exc: ValidationError) -> dict[str, str]:
    """Flattens Pydantic errors to {field: human message} for API and voice tool responses."""
    details: dict[str, str] = {}
    for err in exc.errors():
        loc = [str(p) for p in err.get("loc", ()) if p != "body"]
        field = ".".join(loc) or "body"
        msg = err.get("msg", "is invalid").removeprefix("Value error, ")
        if err.get("type") == "missing":
            msg = "is required"
        elif err.get("type") == "extra_forbidden":
            msg = "is not a recognized field"
        details.setdefault(field, msg)
    return details


def _optional(normalizer):
    """Wraps a normalizer so None passes through (absence is handled elsewhere)."""

    def _validate(cls, value: Any) -> Any:
        return None if value is None else normalizer(value)

    return classmethod(_validate)


class _PatientFields(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    check_names = field_validator("first_name", "last_name", check_fields=False)(
        _optional(v.normalize_name)
    )
    check_dob = field_validator("date_of_birth", mode="before", check_fields=False)(
        _optional(v.parse_date_of_birth)
    )
    check_sex = field_validator("sex", check_fields=False)(_optional(v.normalize_sex))
    check_phones = field_validator(
        "phone_number", "emergency_contact_phone", check_fields=False
    )(_optional(v.normalize_phone))
    check_email = field_validator("email", check_fields=False)(_optional(v.normalize_email))
    check_addr1 = field_validator("address_line_1", check_fields=False)(
        _optional(v.normalize_address_line)
    )
    check_addr2 = field_validator("address_line_2", check_fields=False)(
        _optional(v.normalize_address_line_2)
    )
    check_city = field_validator("city", check_fields=False)(_optional(v.normalize_city))
    check_state = field_validator("state", check_fields=False)(_optional(v.normalize_state))
    check_zip = field_validator("zip_code", check_fields=False)(_optional(v.normalize_zip))
    check_insurer = field_validator("insurance_provider", check_fields=False)(
        _optional(v.normalize_short_text)
    )
    check_member = field_validator("insurance_member_id", check_fields=False)(
        _optional(v.normalize_member_id)
    )
    check_lang = field_validator("preferred_language", check_fields=False)(
        _optional(v.normalize_language)
    )
    check_ec_name = field_validator("emergency_contact_name", check_fields=False)(
        _optional(v.normalize_full_name)
    )


class PatientCreate(_PatientFields):
    first_name: str
    last_name: str
    date_of_birth: date
    sex: str
    phone_number: str
    email: str | None = None
    address_line_1: str
    address_line_2: str | None = None
    city: str
    state: str
    zip_code: str
    insurance_provider: str | None = None
    insurance_member_id: str | None = None
    preferred_language: str = "English"
    emergency_contact_name: str | None = None
    emergency_contact_phone: str | None = None


# Required columns: may be omitted from a PUT, but not explicitly nulled.
NON_NULLABLE_FIELDS = frozenset(v.REQUIRED_FIELDS) | {"preferred_language"}


class PatientUpdate(_PatientFields):
    """Partial update: every field optional; only fields present in the body change."""

    first_name: str | None = None
    last_name: str | None = None
    date_of_birth: date | None = None
    sex: str | None = None
    phone_number: str | None = None
    email: str | None = None
    address_line_1: str | None = None
    address_line_2: str | None = None
    city: str | None = None
    state: str | None = None
    zip_code: str | None = None
    insurance_provider: str | None = None
    insurance_member_id: str | None = None
    preferred_language: str | None = None
    emergency_contact_name: str | None = None
    emergency_contact_phone: str | None = None


class PatientOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    patient_id: uuid.UUID
    first_name: str
    last_name: str
    date_of_birth: date
    sex: str
    phone_number: str
    email: str | None
    address_line_1: str
    address_line_2: str | None
    city: str
    state: str
    zip_code: str
    insurance_provider: str | None
    insurance_member_id: str | None
    preferred_language: str
    emergency_contact_name: str | None
    emergency_contact_phone: str | None
    created_at: datetime
    updated_at: datetime

    @field_serializer("date_of_birth")
    def _ser_dob(self, value: date) -> str:
        return v.format_dob(value)

    @field_serializer("created_at", "updated_at")
    def _ser_ts(self, value: datetime | None) -> str | None:
        return iso_utc(value)


class CallLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    call_id: str
    patient_id: uuid.UUID | None
    caller_number: str | None
    status: str
    ended_reason: str | None
    started_at: datetime | None
    ended_at: datetime | None
    transcript: str | None
    summary: str | None
    recording_url: str | None
    collected_payload: dict | None
    created_at: datetime

    @field_serializer("started_at", "ended_at", "created_at")
    def _ser_ts(self, value: datetime | None) -> str | None:
        return iso_utc(value)


class AppointmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    appointment_id: uuid.UUID
    patient_id: uuid.UUID
    provider_name: str
    starts_at: datetime
    reason: str | None
    status: str

    @field_serializer("starts_at")
    def _ser_ts(self, value: datetime) -> str | None:
        return iso_utc(value)
