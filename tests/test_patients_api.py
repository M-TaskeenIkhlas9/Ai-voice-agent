import uuid

from app import db as database
from app.config import Settings, get_settings
from app.models import Patient
from tests.conftest import VALID_PATIENT


def test_create_returns_201_with_envelope_and_normalized_fields(client):
    body = {**VALID_PATIENT, "state": "texas", "zip_code": "787011234", "sex": "f"}
    res = client.post("/patients", json=body)

    assert res.status_code == 201
    payload = res.json()
    assert payload["error"] is None
    data = payload["data"]
    assert data["patient_id"]
    assert data["phone_number"] == "5125550198"
    assert data["state"] == "TX"
    assert data["zip_code"] == "78701-1234"
    assert data["sex"] == "Female"
    assert data["date_of_birth"] == "03/14/1985"
    assert data["preferred_language"] == "English"
    assert data["created_at"].endswith("Z")


def test_create_rejects_invalid_fields_with_422_and_per_field_details(client):
    body = {**VALID_PATIENT, "phone_number": "123", "date_of_birth": "01/01/2999", "state": "ZZ"}
    res = client.post("/patients", json=body)

    assert res.status_code == 422
    payload = res.json()
    assert payload["data"] is None
    details = payload["error"]["details"]
    assert set(details) == {"phone_number", "date_of_birth", "state"}
    assert "future" in details["date_of_birth"]


def test_create_requires_required_fields(client):
    res = client.post("/patients", json={"first_name": "Jane"})
    assert res.status_code == 422
    assert "last_name" in res.json()["error"]["details"]


def test_create_rejects_unknown_fields(client):
    res = client.post("/patients", json={**VALID_PATIENT, "ssn": "123-45-6789"})
    assert res.status_code == 422
    assert "ssn" in res.json()["error"]["details"]


def test_malformed_json_is_400(client):
    res = client.post("/patients", content="{not json", headers={"content-type": "application/json"})
    assert res.status_code == 400


def test_get_by_id(client, patient):
    res = client.get(f"/patients/{patient['patient_id']}")
    assert res.status_code == 200
    assert res.json()["data"]["last_name"] == "Davis"


def test_get_unknown_is_404_and_bad_uuid_is_400(client):
    assert client.get("/patients/00000000-0000-0000-0000-000000000000").status_code == 404
    assert client.get("/patients/not-a-uuid").status_code == 400


def test_list_filters(client, patient):
    client.post("/patients", json={**VALID_PATIENT, "last_name": "Smith", "phone_number": "2125550111"})

    assert len(client.get("/patients").json()["data"]) == 2
    assert len(client.get("/patients", params={"last_name": "davis"}).json()["data"]) == 1
    assert len(client.get("/patients", params={"phone_number": "(512) 555-0198"}).json()["data"]) == 1
    assert len(client.get("/patients", params={"date_of_birth": "1985-03-14"}).json()["data"]) == 2
    assert client.get("/patients", params={"phone_number": "12"}).status_code == 422


def test_partial_update(client, patient):
    pid = patient["patient_id"]
    res = client.put(f"/patients/{pid}", json={"last_name": "Davies", "email": "Jane@Example.com"})

    assert res.status_code == 200
    data = res.json()["data"]
    assert data["last_name"] == "Davies"
    assert data["email"] == "jane@example.com"
    assert data["first_name"] == "Jane"  # untouched
    assert data["updated_at"] >= patient["updated_at"]


def test_update_cannot_null_required_field(client, patient):
    res = client.put(f"/patients/{patient['patient_id']}", json={"city": None})
    assert res.status_code == 422


def test_update_can_clear_optional_field(client, patient):
    pid = patient["patient_id"]
    client.put(f"/patients/{pid}", json={"email": "a@b.co"})
    res = client.put(f"/patients/{pid}", json={"email": None})
    assert res.status_code == 200
    assert res.json()["data"]["email"] is None


def test_soft_delete_hides_record_but_keeps_row(client, patient):
    pid = patient["patient_id"]
    res = client.delete(f"/patients/{pid}")
    assert res.status_code == 200
    assert res.json()["data"]["deleted_at"]

    assert client.get(f"/patients/{pid}").status_code == 404
    assert client.get("/patients").json()["data"] == []
    assert client.delete(f"/patients/{pid}").status_code == 404

    with database.SessionLocal() as s:
        row = s.get(Patient, uuid.UUID(pid))
        assert row is not None and row.deleted_at is not None


def test_api_key_enforced_on_writes_when_configured(client, monkeypatch):
    monkeypatch.setattr(
        "app.api.patients.get_settings",
        lambda: Settings(**{**get_settings().__dict__, "api_key": "secret"}),
    )
    assert client.post("/patients", json=VALID_PATIENT).status_code == 401
    res = client.post("/patients", json=VALID_PATIENT, headers={"X-API-Key": "secret"})
    assert res.status_code == 201
    assert client.get("/patients").status_code == 200  # reads stay open
