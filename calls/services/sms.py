"""Outbound SMS.

The model can no longer send arbitrary texts (it used to be able to text any
number with any content). The only message we send is a fixed-template
booking confirmation, to the phone number stored on the appointment, with a
per-number daily cap.
"""
import logging
from datetime import datetime, timedelta

from django.conf import settings
from django.utils import timezone

from ..agent.arguments import ToolArgumentError, normalize_phone

logger = logging.getLogger(__name__)

CONFIRMATION_TEMPLATE = (
    "{clinic}: your {kind} appointment is confirmed for {when}. "
    "Reply or call us to make changes."
)

_twilio_client = None


def get_twilio_client():
    global _twilio_client
    if _twilio_client is None:
        from twilio.rest import Client

        _twilio_client = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)
    return _twilio_client


def sms_configured() -> bool:
    return bool(settings.TWILIO_ACCOUNT_SID and settings.TWILIO_AUTH_TOKEN and settings.TWILIO_PHONE_NUMBER)


def send_sms(to: str, message: str) -> dict:
    """Low-level send. Not exposed to the model."""
    result = get_twilio_client().messages.create(body=message, from_=settings.TWILIO_PHONE_NUMBER, to=to)
    return {"success": True, "sid": result.sid}


def render_confirmation(appointment) -> str:
    return CONFIRMATION_TEMPLATE.format(
        clinic=settings.CLINIC_NAME,
        kind=appointment.get_appointment_type_display().lower(),
        when=spoken_datetime(datetime.combine(appointment.date, appointment.time)),
    )


def spoken_datetime(when: datetime) -> str:
    """e.g. "Monday, November 2 at 2:30 PM" (portable: no %-d)."""
    hour = when.hour % 12 or 12
    suffix = "AM" if when.hour < 12 else "PM"
    return f"{when:%A, %B} {when.day} at {hour}:{when.minute:02d} {suffix}"


def _sent_recently(phone: str) -> int:
    from ..models import Appointment

    since = timezone.now() - timedelta(days=1)
    return Appointment.objects.filter(
        patient_phone=phone,
        sms_status__in=[Appointment.SMS_PENDING, Appointment.SMS_SENT],
        sms_updated_at__gte=since,
    ).count()


def _set_status(appointment, status: str, *, sid: str = "", error: str = "") -> None:
    appointment.sms_status = status
    appointment.sms_sid = sid
    appointment.sms_error = error[:255]
    appointment.sms_updated_at = timezone.now()
    appointment.save(update_fields=["sms_status", "sms_sid", "sms_error", "sms_updated_at"])


def queue_booking_confirmation(appointment) -> bool:
    """Queue the confirmation text for ``appointment``. Returns True if queued."""
    from ..background import run_in_background
    from ..models import Appointment

    if not sms_configured():
        _set_status(appointment, Appointment.SMS_SKIPPED, error="Twilio is not configured")
        return False
    try:
        normalize_phone(appointment.patient_phone)
    except ToolArgumentError:
        _set_status(appointment, Appointment.SMS_SKIPPED, error="invalid phone number")
        return False
    if _sent_recently(appointment.patient_phone) >= settings.SMS_DAILY_LIMIT_PER_NUMBER:
        logger.warning("[SMS] daily limit reached for appointment id=%s", appointment.pk)
        _set_status(appointment, Appointment.SMS_SKIPPED, error="daily limit reached")
        return False

    _set_status(appointment, Appointment.SMS_PENDING)
    run_in_background(deliver_booking_confirmation, appointment.pk)
    return True


def deliver_booking_confirmation(appointment_id: int) -> None:
    from ..models import Appointment

    appointment = Appointment.objects.get(pk=appointment_id)
    try:
        result = send_sms(appointment.patient_phone, render_confirmation(appointment))
    except Exception as exc:
        logger.error("[SMS] confirmation failed for appointment id=%s: %s", appointment_id, type(exc).__name__)
        _set_status(appointment, Appointment.SMS_FAILED, error=str(exc))
        return
    _set_status(appointment, Appointment.SMS_SENT, sid=result["sid"])
    logger.info("[SMS] confirmation sent for appointment id=%s", appointment_id)
