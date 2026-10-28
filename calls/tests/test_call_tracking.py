import json
from unittest import mock

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.urls import reverse

from calls.agent.arguments import BookingRequest
from calls.models import CallLog
from calls.services import calendar
from calls.services.database import get_or_create_call

from .fakes import FakeCalendar, clinic_time, patch_calendar, patch_now
from .helpers import TEST_SECRET, api_post

END_OF_CALL = {
    "message": {
        "type": "end-of-call-report",
        "summary": "Booked a cleaning.",
        "call": {"id": "call-123", "customer": {"number": "+15551234567"}, "duration": 95},
    }
}


@override_settings(VAPI_SECRET=TEST_SECRET)
class CallTrackingTests(TestCase):
    def _book_during_call(self, call):
        request = BookingRequest.from_args({
            "date": "2026-11-02", "time": "10:00", "patient_name": "Jane Doe",
            "patient_phone": "+15551234567", "appointment_type": "returning",
        })
        with patch_calendar(FakeCalendar()), patch_now(clinic_time(2026, 11, 2, 7)):
            return calendar.book_appointment(request, call=call)

    def test_webhook_upserts_the_call_created_during_the_conversation(self):
        call = get_or_create_call("call-123", "+15551234567")
        self._book_during_call(call)

        res = api_post(self.client, "/api/vapi/webhook/", END_OF_CALL)
        self.assertEqual(res.status_code, 200)

        self.assertEqual(CallLog.objects.count(), 1)
        log = CallLog.objects.get()
        self.assertTrue(log.appointment_booked)
        self.assertEqual(log.duration_seconds, 95)
        self.assertEqual(log.appointments.count(), 1)

    def test_webhook_is_idempotent(self):
        api_post(self.client, "/api/vapi/webhook/", END_OF_CALL)
        api_post(self.client, "/api/vapi/webhook/", END_OF_CALL)
        self.assertEqual(CallLog.objects.count(), 1)
        self.assertFalse(CallLog.objects.get().appointment_booked)

    def test_dashboard_conversion_reflects_bookings(self):
        self._book_during_call(get_or_create_call("call-123", "+15551234567"))
        api_post(self.client, "/api/vapi/webhook/", END_OF_CALL)
        other = dict(END_OF_CALL, message=dict(END_OF_CALL["message"], call={"id": "call-456"}))
        api_post(self.client, "/api/vapi/webhook/", other)

        User.objects.create_superuser("staff", "staff@example.com", "pw12345")
        self.client.login(username="staff", password="pw12345")
        res = self.client.get(reverse("dashboard"))
        self.assertEqual(res.context["total_calls"], 2)
        self.assertEqual(res.context["booked_calls"], 1)
        self.assertEqual(res.context["conversion"], 50)

    def test_log_call_is_no_longer_a_model_tool(self):
        from calls.agent.tools import TOOLS

        self.assertNotIn("log_call", {t["function"]["name"] for t in TOOLS})

    def test_chat_completions_creates_call_row_from_vapi_call_id(self):
        with mock.patch("calls.views.handle_conversation_turn", return_value={"text": "Hi!", "end_call": False}) as turn:
            res = api_post(self.client, "/api/vapi/chat/completions/", {
                "messages": [{"role": "user", "content": "hello"}],
                "call": {"id": "call-789", "customer": {"number": "+15551234567"}},
            })
        self.assertEqual(res.status_code, 200)
        call_log = turn.call_args.kwargs["call_log"]
        self.assertEqual(call_log.vapi_call_id, "call-789")
        self.assertEqual(json.loads(res.content)["choices"][0]["message"]["content"], "Hi!")
