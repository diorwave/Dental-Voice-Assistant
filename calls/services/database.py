"""Call bookkeeping.

A ``CallLog`` row is keyed by Vapi's call id. It is created on the first
conversation turn (so appointments booked during the call can link to it) and
completed by the end-of-call webhook. ``appointment_booked`` is derived from
whether an Appointment was actually created during the call — it is never
left to the model to report.
"""
from __future__ import annotations

from django.db import transaction

from ..models import CallLog


def get_or_create_call(vapi_call_id: str | None, caller_phone: str | None = None) -> CallLog | None:
    if not vapi_call_id:
        return None
    call, created = CallLog.objects.get_or_create(
        vapi_call_id=vapi_call_id, defaults={"caller_phone": caller_phone or ""}
    )
    if not created and caller_phone and not call.caller_phone:
        call.caller_phone = caller_phone
        call.save(update_fields=["caller_phone"])
    return call


def mark_appointment_booked(call: CallLog | None) -> None:
    if call is not None and not call.appointment_booked:
        CallLog.objects.filter(pk=call.pk).update(appointment_booked=True)
        call.appointment_booked = True


@transaction.atomic
def record_end_of_call(
    *,
    vapi_call_id: str | None,
    caller_phone: str | None,
    summary: str,
    duration_seconds: int | None,
) -> CallLog:
    """Upsert the CallLog for an end-of-call report (idempotent on vapi_call_id)."""
    if vapi_call_id:
        call, _ = CallLog.objects.select_for_update().get_or_create(vapi_call_id=vapi_call_id)
    else:
        call = CallLog()
    if caller_phone:
        call.caller_phone = caller_phone
    call.call_summary = summary
    call.duration_seconds = duration_seconds
    call.appointment_booked = call.pk is not None and call.appointments.filter(status="booked").exists()
    call.save()
    return call
