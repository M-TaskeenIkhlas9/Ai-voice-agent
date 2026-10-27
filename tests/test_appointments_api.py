from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from app.config import get_settings


def _next_weekday_slot(hour: int = 10, days_ahead: int = 2) -> datetime:
    tz = ZoneInfo(get_settings().clinic_timezone)
    day = datetime.now(tz).date() + timedelta(days=days_ahead)
    while day.weekday() >= 5:
        day += timedelta(days=1)
    return datetime.combine(day, time(hour), tzinfo=tz)


def _book(client, patient, slot: datetime, provider="Dr. Sarah Chen"):
    return client.post("/appointments", json={
        "patient_id": patient["patient_id"], "slot_start": slot.isoformat(), "provider_name": provider,
    })


def test_book_and_list_schedule(client, patient):
    slot = _next_weekday_slot()
    res = _book(client, patient, slot)
    assert res.status_code == 201, res.text
    assert res.json()["data"]["created_at"]

    listed = client.get("/appointments", params={"start": slot.date().isoformat(), "days": 1}).json()["data"]
    assert len(listed) == 1
    assert listed[0]["patient_name"] == "Jane Davis"
    assert listed[0]["provider_name"] == "Dr. Sarah Chen"

    other_day = (slot.date() + timedelta(days=1)).isoformat()
    assert client.get("/appointments", params={"start": other_day, "days": 1}).json()["data"] == []


def test_double_booking_is_409(client, patient):
    slot = _next_weekday_slot()
    assert _book(client, patient, slot).status_code == 201
    assert _book(client, patient, slot).status_code == 409
    assert _book(client, patient, slot, provider="Dr. Michael Okafor").status_code == 201


def test_rejects_slots_outside_clinic_hours(client, patient):
    assert _book(client, patient, _next_weekday_slot(hour=20)).status_code == 422
    assert _book(client, patient, _next_weekday_slot(hour=10) + timedelta(minutes=30)).status_code == 422
    assert _book(client, patient, _next_weekday_slot(), provider="Dr. Nobody").status_code == 422


def test_bad_start_date_is_422(client):
    assert client.get("/appointments", params={"start": "next tuesday"}).status_code == 422


def test_config_exposes_no_secrets(client):
    data = client.get("/config").json()["data"]
    assert data["providers"] and data["clinic_hours"]
    assert data["web_call"] is None  # not configured in tests
    flat = str(data).lower()
    assert "secret" not in flat and "database" not in flat
