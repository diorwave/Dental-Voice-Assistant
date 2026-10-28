from datetime import date, time

from django.test import SimpleTestCase, TestCase

from calls.agent.arguments import (
    AvailabilityRequest,
    BookingRequest,
    ToolArgumentError,
    normalize_phone,
    parse_date,
    parse_time,
)
from calls.agent.receptionist import execute_tool
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


class ArgumentParsingTests(SimpleTestCase):
    def test_dates(self):
        self.assertEqual(parse_date("2026-11-02"), date(2026, 11, 2))
        self.assertEqual(parse_date("2026-1-5"), date(2026, 1, 5))
        for bad in ("", None, "11/02/2026", "2026-13-01", "tomorrow"):
            with self.assertRaises(ToolArgumentError) as ctx:
                parse_date(bad)
            self.assertEqual(ctx.exception.code, "invalid_date")

    def test_times(self):
        self.assertEqual(parse_time("14:30"), time(14, 30))
        self.assertEqual(parse_time("9:30"), time(9, 30))
        self.assertEqual(parse_time("2:30 PM"), time(14, 30))
        self.assertEqual(parse_time("2pm"), time(14, 0))
        self.assertEqual(parse_time("10:00:00"), time(10, 0))
        for bad in ("", None, "25:00", "noon", "1430"):
            with self.assertRaises(ToolArgumentError) as ctx:
                parse_time(bad)
            self.assertEqual(ctx.exception.code, "invalid_time")

    def test_phone_normalization(self):
        self.assertEqual(normalize_phone("(555) 123-4567"), "+15551234567")
        self.assertEqual(normalize_phone("1-555-123-4567"), "+15551234567")
        self.assertEqual(normalize_phone("+44 20 7946 0958"), "+442079460958")
        for bad in ("", "12345", "call me", "+0123456789"):
            with self.assertRaises(ToolArgumentError):
                normalize_phone(bad)

    def test_missing_field_is_a_structured_error(self):
        result = execute_tool("book_appointment", {"date": "2026-11-02", "time": "10:00"})
        self.assertFalse(result["success"])
        self.assertEqual(result["error"], "missing_patient_name")

    def test_malformed_date_is_a_structured_error(self):
        result = execute_tool("check_availability", {"date": "next tuesday"})
        self.assertEqual(result, {"success": False, "error": "invalid_date", "message": result["message"]})


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


class BookingTests(TestCase):
    def book(self, request, fake, now=MONDAY_MORNING):
        with patch_calendar(fake), patch_now(now):
            return calendar.book_appointment(request)

    def test_successful_booking_creates_event_and_row(self):
        fake = FakeCalendar()
        result = self.book(booking(), fake)
        self.assertTrue(result["success"])
        self.assertEqual(len(fake.inserted), 1)
        appt = Appointment.objects.get()
        self.assertEqual(appt.google_event_id, fake.inserted[0]["id"])
        self.assertEqual(appt.duration_minutes, 30)

    def test_taken_slot_is_not_reported_as_success(self):
        fake = FakeCalendar()
        fake.add_timed(clinic_time(2026, 11, 2, 10), clinic_time(2026, 11, 2, 11))
        result = self.book(booking(), fake)
        self.assertFalse(result["success"])
        self.assertEqual(result["error"], "slot_taken")
        self.assertEqual(result["alternatives"], ["09:30", "11:00"])
        self.assertEqual(fake.inserted, [])
        self.assertFalse(Appointment.objects.exists())

    def test_slot_held_by_another_patient_in_db_is_taken(self):
        fake = FakeCalendar()
        self.book(booking(), fake)
        result = self.book(booking(patient_name="Other", patient_phone="+15559876543"), fake)
        self.assertEqual(result["error"], "slot_taken")
        self.assertEqual(Appointment.objects.count(), 1)

    def test_repeat_booking_by_same_patient_is_idempotent(self):
        fake = FakeCalendar()
        first = self.book(booking(), fake)
        second = self.book(booking(), fake)
        self.assertTrue(second["success"])
        self.assertEqual(first["appointment_id"], second["appointment_id"])
        self.assertEqual(len(fake.inserted), 1)

    def test_in_flight_reservation_blocks_overlapping_booking(self):
        # Another request reserved 10:00-11:00 but its Calendar insert hasn't landed.
        Appointment.objects.create(
            patient_name="A", patient_phone="+15550000001", appointment_type="new_patient",
            date=date(2026, 11, 2), time=time(10), duration_minutes=60,
        )
        result = self.book(booking(time="10:30", patient_phone="+15559876543"), FakeCalendar())
        self.assertEqual(result["error"], "slot_taken")

    def test_same_patient_retry_while_first_booking_in_flight_is_not_confirmed(self):
        Appointment.objects.create(
            patient_name="Jane Doe", patient_phone="+15551234567", appointment_type="returning",
            date=date(2026, 11, 2), time=time(10),
        )
        result = self.book(booking(), FakeCalendar())
        self.assertFalse(result["success"])
        self.assertEqual(result["error"], "booking_in_progress")

    def test_deleting_the_calendar_event_frees_the_slot(self):
        fake = FakeCalendar()
        first = self.book(booking(), fake)
        fake.items.clear()  # staff cancelled by deleting the event in Google Calendar
        result = self.book(booking(patient_name="Other", patient_phone="+15559876543"), fake)
        self.assertTrue(result["success"])
        self.assertEqual(Appointment.objects.get(pk=first["appointment_id"]).status, Appointment.STATUS_CANCELLED)
        self.assertEqual(Appointment.objects.filter(status=Appointment.STATUS_BOOKED).count(), 1)

    def test_abandoned_reservation_is_released(self):
        from datetime import timedelta

        from django.utils import timezone

        stale = Appointment.objects.create(
            patient_name="A", patient_phone="+15550000001", appointment_type="returning",
            date=date(2026, 11, 2), time=time(10),
        )
        Appointment.objects.filter(pk=stale.pk).update(created_at=timezone.now() - timedelta(hours=1))
        result = self.book(booking(patient_phone="+15559876543"), FakeCalendar())
        self.assertTrue(result["success"])
        stale.refresh_from_db()
        self.assertEqual(stale.status, Appointment.STATUS_CANCELLED)

    def test_unique_constraint_guards_same_start(self):
        from django.db import IntegrityError, transaction

        Appointment.objects.create(
            patient_name="A", patient_phone="+15550000001", appointment_type="returning",
            date=date(2026, 11, 2), time=time(10),
        )
        with self.assertRaises(IntegrityError), transaction.atomic():
            Appointment.objects.create(
                patient_name="B", patient_phone="+15550000002", appointment_type="returning",
                date=date(2026, 11, 2), time=time(10),
            )

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

    def test_calendar_failure_releases_the_reservation(self):
        fake = FakeCalendar()
        fake.fail_insert = True
        with self.assertRaises(RuntimeError):
            self.book(booking(), fake)
        self.assertFalse(Appointment.objects.exists())
