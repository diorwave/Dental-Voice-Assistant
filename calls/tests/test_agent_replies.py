from unittest import mock

from django.test import SimpleTestCase, TestCase, override_settings

from calls.agent import receptionist
from calls.models import Appointment

from .fakes import FakeCalendar, FakeOpenAI, assistant, clinic_time, patch_calendar, patch_now, patch_openai, tool_call
from .test_sms import BOOK_ARGS, TWILIO, FakeTwilio


class SmsQueueFailureTests(TestCase):
    def test_booking_still_succeeds_if_sms_queueing_raises(self):
        with patch_calendar(FakeCalendar()), patch_now(clinic_time(2026, 11, 2, 7)), \
                mock.patch("calls.agent.receptionist.queue_booking_confirmation", side_effect=RuntimeError("db")), \
                self.assertLogs("calls.agent.receptionist", "ERROR"):
            result = receptionist.execute_tool("book_appointment", BOOK_ARGS)
        self.assertTrue(result["success"])
        self.assertEqual(result["sms_confirmation"], "not_sent")


class FallbackReplyTests(SimpleTestCase):
    def test_booking_success_with_sms(self):
        text = receptionist.fallback_reply("book_appointment", {
            "success": True, "start": "2026-11-02T10:00:00-05:00", "sms_confirmation": "queued",
        })
        self.assertIn("Monday, November 2 at 10:00 AM", text)
        self.assertIn("text confirmation", text)

    def test_booking_success_without_sms_does_not_claim_a_text(self):
        text = receptionist.fallback_reply("book_appointment", {
            "success": True, "start": "2026-11-02T10:00:00-05:00", "sms_confirmation": "not_sent",
        })
        self.assertNotIn("text", text)

    def test_booking_failure_never_claims_success(self):
        for result in (
            {"success": False, "error": "slot_taken", "alternatives": ["09:30", "11:00"]},
            {"success": False, "error": "tool_failed"},
            {"error": "boom"},
            None,
        ):
            text = receptionist.fallback_reply("book_appointment", result)
            self.assertNotIn("all set", text)
        self.assertIn("09:30 or 11:00", receptionist.fallback_reply(
            "book_appointment", {"success": False, "error": "slot_taken", "alternatives": ["09:30", "11:00"]}
        ))


@override_settings(**TWILIO)
class AgentLoopTests(TestCase):
    def test_empty_model_reply_after_failed_booking_is_truthful(self):
        fake_llm = FakeOpenAI(assistant(tool_calls=[tool_call("book_appointment", BOOK_ARGS)]), assistant(""))
        cal = FakeCalendar()
        cal.add_timed(clinic_time(2026, 11, 2, 10), clinic_time(2026, 11, 2, 10, 30))
        with patch_openai(fake_llm), patch_calendar(cal), patch_now(clinic_time(2026, 11, 2, 7)), \
                mock.patch("calls.services.sms.get_twilio_client", return_value=FakeTwilio()):
            result = receptionist.handle_conversation_turn([{"role": "user", "content": "book 10am"}])
        self.assertIn("isn't available", result["text"])
        self.assertFalse(Appointment.objects.exists())
