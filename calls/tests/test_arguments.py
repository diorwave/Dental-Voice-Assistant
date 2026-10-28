from datetime import date, time

from django.test import SimpleTestCase

from calls.agent.arguments import ToolArgumentError, normalize_phone, parse_date, parse_time
from calls.agent.receptionist import execute_tool


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


class BookingRequestTests(SimpleTestCase):
    def test_normalizes_all_fields(self):
        from calls.agent.arguments import BookingRequest

        req = BookingRequest.from_args({
            "date": "2026-11-2", "time": "2:30 PM", "patient_name": "  Jane Doe ",
            "patient_phone": "(555) 123-4567", "appointment_type": "new_patient",
        })
        self.assertEqual(
            (req.date, req.time, req.patient_name, req.patient_phone),
            (date(2026, 11, 2), time(14, 30), "Jane Doe", "+15551234567"),
        )

    def test_unknown_appointment_type(self):
        result = execute_tool("book_appointment", {
            "date": "2026-11-02", "time": "10:00", "patient_name": "J",
            "patient_phone": "+15551234567", "appointment_type": "vip",
        })
        self.assertEqual(result["error"], "invalid_appointment_type")
