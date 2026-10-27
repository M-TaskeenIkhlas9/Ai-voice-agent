"""Database engine/session setup.

PostgreSQL in production (DATABASE_URL from Railway/Render), SQLite file as a
zero-config local fallback. Tables are created on startup with
``create_all`` -- see README "Trade-offs" for why there is no Alembic yet.
"""

from __future__ import annotations

import os
from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError, ProgrammingError
from sqlalchemy.pool import NullPool
from sqlalchemy.orm import DeclarativeBase, sessionmaker, Session


class Base(DeclarativeBase):
    pass


def _normalize_url(url: str) -> str:
    # Hosting providers hand out postgres:// URLs; SQLAlchemy wants an explicit driver.
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    if url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://"):]
    return url


def _make_engine(url: str) -> Engine:
    url = _normalize_url(url)
    if url.startswith("sqlite"):
        path = url.split("///", 1)[-1]
        if path and path != ":memory:":
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        return create_engine(url, connect_args={"check_same_thread": False})
    if os.getenv("VERCEL"):
        # Serverless instances freeze between requests, so pooled connections
        # go stale; open one per request (Neon's pooler absorbs the cost).
        return create_engine(url, poolclass=NullPool)
    return create_engine(url, pool_pre_ping=True, pool_size=5, max_overflow=5)


engine: Engine | None = None
SessionLocal = sessionmaker(autoflush=False, expire_on_commit=False)


def init_engine(url: str) -> Engine:
    global engine
    engine = _make_engine(url)
    SessionLocal.configure(bind=engine)
    return engine


def create_tables() -> None:
    from app import models  # noqa: F401  (registers models on Base.metadata)

    assert engine is not None, "init_engine() must be called first"
    try:
        Base.metadata.create_all(engine)
    except (IntegrityError, ProgrammingError):
        # Two cold serverless instances raced to create the same tables;
        # the other one won, so the schema now exists. Re-check once.
        Base.metadata.create_all(engine)


def get_db() -> Iterator[Session]:
    """FastAPI dependency: one session per request."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
