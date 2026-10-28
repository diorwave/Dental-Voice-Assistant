"""Single source of truth for clinic-level scheduling rules.

Everything that depends on "what time is it at the clinic" or "is the clinic
open" goes through this module so the prompt, the calendar service and the
dashboard can never disagree again.
"""
from __future__ import annotations

from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from django.conf import settings

WEEKDAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def clinic_tz() -> ZoneInfo:
    return ZoneInfo(settings.CLINIC_TIMEZONE)


def now() -> datetime:
    """Current wall-clock time at the clinic (timezone-aware)."""
    return datetime.now(clinic_tz())


def today() -> date:
    return now().date()


def hours_for(day: date) -> tuple[time, time] | None:
    """Opening and closing time for ``day``, or ``None`` when closed."""
    hours = settings.CLINIC_BUSINESS_HOURS.get(day.weekday())
    if not hours:
        return None
    open_, close = hours
    return time.fromisoformat(open_), time.fromisoformat(close)


def duration_for(appointment_type: str) -> int:
    """Appointment length in minutes for an appointment type."""
    durations = settings.CLINIC_APPOINTMENT_DURATIONS
    return durations.get(appointment_type, durations["returning"])


def _fmt(t: time) -> str:
    # "8am", "2pm", "9:30am" — reads naturally when spoken.
    suffix = "am" if t.hour < 12 else "pm"
    hour = t.hour % 12 or 12
    return f"{hour}{suffix}" if t.minute == 0 else f"{hour}:{t.minute:02d}{suffix}"


def describe_hours() -> str:
    """Human-readable weekly hours, e.g. for the system prompt."""
    parts = []
    for weekday, name in enumerate(WEEKDAY_NAMES):
        hours = settings.CLINIC_BUSINESS_HOURS.get(weekday)
        if hours:
            open_, close = (time.fromisoformat(h) for h in hours)
            parts.append(f"{name} {_fmt(open_)} to {_fmt(close)}")
        else:
            parts.append(f"{name} closed")
    return ". ".join(parts) + "."
