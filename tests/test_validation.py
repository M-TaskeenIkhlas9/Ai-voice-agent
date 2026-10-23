from datetime import date

import pytest

from app import validation as v


@pytest.mark.parametrize("raw,expected", [
    ("(512) 555-0198", "5125550198"),
    ("+1 512 555 0198", "5125550198"),
    ("512.555.0198", "5125550198"),
])
def test_phone_normalization(raw, expected):
    assert v.normalize_phone(raw) == expected


@pytest.mark.parametrize("raw", ["123", "555-0198", "012-555-0198", "512-055-0198", "1234567890123"])
def test_phone_rejects_invalid(raw):
    with pytest.raises(ValueError):
        v.normalize_phone(raw)


def test_dob_formats_and_rules():
    today = date(2026, 10, 23)
    assert v.parse_date_of_birth("7/4/1990", today) == date(1990, 7, 4)
    assert v.parse_date_of_birth("1990-07-04", today) == date(1990, 7, 4)
    for bad in ("02/30/1990", "13/01/1990", "10/24/2026", "01/01/1850", "yesterday"):
        with pytest.raises(ValueError):
            v.parse_date_of_birth(bad, today)


@pytest.mark.parametrize("raw,expected", [("tx", "TX"), ("Texas", "TX"), ("new york", "NY"), ("D.C.", "DC")])
def test_state_normalization(raw, expected):
    assert v.normalize_state(raw) == expected


@pytest.mark.parametrize("raw", ["ZZ", "Texass", "T"])
def test_state_rejects_invalid(raw):
    with pytest.raises(ValueError):
        v.normalize_state(raw)


@pytest.mark.parametrize("name", ["Mary-Ann", "O'Brien", "José", "De La Cruz", "O’Neil"])
def test_names_accept_real_names(name):
    assert v.normalize_name(name)


@pytest.mark.parametrize("name", ["J0hn", "Smith!", "-Ann", "x" * 51])
def test_names_reject_invalid(name):
    with pytest.raises(ValueError):
        v.normalize_name(name)


def test_zip_and_member_id():
    assert v.normalize_zip("12345") == "12345"
    assert v.normalize_zip("123456789") == "12345-6789"
    with pytest.raises(ValueError):
        v.normalize_zip("1234")
    assert v.normalize_member_id("abc 123-456") == "ABC123456"


def test_sex_aliases():
    assert v.normalize_sex("prefer not to say") == "Decline to Answer"
    assert v.normalize_sex("femenino") == "Female"
    with pytest.raises(ValueError):
        v.normalize_sex("unknown")


def test_validate_fields_reports_errors_and_skips_blanks():
    normalized, errors = v.validate_fields(
        {"first_name": "Ann", "phone_number": "123", "email": "", "state": "ca"}
    )
    assert normalized == {"first_name": "Ann", "state": "CA"}
    assert list(errors) == ["phone_number"]
