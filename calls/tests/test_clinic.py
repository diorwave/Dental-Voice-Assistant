from datetime import date, time

from django.conf import settings
from django.test import SimpleTestCase, override_settings

from calls import clinic
from calls.agent.prompts import get_receptionist_prompt


class ClinicTimezoneTests(SimpleTestCase):
    def test_django_time_zone_follows_clinic_timezone(self):
        self.assertEqual(settings.TIME_ZONE, settings.CLINIC_TIMEZONE)

    def test_prompt_names_the_configured_timezone(self):
        prompt = get_receptionist_prompt()
        self.assertNotIn("Pakistan", prompt)
        self.assertIn(settings.CLINIC_TIMEZONE, prompt)

    @override_settings(CLINIC_TIMEZONE="Europe/London")
    def test_prompt_follows_timezone_override(self):
        self.assertIn("Europe/London", get_receptionist_prompt())

    def test_prompt_hours_come_from_config(self):
        prompt = get_receptionist_prompt()
        self.assertIn("Saturday 9am to 2pm", prompt)
        self.assertIn("Sunday closed", prompt)


class BusinessHoursTests(SimpleTestCase):
    def test_weekday_saturday_and_sunday(self):
        self.assertEqual(clinic.hours_for(date(2026, 11, 2)), (time(8), time(18)))  # Monday
        self.assertEqual(clinic.hours_for(date(2026, 11, 7)), (time(9), time(14)))  # Saturday
        self.assertIsNone(clinic.hours_for(date(2026, 11, 8)))  # Sunday

    def test_durations(self):
        self.assertEqual(clinic.duration_for("new_patient"), 60)
        self.assertEqual(clinic.duration_for("returning"), 30)
        self.assertEqual(clinic.duration_for("unknown"), 30)
