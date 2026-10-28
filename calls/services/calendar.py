"""Google Calendar-backed availability and booking.

Rules enforced here (server-side, regardless of what the model asks for):

* Only offer/book inside the clinic's business hours for that weekday.
* The *whole* appointment must fit: a 60-minute new-patient visit needs 60
  free minutes and must end by closing time.
* No past dates or times.
* All-day events (holidays, closures) block the whole day; events marked
  "show as available" (transparent) block nothing.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, time, timedelta

from django.conf import settings

from .. import clinic
from ..agent.arguments import AvailabilityRequest, BookingRequest, ToolArgumentError

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/calendar"]

Interval = tuple[datetime, datetime]

_calendar_service = None


def get_calendar_service():
    global _calendar_service
    if _calendar_service is None:
        from google.oauth2 import service_account
        from googleapiclient.discovery import build

        creds = service_account.Credentials.from_service_account_file(
            settings.GOOGLE_CALENDAR_CREDENTIALS, scopes=SCOPES
        )
        _calendar_service = build("calendar", "v3", credentials=creds, cache_discovery=False)
    return _calendar_service


def get_calendar_id():
    return settings.GOOGLE_CALENDAR_ID


# ─── Pure scheduling helpers (no I/O, unit-tested directly) ───────────────


def event_interval(event: dict, tz) -> Interval | None:
    """Return the blocking interval of a Calendar event, or None if it doesn't block."""
    if event.get("transparency") == "transparent" or event.get("status") == "cancelled":
        return None
    start, end = event.get("start") or {}, event.get("end") or {}
    if "dateTime" in start:
        return datetime.fromisoformat(start["dateTime"]), datetime.fromisoformat(end["dateTime"])
    if "date" in start:
        # All-day event; Google's end date is exclusive.
        first = date.fromisoformat(start["date"])
        last = date.fromisoformat(end["date"]) if "date" in end else first + timedelta(days=1)
        return datetime.combine(first, time.min, tz), datetime.combine(last, time.min, tz)
    return None


def overlaps(start: datetime, end: datetime, busy: list[Interval]) -> bool:
    return any(b_start < end and start < b_end for b_start, b_end in busy)


def opening_window(day: date) -> Interval | None:
    hours = clinic.hours_for(day)
    if hours is None:
        return None
    tz = clinic.clinic_tz()
    return datetime.combine(day, hours[0], tz), datetime.combine(day, hours[1], tz)


def free_slots(day: date, duration_minutes: int, busy: list[Interval], now: datetime) -> list[datetime]:
    """Every slot start on ``day`` where the full appointment fits and is free."""
    window = opening_window(day)
    if window is None:
        return []
    open_at, close_at = window
    step = timedelta(minutes=settings.CLINIC_SLOT_INTERVAL_MINUTES)
    length = timedelta(minutes=duration_minutes)

    slots = []
    slot = open_at
    while slot + length <= close_at:
        if slot > now and not overlaps(slot, slot + length, busy):
            slots.append(slot)
        slot += step
    return slots


def validate_booking_window(start: datetime, duration_minutes: int, now: datetime) -> None:
    """Raise ToolArgumentError if an appointment can't be booked at ``start``."""
    if start <= now:
        raise ToolArgumentError("time_in_past", "That time has already passed; please pick a future time.")
    window = opening_window(start.date())
    if window is None:
        raise ToolArgumentError(
            "clinic_closed", f"The clinic is closed on {clinic.WEEKDAY_NAMES[start.weekday()]}s."
        )
    open_at, close_at = window
    end = start + timedelta(minutes=duration_minutes)
    if start < open_at or end > close_at:
        raise ToolArgumentError(
            "outside_business_hours",
            f"A {duration_minutes}-minute appointment must start no earlier than "
            f"{open_at:%H:%M} and finish by {close_at:%H:%M} on that day.",
        )


# ─── Calendar I/O ─────────────────────────────────────────────────────────


def busy_intervals(day: date) -> list[Interval]:
    """Blocking intervals overlapping ``day`` (clinic-local), from Google Calendar."""
    tz = clinic.clinic_tz()
    day_start = datetime.combine(day, time.min, tz)
    events = (
        get_calendar_service()
        .events()
        .list(
            calendarId=get_calendar_id(),
            timeMin=day_start.isoformat(),
            timeMax=(day_start + timedelta(days=1)).isoformat(),
            singleEvents=True,
            orderBy="startTime",
            timeZone=tz.key,
        )
        .execute()
    )
    intervals = []
    for event in events.get("items", []):
        interval = event_interval(event, tz)
        if interval:
            intervals.append(interval)
    return intervals


def check_availability(request: AvailabilityRequest) -> dict:
    now = clinic.now()
    if request.date < now.date():
        raise ToolArgumentError("date_in_past", "That date has already passed; please pick a future date.")

    duration = clinic.duration_for(request.appointment_type)
    if clinic.hours_for(request.date) is None:
        return {
            "success": True,
            "date": request.date.isoformat(),
            "closed": True,
            "message": f"The clinic is closed on {clinic.WEEKDAY_NAMES[request.date.weekday()]}s.",
            "available_slots": [],
            "total_available": 0,
        }

    busy = busy_intervals(request.date)
    slots = [s.strftime("%H:%M") for s in free_slots(request.date, duration, busy, now)]
    return {
        "success": True,
        "date": request.date.isoformat(),
        "appointment_type": request.appointment_type,
        "duration_minutes": duration,
        "available_slots": slots,
        "total_available": len(slots),
    }


def book_appointment(request: BookingRequest) -> dict:
    from ..models import Appointment

    service = get_calendar_service()
    calendar_id = get_calendar_id()

    tz = clinic.clinic_tz()
    duration = clinic.duration_for(request.appointment_type)
    start = datetime.combine(request.date, request.time, tz)
    end = start + timedelta(minutes=duration)
    validate_booking_window(start, duration, clinic.now())

    # Check for existing bookings at this slot to prevent duplicates
    existing = (
        service.events()
        .list(
            calendarId=calendar_id,
            timeMin=start.isoformat(),
            timeMax=end.isoformat(),
            singleEvents=True,
            timeZone=tz.key,
        )
        .execute()
    )
    if existing.get("items"):
        existing_event = existing["items"][0]
        logger.info(f"[DUPLICATE] Slot already booked at {request.date} {request.time}")
        return {
            "success": True,
            "event_id": existing_event["id"],
            "start": start.isoformat(),
            "end": end.isoformat(),
            "note": "Appointment was already booked for this slot.",
        }

    event = (
        service.events()
        .insert(
            calendarId=calendar_id,
            body={
                "summary": f"{request.appointment_type.replace('_', ' ').title()} - {request.patient_name}",
                "description": f"Phone: {request.patient_phone}\nType: {request.appointment_type}",
                "start": {"dateTime": start.isoformat(), "timeZone": tz.key},
                "end": {"dateTime": end.isoformat(), "timeZone": tz.key},
            },
        )
        .execute()
    )

    # Save appointment to database (prevent DB-level duplicates too)
    Appointment.objects.get_or_create(
        date=request.date,
        time=request.time,
        patient_phone=request.patient_phone,
        defaults={
            "patient_name": request.patient_name,
            "appointment_type": request.appointment_type,
            "duration_minutes": duration,
            "google_event_id": event["id"],
        },
    )
    logger.info(f"[BOOKED] {request.patient_name} on {request.date} at {request.time}")

    return {
        "success": True,
        "event_id": event["id"],
        "start": start.isoformat(),
        "end": end.isoformat(),
    }
