import logging
from datetime import datetime, time, timedelta
from django.conf import settings

from .. import clinic
from ..agent.arguments import AvailabilityRequest, BookingRequest
from googleapiclient.discovery import build
from google.oauth2 import service_account

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/calendar"]

_calendar_service = None


def get_calendar_service():
    global _calendar_service
    if _calendar_service is None:
        creds = service_account.Credentials.from_service_account_file(
            settings.GOOGLE_CALENDAR_CREDENTIALS, scopes=SCOPES
        )
        _calendar_service = build("calendar", "v3", credentials=creds)
    return _calendar_service


def get_calendar_id():
    return settings.GOOGLE_CALENDAR_ID


def check_availability(request: AvailabilityRequest) -> dict:
    service = get_calendar_service()
    calendar_id = get_calendar_id()

    tz = clinic.clinic_tz()
    day = request.date
    start_of_day = datetime.combine(day, time(8, 0), tz)
    end_of_day = datetime.combine(day, time(18, 0), tz)

    events = (
        service.events()
        .list(
            calendarId=calendar_id,
            timeMin=start_of_day.isoformat(),
            timeMax=end_of_day.isoformat(),
            singleEvents=True,
            orderBy="startTime",
            timeZone=tz.key,
        )
        .execute()
    )

    busy_slots = [
        (e["start"]["dateTime"], e["end"]["dateTime"])
        for e in events.get("items", [])
    ]

    available = []
    for hour in range(8, 18):
        for minute in [0, 30]:
            slot = datetime.combine(day, time(hour, minute), tz)
            is_busy = any(
                datetime.fromisoformat(s) <= slot < datetime.fromisoformat(e)
                for s, e in busy_slots
            )
            if not is_busy:
                available.append(f"{hour:02d}:{minute:02d}")

    return {"date": day.isoformat(), "available_slots": available, "total_available": len(available)}


def book_appointment(request: BookingRequest) -> dict:
    from ..models import Appointment

    service = get_calendar_service()
    calendar_id = get_calendar_id()

    tz = clinic.clinic_tz()
    duration = clinic.duration_for(request.appointment_type)
    start = datetime.combine(request.date, request.time, tz)
    end = start + timedelta(minutes=duration)

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
