from datetime import date

from django.test import TestCase

from calls.agent.arguments import AvailabilityRequest, BookingRequest, ToolArgumentError
from calls.models import Appointment
from calls.services import calendar

from .fakes import FakeCalendar, clinic_time, patch_calendar, patch_now

# Monday 2 Nov 2026, 07:00 clinic time — before opening.
MONDAY_MORNING = clinic_time(2026, 11, 2, 7, 0)


def booking(**overrides):
    args = {
        "date": "2026-11-02",
        "time": "10:00",
        "patient_name": "Jane Doe",
        "patient_phone": "+15551234567",
        "appointment_type": "returning",
    }
    args.update(overrides)
    return BookingRequest.from_args(args)


class AvailabilityTests(TestCase):
    def check(self, day, appointment_type="returning", now=MONDAY_MORNING, fake=None):
        fake = fake or FakeCalendar()
        with patch_calendar(fake), patch_now(now):
            return calendar.check_availability(AvailabilityRequest(date=day, appointment_type=appointment_type))

    def test_weekday_offers_full_hours_ending_at_close(self):
        slots = self.check(date(2026, 11, 2))["available_slots"]
        self.assertEqual(slots[0], "08:00")
        self.assertEqual(slots[-1], "17:30")  # 30-min visit ends 18:00

    def test_new_patient_slots_must_fit_sixty_minutes(self):
        slots = self.check(date(2026, 11, 2), "new_patient")["available_slots"]
        self.assertEqual(slots[-1], "17:00")

    def test_slot_is_busy_if_any_part_of_the_appointment_overlaps(self):
        fake = FakeCalendar()
        fake.add_timed(clinic_time(2026, 11, 2, 10, 30), clinic_time(2026, 11, 2, 11, 0))
        slots = self.check(date(2026, 11, 2), "new_patient", fake=fake)["available_slots"]
        self.assertNotIn("10:00", slots)  # 10:00-11:00 would overlap 10:30
        self.assertNotIn("10:30", slots)
        self.assertIn("09:30", slots)
        self.assertIn("11:00", slots)

    def test_saturday_uses_saturday_hours(self):
        slots = self.check(date(2026, 11, 7))["available_slots"]
        self.assertEqual((slots[0], slots[-1]), ("09:00", "13:30"))

    def test_sunday_is_closed(self):
        result = self.check(date(2026, 11, 8))
        self.assertTrue(result["closed"])
        self.assertEqual(result["available_slots"], [])

    def test_past_slots_today_are_not_offered(self):
        slots = self.check(date(2026, 11, 2), now=clinic_time(2026, 11, 2, 12, 10))["available_slots"]
        self.assertEqual(slots[0], "12:30")

    def test_past_date_is_rejected(self):
        with self.assertRaises(ToolArgumentError) as ctx:
            self.check(date(2026, 11, 1))
        self.assertEqual(ctx.exception.code, "date_in_past")

    def test_all_day_event_blocks_the_day_without_crashing(self):
        fake = FakeCalendar()
        fake.add_all_day("2026-11-02", "2026-11-03")
        self.assertEqual(self.check(date(2026, 11, 2), fake=fake)["available_slots"], [])

    def test_transparent_events_do_not_block(self):
        fake = FakeCalendar()
        fake.add_timed(clinic_time(2026, 11, 2, 8), clinic_time(2026, 11, 2, 18), transparency="transparent")
        self.assertEqual(self.check(date(2026, 11, 2), fake=fake)["total_available"], 20)


class BookingWindowTests(TestCase):
    def book(self, request, fake, now=MONDAY_MORNING):
        with patch_calendar(fake), patch_now(now):
            return calendar.book_appointment(request)

    def test_booking_inside_hours_succeeds(self):
        fake = FakeCalendar()
        result = self.book(booking(), fake)
        self.assertTrue(result["success"])
        self.assertEqual(len(fake.inserted), 1)
        self.assertEqual(Appointment.objects.get().duration_minutes, 30)

    def test_out_of_hours_and_closed_days_are_rejected(self):
        cases = [
            (booking(time="17:30", appointment_type="new_patient"), "outside_business_hours"),
            (booking(time="07:30"), "outside_business_hours"),
            (booking(date="2026-11-08"), "clinic_closed"),
            (booking(date="2026-11-07", time="14:00"), "outside_business_hours"),
        ]
        for request, code in cases:
            with self.subTest(code=code, request=request), self.assertRaises(ToolArgumentError) as ctx:
                self.book(request, FakeCalendar())
            self.assertEqual(ctx.exception.code, code)

    def test_past_time_is_rejected(self):
        with self.assertRaises(ToolArgumentError) as ctx:
            self.book(booking(time="09:00"), FakeCalendar(), now=clinic_time(2026, 11, 2, 9, 30))
        self.assertEqual(ctx.exception.code, "time_in_past")
