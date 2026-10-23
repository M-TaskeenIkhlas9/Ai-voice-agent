"""Field-level normalizers and validators for patient demographics.

Single source of truth for validation rules. Used by:
  * the Pydantic request schemas (REST API), and
  * the voice agent's ``validate_patient_info`` tool,
so the phone agent and the API can never disagree about what is valid.

Each normalizer takes raw input (often loosely formatted speech-to-text output)
and returns a canonical value, or raises ``ValueError`` with a message written
so the LLM can relay it to the caller ("must be a 10-digit U.S. number (got 3 digits)").
"""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import date, datetime
from typing import Any

SEX_VALUES = ("Male", "Female", "Other", "Decline to Answer")

US_STATES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas", "CA": "California",
    "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware", "FL": "Florida", "GA": "Georgia",
    "HI": "Hawaii", "ID": "Idaho", "IL": "Illinois", "IN": "Indiana", "IA": "Iowa",
    "KS": "Kansas", "KY": "Kentucky", "LA": "Louisiana", "ME": "Maine", "MD": "Maryland",
    "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota", "MS": "Mississippi",
    "MO": "Missouri", "MT": "Montana", "NE": "Nebraska", "NV": "Nevada", "NH": "New Hampshire",
    "NJ": "New Jersey", "NM": "New Mexico", "NY": "New York", "NC": "North Carolina",
    "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma", "OR": "Oregon", "PA": "Pennsylvania",
    "RI": "Rhode Island", "SC": "South Carolina", "SD": "South Dakota", "TN": "Tennessee",
    "TX": "Texas", "UT": "Utah", "VT": "Vermont", "VA": "Virginia", "WA": "Washington",
    "WV": "West Virginia", "WI": "Wisconsin", "WY": "Wyoming", "DC": "District of Columbia",
    "PR": "Puerto Rico", "GU": "Guam", "VI": "U.S. Virgin Islands", "AS": "American Samoa",
    "MP": "Northern Mariana Islands",
}
_STATE_BY_NAME = {name.lower(): code for code, name in US_STATES.items()}
_STATE_BY_NAME.update({"washington dc": "DC", "washington d.c.": "DC", "virgin islands": "VI"})

# Unicode letters (so "José" and "Zoë" pass), joined by single space, hyphen or apostrophe.
_NAME_RE = re.compile(r"^[^\W\d_]+(?:[ '\-][^\W\d_]+)*$")
_EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)*\.[A-Za-z]{2,}$")
_ZIP_RE = re.compile(r"^\d{5}(?:-\d{4})?$")
_MEMBER_ID_RE = re.compile(r"^[A-Z0-9]{1,30}$")

_SEX_ALIASES = {
    "male": "Male", "m": "Male", "man": "Male", "masculino": "Male", "hombre": "Male",
    "female": "Female", "f": "Female", "woman": "Female", "femenino": "Female", "mujer": "Female",
    "other": "Other", "non-binary": "Other", "nonbinary": "Other", "otro": "Other",
    "decline to answer": "Decline to Answer", "decline": "Decline to Answer",
    "prefer not to say": "Decline to Answer", "prefer not to answer": "Decline to Answer",
}


def _clean(value: Any) -> str:
    if value is None:
        raise ValueError("is required")
    text = re.sub(r"\s+", " ", str(value)).strip()
    if not text:
        raise ValueError("cannot be empty")
    return text


def normalize_name(value: Any, max_len: int = 50) -> str:
    text = _clean(value).replace("’", "'")
    if len(text) > max_len:
        raise ValueError(f"must be at most {max_len} characters")
    if not _NAME_RE.match(text):
        raise ValueError("may only contain letters, hyphens, apostrophes and spaces")
    return text


def normalize_full_name(value: Any) -> str:
    return normalize_name(value, max_len=100)


def parse_date_of_birth(value: Any, today: date | None = None) -> date:
    """Accepts MM/DD/YYYY (canonical), M/D/YYYY, MM-DD-YYYY or ISO YYYY-MM-DD."""
    if isinstance(value, datetime):
        value = value.date()
    if isinstance(value, date):
        dob = value
    else:
        text = _clean(value)
        dob = None
        for fmt in ("%m/%d/%Y", "%m-%d-%Y", "%Y-%m-%d"):
            try:
                dob = datetime.strptime(text, fmt).date()
                break
            except ValueError:
                continue
        if dob is None:
            raise ValueError("must be a real calendar date in MM/DD/YYYY format")
    today = today or date.today()
    if dob > today:
        raise ValueError("cannot be in the future")
    if dob.year < today.year - 130:
        raise ValueError("is more than 130 years ago; please double-check the year")
    return dob


