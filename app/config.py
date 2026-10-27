"""Runtime configuration, read once from environment variables.

Nothing secret is hardcoded here; see .env.example for the full list.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache


def _bool(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    database_url: str
    # Shared secret Vapi sends on every webhook (header x-webhook-secret).
    # When empty, webhook auth is disabled (local dev only).
    webhook_secret: str
    # Optional API key for write endpoints (POST/PUT/DELETE). Empty = open.
    api_key: str
    seed_data: bool
    clinic_name: str
    clinic_timezone: str
    log_level: str
    # Public, browser-safe values for the dashboard's "call Ava" panel.
    # VAPI_PUBLIC_KEY is Vapi's *public* key (never the private one).
    vapi_public_key: str
    vapi_assistant_id: str
    intake_phone_number: str


def _prefixed_database_url() -> str | None:
    # Vercel's Storage integration prepends a user-chosen prefix to every
    # variable it creates, e.g. "database_DATABASE_URL" or "STORAGE_DATABASE_URL".
    for key in sorted(os.environ):
        if key.upper().endswith("_DATABASE_URL"):
            return os.environ[key]
    return None


def _database_url() -> str:
    # Vercel's Neon integration may expose POSTGRES_URL instead of DATABASE_URL.
    url = os.getenv("DATABASE_URL") or os.getenv("POSTGRES_URL") or _prefixed_database_url()
    if url:
        return url
    if os.getenv("VERCEL"):
        # A SQLite file on a serverless disk is wiped between instances, which
        # would silently lose patients. Refuse to start instead.
        raise RuntimeError("DATABASE_URL is not set; connect a Postgres database to this Vercel project")
    return "sqlite:///./data/patients.db"


@lru_cache
def get_settings() -> Settings:
    return Settings(
        database_url=_database_url(),
        webhook_secret=os.getenv("VAPI_WEBHOOK_SECRET", ""),
        api_key=os.getenv("API_KEY", ""),
        seed_data=_bool(os.getenv("SEED_DATA"), True),
        clinic_name=os.getenv("CLINIC_NAME", "Riverside Family Health"),
        clinic_timezone=os.getenv("CLINIC_TIMEZONE", "America/New_York"),
        log_level=os.getenv("LOG_LEVEL", "INFO"),
        vapi_public_key=os.getenv("VAPI_PUBLIC_KEY", ""),
        vapi_assistant_id=os.getenv("VAPI_ASSISTANT_ID", ""),
        intake_phone_number=os.getenv("INTAKE_PHONE_NUMBER", ""),
    )
