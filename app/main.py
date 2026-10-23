"""FastAPI application: REST API + Vapi webhook + dashboard in one service.

Run locally:  uvicorn app.main:app --reload
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app import db as database
from app.api import calls as calls_api
from app.api import patients as patients_api
from app.api.envelope import BadRequestError, fail, ok
from app.config import get_settings
from app.errors import ConflictError, DomainValidationError, NotFoundError, UnauthorizedError
from app.logging_setup import configure_logging
from app.schemas import error_details
from app.seed import seed_if_empty
from app.voice import webhook as vapi_webhook

log = logging.getLogger("app")
STATIC_DIR = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    configure_logging(settings.log_level)
    database.init_engine(settings.database_url)
    database.create_tables()
    if settings.seed_data:
        with database.SessionLocal() as session:
            seed_if_empty(session)
    log.info("startup complete", extra={"db": settings.database_url.split("://", 1)[0]})
    yield


app = FastAPI(
    title="Patient Registration Voice Agent API",
    version="1.0.0",
    description="REST API backing a Vapi voice agent that registers new patients by phone.",
    lifespan=lifespan,
)
app.include_router(patients_api.router)
app.include_router(calls_api.router)
app.include_router(vapi_webhook.router)


# ---------------------------------------------------------------- error mapping
# Every error leaves the API in the same envelope: {"data": null, "error": {...}}


@app.exception_handler(RequestValidationError)
async def _validation_error(request: Request, exc: RequestValidationError):
    errors = exc.errors()
    if any(e.get("type") in {"json_invalid", "json_type"} for e in errors) or any(
        e.get("type") == "missing" and tuple(e.get("loc", ())) == ("body",) for e in errors
    ):
        return fail(400, "bad_request", "Request body must be a valid JSON object")
    details = error_details(exc)
    return fail(422, "validation_error", "One or more fields are invalid", details)


@app.exception_handler(DomainValidationError)
async def _domain_validation_error(request: Request, exc: DomainValidationError):
    return fail(422, "validation_error", str(exc), exc.details)


@app.exception_handler(BadRequestError)
async def _bad_request(request: Request, exc: BadRequestError):
    return fail(400, "bad_request", str(exc))


@app.exception_handler(UnauthorizedError)
async def _unauthorized(request: Request, exc: UnauthorizedError):
    return fail(401, "unauthorized", str(exc))


@app.exception_handler(NotFoundError)
async def _not_found(request: Request, exc: NotFoundError):
    return fail(404, "not_found", str(exc))


@app.exception_handler(ConflictError)
async def _conflict(request: Request, exc: ConflictError):
    return fail(409, "conflict", str(exc))


@app.exception_handler(StarletteHTTPException)
async def _http_error(request: Request, exc: StarletteHTTPException):
    return fail(exc.status_code, "http_error", str(exc.detail))


@app.exception_handler(SQLAlchemyError)
async def _db_error(request: Request, exc: SQLAlchemyError):
    log.exception("database error", extra={"path": request.url.path})
    return fail(500, "database_error", "A database error occurred. Please try again.")


@app.exception_handler(Exception)
async def _unhandled(request: Request, exc: Exception):
    log.exception("unhandled error", extra={"path": request.url.path})
    return fail(500, "internal_error", "An unexpected error occurred.")


# ---------------------------------------------------------------- misc routes


@app.get("/health", tags=["meta"])
def health():
    with database.SessionLocal() as session:
        session.execute(text("SELECT 1"))
    return ok({"status": "ok"})


@app.get("/", include_in_schema=False)
@app.get("/dashboard", include_in_schema=False)
def dashboard():
    return FileResponse(STATIC_DIR / "dashboard.html")