def format_dob(value: date) -> str:
    return value.strftime("%m/%d/%Y")


def normalize_sex(value: Any) -> str:
    text = _clean(value).lower()
    if text in _SEX_ALIASES:
        return _SEX_ALIASES[text]
    raise ValueError("must be one of: Male, Female, Other, Decline to Answer")


def normalize_phone(value: Any) -> str:
    """Returns a bare 10-digit NANP number, e.g. '2125550101'."""
    digits = re.sub(r"\D", "", _clean(value))
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    if len(digits) != 10:
        raise ValueError(f"must be a 10-digit U.S. number (got {len(digits)} digits)")
    if digits[0] in "01" or digits[3] in "01":
        raise ValueError("is not a valid U.S. number (area code and exchange cannot start with 0 or 1)")
    return digits


def normalize_email(value: Any) -> str:
    text = _clean(value).replace(" ", "").lower()
    if len(text) > 254 or not _EMAIL_RE.match(text):
        raise ValueError("is not a valid email address")
    return text


def normalize_address_line(value: Any, max_len: int = 200) -> str:
    text = _clean(value)
    if len(text) > max_len:
        raise ValueError(f"must be at most {max_len} characters")
    return text


def normalize_address_line_2(value: Any) -> str:
    return normalize_address_line(value, max_len=100)


def normalize_city(value: Any) -> str:
    text = _clean(value)
    if len(text) > 100:
        raise ValueError("must be 1-100 characters")
    return text


def normalize_state(value: Any) -> str:
    text = _clean(value).replace(".", "").strip()
    if text.upper() in US_STATES:
        return text.upper()
    code = _STATE_BY_NAME.get(text.lower())
    if code:
        return code
    raise ValueError("must be a valid 2-letter U.S. state abbreviation")


def normalize_zip(value: Any) -> str:
    text = _clean(value).replace(" ", "")
    if re.fullmatch(r"\d{9}", text):
        text = f"{text[:5]}-{text[5:]}"
    if not _ZIP_RE.match(text):
        raise ValueError("must be a 5-digit ZIP code or ZIP+4 (12345-6789)")
    return text


def normalize_short_text(value: Any, max_len: int = 100) -> str:
    text = _clean(value)
    if len(text) > max_len:
        raise ValueError(f"must be at most {max_len} characters")
    return text


def normalize_member_id(value: Any) -> str:
    # Spoken IDs arrive as "ABC 123-456"; store the bare alphanumeric form.
    text = re.sub(r"[\s\-]", "", _clean(value)).upper()
    if not _MEMBER_ID_RE.match(text):
        raise ValueError("must be letters and numbers only (max 30 characters)")
    return text


def normalize_language(value: Any) -> str:
    return normalize_short_text(value, max_len=50).title()


# field name -> normalizer. Order matters: it is the order fields are reported.
FIELD_NORMALIZERS: dict[str, Callable[[Any], Any]] = {
    "first_name": normalize_name,
    "last_name": normalize_name,
    "date_of_birth": parse_date_of_birth,
    "sex": normalize_sex,
    "phone_number": normalize_phone,
    "email": normalize_email,
    "address_line_1": normalize_address_line,
    "address_line_2": normalize_address_line_2,
    "city": normalize_city,
    "state": normalize_state,
    "zip_code": normalize_zip,
    "insurance_provider": normalize_short_text,
    "insurance_member_id": normalize_member_id,
    "preferred_language": normalize_language,
    "emergency_contact_name": normalize_full_name,
    "emergency_contact_phone": normalize_phone,
}

REQUIRED_FIELDS = (
    "first_name", "last_name", "date_of_birth", "sex", "phone_number",
    "address_line_1", "city", "state", "zip_code",
)


def validate_fields(raw: dict[str, Any]) -> tuple[dict[str, Any], dict[str, str]]:
    """Validates whichever known fields are present (blank values are skipped).

    Returns (normalized, errors). Dates come back as MM/DD/YYYY strings so the
    result is JSON-serializable for the voice tool.
    """
    normalized: dict[str, Any] = {}
    errors: dict[str, str] = {}
    for field, normalizer in FIELD_NORMALIZERS.items():
        value = raw.get(field)
        if value is None or (isinstance(value, str) and not value.strip()):
            continue
        try:
            result = normalizer(value)
        except ValueError as exc:
            errors[field] = f"{field.replace('_', ' ')} {exc}"
            continue
        normalized[field] = format_dob(result) if isinstance(result, date) else result
    return normalized, errors
