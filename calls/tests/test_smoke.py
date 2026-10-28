"""Smoke tests that exercise routing, models, and the frontend without any
external API calls (no OpenAI / Vapi / Google / Twilio keys required)."""
from datetime import time

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from calls.models import Appointment, CallLog


class HealthAndApiTests(TestCase):
    def test_webhook_health_check(self):
        res = self.client.get("/api/vapi/webhook/")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["status"], "ok")

    def test_chat_completions_rejects_get(self):
        res = self.client.get("/api/vapi/chat/completions/")
        self.assertEqual(res.status_code, 405)


class FrontendTests(TestCase):
    def test_landing_page_renders(self):
        res = self.client.get(reverse("landing"))
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "Bright Smile Dental")

    def test_chat_page_renders(self):
        self.assertEqual(self.client.get(reverse("chat")).status_code, 200)

    def test_dashboard_requires_login(self):
        # Anonymous users are redirected to the login page.
        res = self.client.get(reverse("dashboard"))
        self.assertEqual(res.status_code, 302)

    def test_dashboard_visible_when_authenticated(self):
        User.objects.create_superuser("staff", "staff@example.com", "pw12345")
        self.client.login(username="staff", password="pw12345")
        res = self.client.get(reverse("dashboard"))
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "dashboard")


class ModelTests(TestCase):
    def test_appointment_and_calllog_persist(self):
        CallLog.objects.create(caller_phone="+15551234567", appointment_booked=True)
        Appointment.objects.create(
            patient_name="Test Patient",
            patient_phone="+15551234567",
            appointment_type="returning",
            date="2026-08-01",
            time=time(10, 0),
        )
        self.assertEqual(CallLog.objects.count(), 1)
        self.assertEqual(Appointment.objects.first().patient_name, "Test Patient")
