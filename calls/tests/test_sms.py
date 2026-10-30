from datetime import date, time
from unittest import mock

from django.test import TestCase, override_settings

from calls.agent import receptionist
from calls.agent.tools import TOOLS
from calls.models import Appointment
from calls.services import sms

from .fakes import FakeCalendar, clinic_time, patch_calendar, patch_now

TWILIO = dict(
    TWILIO_ACCOUNT_SID="AC123",
    TWILIO_AUTH_TOKEN="token",
    TWILIO_PHONE_NUMBER="+15550001111",
    BACKGROUND_TASKS_EAGER=True,
)
BOOK_ARGS = {
    "date": "2026-11-02",
    "time": "10:00",
    "patient_name": "Jane Doe",
    "patient_phone": "+15551234567",
    "appointment_type": "returning",
}


def make_appointment(**overrides):
    fields = dict(
        patient_name="Jane Doe", patient_phone="+15551234567", appointment_type="returning",
        date=date(2026, 11, 2), time=time(10),
    )
    fields.update(overrides)
    return Appointment.objects.create(**fields)


class FakeTwilio:
    def __init__(self, fail=False):
        self.sent = []
        self.fail = fail
        self.messages = self

    def create(self, body, from_, to):
        if self.fail:
            raise RuntimeError("twilio down")
        self.sent.append({"body": body, "from": from_, "to": to})
        return mock.Mock(sid=f"SM{len(self.sent)}")


@override_settings(**TWILIO)
class SmsTests(TestCase):
    def setUp(self):
        self.twilio = FakeTwilio()
        patcher = mock.patch("calls.services.sms.get_twilio_client", return_value=self.twilio)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_model_cannot_send_arbitrary_sms(self):
        names = {t["function"]["name"] for t in TOOLS}
        self.assertNotIn("send_sms", names)
        result = receptionist.execute_tool("send_sms", {"to": "+15550000000", "message": "spam"})
        self.assertEqual(result["error"], "unknown_tool")
        self.assertEqual(self.twilio.sent, [])

    def test_confirmation_uses_fixed_template_and_appointment_phone(self):
        appt = make_appointment()
        self.assertTrue(sms.queue_booking_confirmation(appt))
        self.assertEqual(len(self.twilio.sent), 1)
        sent = self.twilio.sent[0]
        self.assertEqual(sent["to"], "+15551234567")
        self.assertEqual(
            sent["body"],
            "Bright Smile Dental: your returning appointment is confirmed for Monday, "
            "November 2 at 10:00 AM. Reply or call us to make changes.",
        )
        appt.refresh_from_db()
        self.assertEqual((appt.sms_status, appt.sms_sid), (Appointment.SMS_SENT, "SM1"))

    @override_settings(SMS_DAILY_LIMIT_PER_NUMBER=2)
    def test_daily_limit_per_number(self):
        results = [sms.queue_booking_confirmation(make_appointment(time=time(9 + i))) for i in range(3)]
        self.assertEqual(results, [True, True, False])
        self.assertEqual(len(self.twilio.sent), 2)
        self.assertEqual(Appointment.objects.filter(sms_status=Appointment.SMS_SKIPPED).count(), 1)

    def test_failure_is_recorded_not_swallowed(self):
        self.twilio.fail = True
        appt = make_appointment()
        self.assertTrue(sms.queue_booking_confirmation(appt))
        appt.refresh_from_db()
        self.assertEqual(appt.sms_status, Appointment.SMS_FAILED)
        self.assertIn("twilio down", appt.sms_error)

    @override_settings(TWILIO_ACCOUNT_SID=None)
    def test_unconfigured_twilio_skips(self):
        appt = make_appointment()
        self.assertFalse(sms.queue_booking_confirmation(appt))
        appt.refresh_from_db()
        self.assertEqual(appt.sms_status, Appointment.SMS_SKIPPED)

    def test_successful_booking_queues_exactly_one_confirmation(self):
        with patch_calendar(FakeCalendar()), patch_now(clinic_time(2026, 11, 2, 7)):
            first = receptionist.execute_tool("book_appointment", BOOK_ARGS)
            repeat = receptionist.execute_tool("book_appointment", BOOK_ARGS)
        self.assertEqual(first["sms_confirmation"], "queued")
        self.assertNotIn("sms_confirmation", repeat)
        self.assertEqual(len(self.twilio.sent), 1)
