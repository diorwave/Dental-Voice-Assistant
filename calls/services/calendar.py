"""Google Calendar-backed availability and booking.

Rules enforced here (server-side, regardless of what the model asks for):

* Only offer/book inside the clinic's business hours for that weekday.
* The *whole* appointment must fit: a 60-minute new-patient visit needs 60
  free minutes and must end by closing time.
* No past dates or times.
* All-day events (holidays, closures) block the whole day; events marked
  "show as available" (transparent) block nothing.
* A slot that is already taken is reported as ``slot_taken`` together with
  nearby free alternatives — never as a success.
* Google Calendar is the source of truth for confirmed appointments: deleting
  an event there frees the slot (the DB row is marked cancelled).
"""
from __future__ import annotations

import logging
from datetime import date, datetime, time, timedelta

from django.conf import settings
from django.db import IntegrityError, connection, transaction
from django.utils import timezone

from .. import clinic
from ..agent.arguments import AvailabilityRequest, BookingRequest, ToolArgumentError

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/calendar"]

Interval = tuple[datetime, datetime]

# A reservation whose Calendar insert hasn't completed after this long is
# considered abandoned (e.g. the worker was killed) and released.
RESERVATION_TTL_MINUTES = 10
# First key of the PostgreSQL advisory lock used to serialize bookings per day.
BOOKING_LOCK_NAMESPACE = 72_001

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


def _nearest(slots: list[datetime], target: datetime, count: int = 2) -> list[str]:
    # Closest first; on a tie prefer the later slot (callers rarely want earlier).
    ranked = sorted(slots, key=lambda s: (abs((s - target).total_seconds()), s < target))
    return [s.strftime("%H:%M") for s in sorted(ranked[:count])]


# ─── Calendar I/O ─────────────────────────────────────────────────────────


def calendar_events(day: date) -> list[dict]:
    """Events overlapping ``day`` (clinic-local) on the clinic's Google Calendar."""
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
    return events.get("items", [])


def _intervals(events: list[dict]) -> list[Interval]:
    tz = clinic.clinic_tz()
    return [iv for iv in (event_interval(e, tz) for e in events) if iv]


def busy_intervals(day: date) -> list[Interval]:
    """Blocking intervals overlapping ``day`` from Google Calendar."""
    return _intervals(calendar_events(day))


def _reconcile_with_calendar(day: date, events: list[dict]) -> None:
    """Google Calendar is the source of truth for confirmed appointments: staff
    cancel by deleting the event. Release DB rows whose event is gone, and
    reservations whose Calendar insert never completed (crashed worker)."""
    from ..models import Appointment

    live_ids = {e.get("id") for e in events if e.get("status") != "cancelled"}
    stale_before = timezone.now() - timedelta(minutes=RESERVATION_TTL_MINUTES)
    released = 0
    for appt in Appointment.objects.filter(date=day, status=Appointment.STATUS_BOOKED):
        orphaned = appt.google_event_id and appt.google_event_id not in live_ids
        abandoned = not appt.google_event_id and appt.created_at < stale_before
        if orphaned or abandoned:
            appt.status = Appointment.STATUS_CANCELLED
            appt.save(update_fields=["status"])
            released += 1
    if released:
        logger.info("[BOOKING] released %d appointment(s) on %s no longer on the calendar", released, day)


def _db_busy_intervals(day: date) -> list[Interval]:
    """Booked appointments in our database. Covers a concurrent booking whose
    Calendar event isn't visible yet."""
    from ..models import Appointment

    tz = clinic.clinic_tz()
    intervals = []
    for appt in Appointment.objects.filter(date=day, status=Appointment.STATUS_BOOKED):
        start = datetime.combine(appt.date, appt.time, tz)
        intervals.append((start, start + timedelta(minutes=appt.duration_minutes)))
    return intervals


def _lock_day(day: date) -> None:
    """Serialize bookings for one day until the surrounding transaction ends.

    On PostgreSQL this is a transaction-scoped advisory lock, so the overlap
    re-check below can't interleave with another booking for the same day (the
    unique constraint alone only covers identical start times). SQLite (local
    dev) serializes writers itself.
    """
    if connection.vendor == "postgresql":
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(%s, %s)", [BOOKING_LOCK_NAMESPACE, day.toordinal()])


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

    events = calendar_events(request.date)
    _reconcile_with_calendar(request.date, events)
    busy = _intervals(events) + _db_busy_intervals(request.date)
    slots = [s.strftime("%H:%M") for s in free_slots(request.date, duration, busy, now)]
    return {
        "success": True,
        "date": request.date.isoformat(),
        "appointment_type": request.appointment_type,
        "duration_minutes": duration,
        "available_slots": slots,
        "total_available": len(slots),
    }


