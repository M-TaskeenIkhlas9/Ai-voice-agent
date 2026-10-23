"""Vapi server webhook: tool calls in, tool results out; call lifecycle events logged.

Vapi POSTs every server message to one URL. We care about three:
  * ``tool-calls``         -> run tools, return {"results": [...]} synchronously
  * ``status-update``      -> record that a call started / ended
  * ``end-of-call-report`` -> store transcript + summary (also fires when the
                              caller hangs up mid-registration, so dropped
                              calls are still visible on the dashboard)
"""

from __future__ import annotations

import hmac
import json
import logging
from typing import Any

from fastapi import APIRouter, Body, Depends, Header
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.errors import UnauthorizedError
from app.services import calls as call_service
from app.voice.tools import CallContext, run_tool

log = logging.getLogger("voice.webhook")
router = APIRouter(prefix="/vapi", tags=["voice"])


def verify_secret(
    x_webhook_secret: str | None = Header(default=None),
    x_vapi_secret: str | None = Header(default=None),
) -> None:
    expected = get_settings().webhook_secret
    if not expected:
        return
    provided = x_webhook_secret or x_vapi_secret or ""
    if not hmac.compare_digest(provided, expected):
        raise UnauthorizedError("Invalid webhook secret")


def _context(message: dict) -> CallContext:
    call = message.get("call") or {}
    customer = call.get("customer") or message.get("customer") or {}
    return CallContext(call_id=call.get("id"), caller_number=customer.get("number"))


def _parse_args(raw: Any) -> dict:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


@router.post("/webhook", dependencies=[Depends(verify_secret)])
def vapi_webhook(payload: dict[str, Any] = Body(...), db: Session = Depends(get_db)):
    message = payload.get("message") or {}
    msg_type = message.get("type")
    ctx = _context(message)

    if msg_type == "tool-calls":
        return {"results": _handle_tool_calls(db, message, ctx)}

    if msg_type == "function-call":  # legacy Vapi format
        fn = message.get("functionCall") or {}
        result = run_tool(db, fn.get("name", ""), _parse_args(fn.get("parameters")), ctx)
        return {"result": json.dumps(result)}

    try:
        if msg_type == "status-update":
            _record_status(db, message, ctx)
        elif msg_type == "end-of-call-report":
            _record_end_of_call(db, message, ctx)
    except SQLAlchemyError:
        # Logging a call must never break the call itself.
        db.rollback()
        log.exception("failed to persist call event", extra={"call_id": ctx.call_id})
    return {"ok": True}


def _handle_tool_calls(db: Session, message: dict, ctx: CallContext) -> list[dict]:
    results = []
    for call in message.get("toolCallList") or message.get("toolCalls") or []:
        fn = call.get("function") or {}
        name = fn.get("name") or call.get("name", "")
        args = _parse_args(fn.get("arguments", call.get("arguments")))
        log.info("tool call", extra={"call_id": ctx.call_id, "tool": name, "tool_args": args})
        result = run_tool(db, name, args, ctx)
        log.info("tool result", extra={"call_id": ctx.call_id, "tool": name, "result": result})
        results.append({"toolCallId": call.get("id"), "result": json.dumps(result)})
    return results


def _record_status(db: Session, message: dict, ctx: CallContext) -> None:
    if not ctx.call_id:
        return
    status = message.get("status")
    log.info("call status", extra={"call_id": ctx.call_id, "status": status})
    fields: dict[str, Any] = {"caller_number": ctx.caller_number, "status": status}
    if status == "in-progress":
        fields["started_at"] = call_service.parse_vapi_time((message.get("call") or {}).get("startedAt"))
    call_service.upsert_call(db, ctx.call_id, **fields)


def _record_end_of_call(db: Session, message: dict, ctx: CallContext) -> None:
    if not ctx.call_id:
        return
    artifact = message.get("artifact") or {}
    analysis = message.get("analysis") or {}
    transcript = message.get("transcript") or artifact.get("transcript")
    summary = message.get("summary") or analysis.get("summary")
    ended_reason = message.get("endedReason")
    call_service.upsert_call(
        db,
        ctx.call_id,
        caller_number=ctx.caller_number,
        status="ended",
        ended_reason=ended_reason,
        started_at=call_service.parse_vapi_time(message.get("startedAt")),
        ended_at=call_service.parse_vapi_time(message.get("endedAt")),
        transcript=transcript,
        summary=summary,
        recording_url=message.get("recordingUrl") or artifact.get("recordingUrl"),
    )
    log.info(
        "call ended",
        extra={"call_id": ctx.call_id, "ended_reason": ended_reason, "summary": summary},
    )
