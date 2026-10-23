"""Domain exceptions raised by the service layer, mapped to HTTP codes in app/main.py."""

from __future__ import annotations


class NotFoundError(Exception):
    """Requested record does not exist (or is soft-deleted). -> 404"""


class DomainValidationError(Exception):
    """Business-rule violation not caught by schema validation. -> 422"""

    def __init__(self, message: str, details: dict[str, str] | None = None):
        super().__init__(message)
        self.details = details or {}


class ConflictError(Exception):
    """Write conflicts with existing state (e.g. slot already booked). -> 409"""


class UnauthorizedError(Exception):
    """Missing/invalid API key or webhook secret. -> 401"""
