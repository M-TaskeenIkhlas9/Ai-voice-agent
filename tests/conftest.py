import os
import tempfile

# Must be set before the app (and its cached settings) are imported.
_DB_DIR = tempfile.mkdtemp(prefix="patients-test-")
# Tests drop all tables, so never inherit DATABASE_URL; opt in via TEST_DATABASE_URL.
os.environ["DATABASE_URL"] = os.getenv("TEST_DATABASE_URL", f"sqlite:///{_DB_DIR}/test.db")
os.environ["SEED_DATA"] = "false"
os.environ["VAPI_WEBHOOK_SECRET"] = ""
os.environ["API_KEY"] = ""

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import db as database  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture(scope="session")
def _client():
    with TestClient(app) as client:
        yield client


@pytest.fixture
def client(_client):
    """Fresh empty schema for every test."""
    database.Base.metadata.drop_all(database.engine)
    database.Base.metadata.create_all(database.engine)
    return _client


VALID_PATIENT = {
    "first_name": "Jane",
    "last_name": "Davis",
    "date_of_birth": "03/14/1985",
    "sex": "Female",
    "phone_number": "512-555-0198",
    "address_line_1": "123 Main St",
    "city": "Austin",
    "state": "TX",
    "zip_code": "78701",
}


@pytest.fixture
def patient(client):
    res = client.post("/patients", json=VALID_PATIENT)
    assert res.status_code == 201, res.text
    return res.json()["data"]
