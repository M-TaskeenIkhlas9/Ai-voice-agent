"""Simulates the HTTP requests Vapi sends during a call."""

import json

from sqlalchemy.exc import OperationalError

from app.config import Settings, get_settings
from tests.conftest import VALID_PATIENT


def tool_call(client, name, args, call_id="call-123", headers=None):
    body = {
        "message": {
            "type": "tool-calls",
            "call": {"id": call_id, "customer": {"number": "+15125550198"}},
            "toolCallList": [
                {"id": "tc-1", "type": "function", "function": {"name": name, "arguments": args}}
            ],
        }
    }
    res = client.post("/vapi/webhook", json=body, headers=headers or {})
    assert res.status_code == 200, res.text
    result = res.json()["results"][0]
    assert result["toolCallId"] == "tc-1"
    return json.loads(result["result"])


def test_save_patient_persists_via_service_layer(client):
    result = tool_call(client, "save_patient", VALID_PATIENT)
    assert result["success"] is True
    assert result["first_name"] == "Jane"

    listed = client.get("/patients").json()["data"]
    assert [p["patient_id"] for p in listed] == [result["patient_id"]]

    calls = client.get(f"/patients/{result['patient_id']}/calls").json()["data"]
    assert calls[0]["call_id"] == "call-123"
    assert calls[0]["collected_payload"]["last_name"] == "Davis"


def test_save_patient_accepts_json_string_arguments(client):
    result = tool_call(client, "save_patient", json.dumps(VALID_PATIENT))
    assert result["success"] is True


def test_save_patient_returns_field_errors_instead_of_saving(client):
    result = tool_call(client, "save_patient", {**VALID_PATIENT, "date_of_birth": "01/01/2999"})
    assert result["success"] is False
    assert "date_of_birth" in result["errors"]
    assert client.get("/patients").json()["data"] == []


def test_db_failure_is_reported_to_agent_not_raised(client, monkeypatch):
    def boom(*_args, **_kwargs):
        raise OperationalError("INSERT", {}, Exception("db down"))

    monkeypatch.setattr("app.services.patients.create_patient", boom)
    result = tool_call(client, "save_patient", VALID_PATIENT)
    assert result["success"] is False
    assert result["error"] == "system_error"


def test_lookup_detects_returning_caller(client, patient):
    found = tool_call(client, "lookup_patient_by_phone", {"phone_number": "512 555 0198"})
    assert found["found"] is True
    assert found["patients"][0]["first_name"] == "Jane"

    missing = tool_call(client, "lookup_patient_by_phone", {"phone_number": "2125550111"})
    assert missing["found"] is False

    invalid = tool_call(client, "lookup_patient_by_phone", {"phone_number": "555"})
    assert invalid["valid_phone"] is False


def test_update_patient_tool(client, patient):
    result = tool_call(
        client, "update_patient", {"patient_id": patient["patient_id"], "city": "Dallas"}
    )
    assert result["success"] is True
    assert client.get(f"/patients/{patient['patient_id']}").json()["data"]["city"] == "Dallas"


def test_validate_patient_info_reports_missing_and_invalid(client):
    result = tool_call(client, "validate_patient_info", {"first_name": "Jane", "phone_number": "123"})
    assert result["valid"] is False
    assert "phone_number" in result["errors"]
    assert "last_name" in result["missing_required_fields"]


def test_appointment_flow(client, patient):
    slots = tool_call(client, "get_appointment_slots", {})["slots"]
    assert slots
    slot = slots[0]
    booking = {
        "patient_id": patient["patient_id"],
        "slot_start": slot["slot_start"],
        "provider_name": slot["provider_name"],
    }
    assert tool_call(client, "book_appointment", booking)["success"] is True
    assert tool_call(client, "book_appointment", booking)["error"] == "slot_taken"

    appts = client.get(f"/patients/{patient['patient_id']}/appointments").json()["data"]
    assert len(appts) == 1


def test_unknown_tool_does_not_crash(client):
    assert "error" in tool_call(client, "does_not_exist", {})


def test_end_of_call_report_stores_transcript(client):
    client.post("/vapi/webhook", json={"message": {
        "type": "end-of-call-report",
        "call": {"id": "call-dropped", "customer": {"number": "+15125550198"}},
        "endedReason": "customer-ended-call",
        "artifact": {"transcript": "AI: Hi there\nUser: bye"},
        "analysis": {"summary": "Caller hung up early."},
    }})
    calls = client.get("/calls").json()["data"]
    assert calls[0]["call_id"] == "call-dropped"
    assert calls[0]["ended_reason"] == "customer-ended-call"
    assert "bye" in calls[0]["transcript"]


def test_webhook_secret_enforced_when_configured(client, monkeypatch):
    monkeypatch.setattr(
        "app.voice.webhook.get_settings",
        lambda: Settings(**{**get_settings().__dict__, "webhook_secret": "s3cret"}),
    )
    res = client.post("/vapi/webhook", json={"message": {"type": "status-update"}})
    assert res.status_code == 401
    ok = tool_call(client, "validate_patient_info", {}, headers={"x-webhook-secret": "s3cret"})
    assert ok["valid"] is False
