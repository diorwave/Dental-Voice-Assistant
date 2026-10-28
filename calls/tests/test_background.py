from unittest import mock

from django.test import SimpleTestCase, override_settings

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


class SendSmsToolTests(SimpleTestCase):
    def test_send_sms_tool_uses_background_runner_not_raw_threads(self):
        from calls.agent import receptionist

        with mock.patch("calls.agent.receptionist.run_in_background") as run, \
                mock.patch("threading.Thread") as thread:
            result = receptionist.execute_tool("send_sms", {"to": "+15551234567", "message": "hi"})
        run.assert_called_once()
        thread.assert_not_called()
        self.assertTrue(result["success"])