def book_appointment(request: BookingRequest, call=None) -> dict:
    from ..models import Appointment
    from .database import mark_appointment_booked

    tz = clinic.clinic_tz()
    now = clinic.now()
    duration = clinic.duration_for(request.appointment_type)
    start = datetime.combine(request.date, request.time, tz)
    end = start + timedelta(minutes=duration)
    validate_booking_window(start, duration, now)

    events = calendar_events(request.date)
    _reconcile_with_calendar(request.date, events)
    busy = _intervals(events) + _db_busy_intervals(request.date)

    # Idempotency: the model sometimes retries the same booking. Only treat it as
    # "already booked" when it's the *same patient* in the same slot, and only
    # once that booking has actually reached the calendar.
    existing = Appointment.objects.filter(
        date=request.date, time=request.time, status=Appointment.STATUS_BOOKED
    ).first()
    if existing and existing.patient_phone == request.patient_phone:
        if existing.google_event_id:
            logger.info("[BOOKING] idempotent repeat for appointment id=%s", existing.pk)
            return _booked_result(existing, start, end, already_booked=True)
        return {
            "success": False,
            "error": "booking_in_progress",
            "message": "This booking is still being saved. Wait a moment, then try again.",
        }
    if existing or overlaps(start, end, busy):
        return _slot_taken(request, start, duration, busy, now)

    # Reserve the slot in the database first, serialized per day, then create
    # the Calendar event. The unique constraint on booked (date, time) is a
    # backstop if the lock is unavailable.
    try:
        with transaction.atomic():
            _lock_day(request.date)
            if overlaps(start, end, _db_busy_intervals(request.date)):
                raise IntegrityError("overlapping appointment")
            appointment = Appointment.objects.create(
                date=request.date,
                time=request.time,
                patient_name=request.patient_name,
                patient_phone=request.patient_phone,
                appointment_type=request.appointment_type,
                duration_minutes=duration,
                call=call,
            )
    except IntegrityError:
        busy = busy_intervals(request.date) + _db_busy_intervals(request.date)
        return _slot_taken(request, start, duration, busy, now)

    try:
        event = (
            get_calendar_service()
            .events()
            .insert(
                calendarId=get_calendar_id(),
                body={
                    "summary": f"{request.appointment_type.replace('_', ' ').title()} - {request.patient_name}",
                    "description": f"Phone: {request.patient_phone}\nType: {request.appointment_type}",
                    "start": {"dateTime": start.isoformat(), "timeZone": tz.key},
                    "end": {"dateTime": end.isoformat(), "timeZone": tz.key},
                },
            )
            .execute()
        )
    except Exception:
        # Release the reservation so the slot isn't silently lost.
        appointment.delete()
        raise

    appointment.google_event_id = event["id"]
    appointment.save(update_fields=["google_event_id"])
    mark_appointment_booked(call)
    logger.info("[BOOKED] appointment id=%s on %s at %s", appointment.pk, request.date, request.time)
    return _booked_result(appointment, start, end)


def _booked_result(appointment, start: datetime, end: datetime, *, already_booked: bool = False) -> dict:
    result = {
        "success": True,
        "appointment_id": appointment.pk,
        "date": start.date().isoformat(),
        "time": start.strftime("%H:%M"),
        "start": start.isoformat(),
        "end": end.isoformat(),
        "duration_minutes": appointment.duration_minutes,
        "already_booked": already_booked,
    }
    if already_booked:
        result["note"] = "This patient already has this appointment; nothing new was created."
    return result


def _slot_taken(request: BookingRequest, start: datetime, duration: int, busy, now) -> dict:
    logger.info("[BOOKING] slot taken on %s at %s", request.date, request.time)
    alternatives = _nearest(free_slots(request.date, duration, busy, now), start)
    return {
        "success": False,
        "error": "slot_taken",
        "message": "That time is no longer available. Offer the caller one of the alternatives.",
        "alternatives": alternatives,
    }
