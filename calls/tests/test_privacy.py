from datetime import date, time, timedelta
from io import StringIO

from django.core.management import call_command
from django.test import SimpleTestCase, TestCase, override_settings
from django.utils import timezone

from calls.models import Appointment, CallLog
from calls.privacy import mask_phone, redact

from .fakes import FakeCalendar, FakeOpenAI, assistant, clinic_time, patch_calendar, patch_now, patch_openai, tool_call
from .helpers import TEST_SECRET, api_post

PHONE = "+15551234567"


class MaskingTests(SimpleTestCase):
    def test_mask_phone(self):
        self.assertEqual(mask_phone(PHONE), "***4567")
        self.assertEqual(mask_phone("(555) 123-4567"), "***4567")
        self.assertEqual(mask_phone(None), "-")
        self.assertEqual(mask_phone("12"), "***")

    def test_redact_nested(self):
        data = {"patient_name": "Jane Doe", "patient_phone": PHONE, "date": "2026-11-02",
                "nested": [{"to": PHONE}]}
        self.assertEqual(redact(data), {
            "patient_name": "[redacted]", "patient_phone": "***4567", "date": "2026-11-02",
            "nested": [{"to": "***4567"}],
        })


@override_settings(VAPI_SECRET=TEST_SECRET)
class LogRedactionTests(TestCase):
    def test_info_logs_do_not_contain_patient_data(self):
        args = {"date": "2026-11-02", "time": "10:00", "patient_name": "Jane Doe",
                "patient_phone": PHONE, "appointment_type": "returning"}
        fake_llm = FakeOpenAI(assistant(tool_calls=[tool_call("book_appointment", args)]), assistant("Booked!"))
        with patch_openai(fake_llm), patch_calendar(FakeCalendar()), patch_now(clinic_time(2026, 11, 2, 7)), \
                self.assertLogs(level="INFO") as logs:
            api_post(self.client, "/api/vapi/chat/completions/", {
                "messages": [{"role": "user", "content": "book me"}],
                "call": {"id": "c1", "customer": {"number": PHONE}},
            })
            api_post(self.client, "/api/vapi/webhook/", {"message": {
                "type": "end-of-call-report", "call": {"id": "c1", "customer": {"number": PHONE}},
            }})
        output = "\n".join(logs.output)
        self.assertIn("[TOOL] book_appointment", output)
        self.assertNotIn("Jane", output)
        self.assertNotIn("5551234567", output)
        self.assertIn("***4567", output)


class PurgeCommandTests(TestCase):
    def test_purges_old_call_data_only(self):
        old = CallLog.objects.create(caller_phone=PHONE, call_summary="Patient said ...")
        CallLog.objects.filter(pk=old.pk).update(created_at=timezone.now() - timedelta(days=100))
        recent = CallLog.objects.create(caller_phone=PHONE, call_summary="Recent call")
        appt = Appointment.objects.create(patient_name="Jane", patient_phone=PHONE, appointment_type="returning",
                                          date=date(2020, 1, 6), time=time(10))

        out = StringIO()
        call_command("purge_call_data", "--days", "90", stdout=out)
        self.assertIn("Purged 1 call log(s)", out.getvalue())

        for obj in (old, recent, appt):
            obj.refresh_from_db()
        self.assertEqual((old.call_summary, old.caller_phone), ("[purged]", "***4567"))
        self.assertEqual(recent.call_summary, "Recent call")
        self.assertEqual(appt.patient_name, "Jane")  # appointments untouched by default

        call_command("purge_call_data", "--days", "90", "--appointments", stdout=StringIO())
        appt.refresh_from_db()
        self.assertEqual((appt.patient_name, appt.patient_phone), ("[purged]", "***4567"))

    def test_dry_run_writes_nothing(self):
        old = CallLog.objects.create(caller_phone=PHONE, call_summary="secret")
        CallLog.objects.filter(pk=old.pk).update(created_at=timezone.now() - timedelta(days=100))
        out = StringIO()
        call_command("purge_call_data", "--dry-run", stdout=out)
        self.assertIn("Would purge 1", out.getvalue())
        old.refresh_from_db()
        self.assertEqual(old.call_summary, "secret")
