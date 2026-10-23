"""Consistent response envelope: {"data": ..., "error": null} / {"data": null, "error": {...}}."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi.responses import JSONResponse

from app.errors import DomainValidationError


def ok(data: Any, status_code: int = 200) -> JSONResponse:
    return JSONResponse(status_code=status_code, content={"data": data, "error": None})


def fail(
    status_code: int, code: str, message: str, details: dict[str, str] | None = None
) -> JSONResponse:
    error: dict[str, Any] = {"code": code, "message": message}
    if details:
        error["details"] = details
    return JSONResponse(status_code=status_code, content={"data": None, "error": error})


class BadRequestError(Exception):
    """Malformed request (bad UUID, unparseable JSON). -> 400"""


def parse_uuid(raw: str) -> uuid.UUID:
    try:
        return uuid.UUID(raw)
    except ValueError as exc:
        raise BadRequestError(f"'{raw}' is not a valid patient_id (UUID expected)") from exc


def parse_query(field: str, raw: str | None, normalizer) -> Any:
    """Validates a query-string filter with the same rules as the body field."""
    if raw is None or not raw.strip():
        return None
    try:
        return normalizer(raw)
    except ValueError as exc:
        raise DomainValidationError(f"Invalid query parameter '{field}'", {field: str(exc)}) from exc
