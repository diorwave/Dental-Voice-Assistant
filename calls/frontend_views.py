"""Frontend (HTML) views: public landing page, chat tester, and staff dashboard.

These render Django templates and are separate from the JSON API views in views.py
that Vapi calls. The chat tester and voice widget both drive the same
/api/vapi/chat/completions/ endpoint the phone line uses; the text chat tester
is only rendered for staff because it authenticates with the staff session.
"""
from datetime import timedelta

from django.conf import settings
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.utils import timezone

from .models import Appointment, CallLog


def _example_date():
    """A near-future weekday, formatted YYYY-MM-DD, for chat placeholder text."""
    return (timezone.localdate() + timedelta(days=3)).isoformat()


def landing(request):
    return render(request, "landing.html", {
        "vapi_public_key": settings.VAPI_PUBLIC_KEY,
        "vapi_assistant_id": settings.VAPI_ASSISTANT_ID,
        "example_date": _example_date(),
    })


@staff_member_required
def chat_page(request):
    # Runs the real agent (OpenAI, Calendar writes, SMS), so staff only.
    return render(request, "chat.html", {"example_date": _example_date()})


@login_required
def dashboard(request):
    today = timezone.localdate()
    total_calls = CallLog.objects.count()
    booked_calls = CallLog.objects.filter(appointment_booked=True).count()
    conversion = round(booked_calls / total_calls * 100) if total_calls else 0

    return render(request, "dashboard.html", {
        "today": today,
        "total_calls": total_calls,
        "booked_calls": booked_calls,
        "conversion": conversion,
        "todays_appts": Appointment.objects.filter(date=today, status=Appointment.STATUS_BOOKED).count(),
        "upcoming": Appointment.objects.filter(date__gte=today, status=Appointment.STATUS_BOOKED).count(),
        "appointments": Appointment.objects.all()[:50],
        "calls": CallLog.objects.all()[:50],
    })
