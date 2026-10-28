"""Validation for arguments the model passes to tools.

The model is an untrusted, occasionally sloppy client: it may send "2026-1-5",
"9:30", "2:30 PM", or forget a field entirely. Instead of crashing with a
ValueError/KeyError deep inside a service, parse everything up front and
return a structured error the model can act on ("ask the caller again").
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, time

APPOINTMENT_TYPES = ("new_patient", "returning", "emergency")

_TIME_FORMATS = ("%H:%M", "%H:%M:%S", "%I:%M %p", "%I:%M%p", "%I %p", "%I%p")
_PHONE_STRIP = re.compile(r"[\s().\-]")
_E164 = re.compile(r"^\+[1-9]\d{7,14}$")


class ToolArgumentError(ValueError):
    """Raised when a tool argument is missing or malformed."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message

    def as_result(self) -> dict:
        return {"success": False, "error": self.code, "message": self.message}


def parse_date(value) -> date:
    if not isinstance(value, str) or not value.strip():
        raise ToolArgumentError("invalid_date", "A date in YYYY-MM-DD format is required.")
    try:
        # strptime accepts non-zero-padded parts ("2026-1-5"), fromisoformat doesn't.
        return datetime.strptime(value.strip(), "%Y-%m-%d").date()
    except ValueError:
        raise ToolArgumentError(
            "invalid_date", f"Could not understand the date {value!r}; use YYYY-MM-DD."
        ) from None


def parse_time(value) -> time:
    if not isinstance(value, str) or not value.strip():
        raise ToolArgumentError("invalid_time", "A time in HH:MM (24-hour) format is required.")
    text = value.strip().upper().replace(".", "")
    for fmt in _TIME_FORMATS:
        try:
            return datetime.strptime(text, fmt).time()
        except ValueError:
            continue
    raise ToolArgumentError(
        "invalid_time", f"Could not understand the time {value!r}; use HH:MM in 24-hour format."
    )


def normalize_phone(value, *, default_country_code: str = "1") -> str:
    """Return ``value`` as an E.164 number or raise ToolArgumentError.

    Bare 10-digit numbers are assumed to be in ``default_country_code`` (NANP).
    """
    if not isinstance(value, str) or not value.strip():
        raise ToolArgumentError("invalid_phone", "A phone number is required.")
    digits = _PHONE_STRIP.sub("", value.strip())
    if not digits.startswith("+"):
        if len(digits) == 10:
            digits = f"+{default_country_code}{digits}"
        elif len(digits) == 11 and digits.startswith(default_country_code):
            digits = f"+{digits}"
        else:
            digits = f"+{digits}"
    if not _E164.match(digits):
        raise ToolArgumentError(
            "invalid_phone", f"{value!r} is not a valid phone number; please confirm it with the caller."
        )
    return digits


def _require(args: dict, key: str) -> str:
    value = args.get(key)
    if value is None or (isinstance(value, str) and not value.strip()):
        raise ToolArgumentError(f"missing_{key}", f"The {key.replace('_', ' ')} is required.")
    return value


def parse_appointment_type(value) -> str:
    value = value or "returning"
    if value not in APPOINTMENT_TYPES:
        raise ToolArgumentError(
            "invalid_appointment_type", f"appointment_type must be one of {', '.join(APPOINTMENT_TYPES)}."
        )
    return value


@dataclass(frozen=True)
class AvailabilityRequest:
    date: date
    appointment_type: str

    @classmethod
    def from_args(cls, args: dict) -> "AvailabilityRequest":
        return cls(
            date=parse_date(_require(args, "date")),
            appointment_type=parse_appointment_type(args.get("appointment_type")),
        )


@dataclass(frozen=True)
class BookingRequest:
    date: date
    time: time
    patient_name: str
    patient_phone: str
    appointment_type: str

    @classmethod
    def from_args(cls, args: dict) -> "BookingRequest":
        name = str(_require(args, "patient_name")).strip()[:100]
        return cls(
            date=parse_date(_require(args, "date")),
            time=parse_time(_require(args, "time")),
            patient_name=name,
            patient_phone=normalize_phone(_require(args, "patient_phone")),
            appointment_type=parse_appointment_type(_require(args, "appointment_type")),
        )
