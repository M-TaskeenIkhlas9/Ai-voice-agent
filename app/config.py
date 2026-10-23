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


@lru_cache
def get_settings() -> Settings:
    return Settings(
        database_url=os.getenv("DATABASE_URL", "sqlite:///./data/patients.db"),
        webhook_secret=os.getenv("VAPI_WEBHOOK_SECRET", ""),
        api_key=os.getenv("API_KEY", ""),
        seed_data=_bool(os.getenv("SEED_DATA"), True),
        clinic_name=os.getenv("CLINIC_NAME", "Riverside Family Health"),
        clinic_timezone=os.getenv("CLINIC_TIMEZONE", "America/New_York"),
        log_level=os.getenv("LOG_LEVEL", "INFO"),
    )
