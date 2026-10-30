from unittest import mock

from django.test import SimpleTestCase, TestCase, override_settings

from calls import background


class _InlineExecutor:
    def __init__(self):
        self.submitted = 0

    def submit(self, fn):
        self.submitted += 1
        fn()


@override_settings(BACKGROUND_TASKS_EAGER=False)
class BackgroundTests(SimpleTestCase):
    def test_task_manages_connections_and_logs_errors(self):
        def boom():
            raise ValueError("x")

        with mock.patch.object(background, "_get_executor", return_value=_InlineExecutor()), \
                mock.patch("calls.background.close_old_connections") as close, \
                self.assertLogs("calls.background", "ERROR"):
            background.run_in_background(boom)
        # Fresh connection before the task and cleanup after it, even on failure.
        self.assertEqual(close.call_count, 2)

    def test_tasks_go_through_the_bounded_pool(self):
        executor = _InlineExecutor()
        seen = []
        with mock.patch.object(background, "_get_executor", return_value=executor), \
                mock.patch("calls.background.close_old_connections"):
            background.run_in_background(seen.append, 1)
        self.assertEqual((executor.submitted, seen), (1, [1]))

    @override_settings(BACKGROUND_TASK_WORKERS=2)
    def test_pool_size_comes_from_settings(self):
        with mock.patch.object(background, "_executor", None):
            pool = background._get_executor()
            try:
                self.assertEqual(pool._max_workers, 2)
            finally:
                pool.shutdown(wait=False)

    @override_settings(BACKGROUND_TASKS_EAGER=True)
    def test_eager_mode_runs_inline(self):
        seen = []
        background.run_in_background(seen.append, "x")
        self.assertEqual(seen, ["x"])


class SmsUsesBackgroundRunnerTests(TestCase):
    @override_settings(TWILIO_ACCOUNT_SID="AC1", TWILIO_AUTH_TOKEN="t", TWILIO_PHONE_NUMBER="+15550001111")
    def test_confirmation_is_sent_through_the_background_runner(self):
        from datetime import date, time

        from calls.models import Appointment
        from calls.services import sms

        appt = Appointment.objects.create(
            patient_name="J", patient_phone="+15551234567", appointment_type="returning",
            date=date(2026, 11, 2), time=time(10),
        )
        with mock.patch("calls.background.run_in_background") as run, mock.patch("threading.Thread") as thread:
            self.assertTrue(sms.queue_booking_confirmation(appt))
        run.assert_called_once_with(sms.deliver_booking_confirmation, appt.pk)
        thread.assert_not_called()
