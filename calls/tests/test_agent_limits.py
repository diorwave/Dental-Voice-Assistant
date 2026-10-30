from unittest import mock

from django.test import TestCase, override_settings

from calls.agent import receptionist

from .fakes import FakeCalendar, FakeOpenAI, assistant, clinic_time, patch_calendar, patch_now, patch_openai, tool_call


class AgentLimitTests(TestCase):
    @override_settings(AGENT_MAX_TOOL_ITERATIONS=3)
    def test_tool_loop_is_capped(self):
        looping = assistant(tool_calls=[tool_call("check_availability", {"date": "2026-11-02"})])
        fake_llm = FakeOpenAI(looping, repeat_last=True)
        with patch_openai(fake_llm), patch_calendar(FakeCalendar()), patch_now(clinic_time(2026, 11, 2, 7)), \
                self.assertLogs("calls.agent.receptionist", "WARNING"):
            result = receptionist.handle_conversation_turn([{"role": "user", "content": "any slots?"}])
        # 1 initial call + 3 follow-ups, then we stop instead of looping forever.
        self.assertEqual(len(fake_llm.requests), 4)
        self.assertTrue(result["text"])
        self.assertFalse(result["end_call"])

    @override_settings(OPENAI_TIMEOUT_SECONDS=7, OPENAI_MAX_RETRIES=0)
    def test_openai_client_has_timeout_and_bounded_retries(self):
        with mock.patch.object(receptionist, "_client", None), mock.patch("calls.agent.receptionist.OpenAI") as cls:
            receptionist.get_client()
        cls.assert_called_once_with(timeout=7, max_retries=0)

    @override_settings(TWILIO_ACCOUNT_SID="AC1", TWILIO_AUTH_TOKEN="t", TWILIO_TIMEOUT_SECONDS=4)
    def test_twilio_client_has_timeout(self):
        from calls.services import sms

        with mock.patch.object(sms, "_twilio_client", None):
            client = sms.get_twilio_client()
        self.assertEqual(client.http_client.timeout, 4)

    @override_settings(GOOGLE_API_TIMEOUT_SECONDS=6)
    def test_google_calendar_http_has_timeout(self):
        from calls.services import calendar

        with mock.patch.object(calendar, "_calendar_service", None), \
                mock.patch("google.oauth2.service_account.Credentials.from_service_account_file"), \
                mock.patch("googleapiclient.discovery.build") as build:
            calendar.get_calendar_service()
        http = build.call_args.kwargs["http"]
        self.assertEqual(http.http.timeout, 6)
