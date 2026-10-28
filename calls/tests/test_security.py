from unittest import mock

from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from calls.models import CallLog

from .helpers import TEST_SECRET, api_post

CHAT = "/api/vapi/chat/completions/"
WEBHOOK = "/api/vapi/webhook/"
MESSAGES = {"messages": [{"role": "user", "content": "hi"}]}
REPLY = {"text": "Hello!", "end_call": False}


@override_settings(VAPI_SECRET=TEST_SECRET)
class ApiAuthTests(TestCase):
    def setUp(self):
        cache.clear()
        patcher = mock.patch("calls.views.handle_conversation_turn", return_value=REPLY)
        self.turn = patcher.start()
        self.addCleanup(patcher.stop)

    def test_chat_completions_rejects_missing_or_wrong_secret(self):
        for secret in (None, "wrong", ""):
            with self.subTest(secret=secret):
                res = api_post(self.client, CHAT, MESSAGES, secret=secret)
                self.assertEqual(res.status_code, 401)
        self.turn.assert_not_called()

    def test_chat_completions_accepts_vapi_secret_header(self):
        res = api_post(self.client, CHAT, MESSAGES)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["choices"][0]["message"]["content"], "Hello!")

    def test_chat_completions_accepts_bearer_token(self):
        res = api_post(self.client, CHAT, MESSAGES, secret=None, Authorization=f"Bearer {TEST_SECRET}")
        self.assertEqual(res.status_code, 200)

    def test_webhook_post_requires_secret(self):
        report = {"message": {"type": "end-of-call-report", "call": {"id": "fake"}}}
        self.assertEqual(api_post(self.client, WEBHOOK, report, secret=None).status_code, 401)
        self.assertFalse(CallLog.objects.exists())
        self.assertEqual(api_post(self.client, WEBHOOK, report).status_code, 200)
        self.assertTrue(CallLog.objects.exists())

    def test_webhook_health_check_stays_public(self):
        self.assertEqual(self.client.get(WEBHOOK).status_code, 200)

    @override_settings(VAPI_SECRET="")
    def test_fails_closed_when_no_secret_is_configured(self):
        self.assertEqual(api_post(self.client, CHAT, MESSAGES, secret="").status_code, 401)
        self.assertEqual(api_post(self.client, CHAT, MESSAGES, secret=None, Authorization="Bearer ").status_code, 401)

    def test_staff_session_can_use_chat_with_csrf(self):
        User.objects.create_superuser("staff", "staff@example.com", "pw12345")
        client = Client(enforce_csrf_checks=True)
        client.login(username="staff", password="pw12345")
        # Without a CSRF token the cookie session is not enough.
        self.assertEqual(api_post(client, CHAT, MESSAGES, secret=None).status_code, 401)
        # With the token rendered by the chat page it works.
        page = client.get(reverse("chat"))
        token = page.context["csrf_token"]
        res = api_post(client, CHAT, MESSAGES, secret=None, **{"X-CSRFToken": str(token)})
        self.assertEqual(res.status_code, 200)

    def test_non_staff_session_is_rejected(self):
        User.objects.create_user("patient", password="pw12345")
        self.client.login(username="patient", password="pw12345")
        self.assertEqual(api_post(self.client, CHAT, MESSAGES, secret=None).status_code, 401)

    def test_landing_page_hides_chat_tester_from_anonymous_users(self):
        res = self.client.get(reverse("landing"))
        self.assertNotContains(res, 'id="chatbox"')
        self.assertContains(res, "Staff sign-in")


@override_settings(VAPI_SECRET=TEST_SECRET)
class RateLimitTests(TestCase):
    def setUp(self):
        cache.clear()
        patcher = mock.patch("calls.views.handle_conversation_turn", return_value=REPLY)
        patcher.start()
        self.addCleanup(patcher.stop)

    @override_settings(API_RATE_LIMIT_PER_CALL_PER_MINUTE=2)
    def test_per_call_limit(self):
        payload = dict(MESSAGES, call={"id": "call-1"})
        codes = [api_post(self.client, CHAT, payload).status_code for _ in range(3)]
        self.assertEqual(codes, [200, 200, 429])
        # A different call is unaffected.
        self.assertEqual(api_post(self.client, CHAT, dict(MESSAGES, call={"id": "call-2"})).status_code, 200)

    @override_settings(API_RATE_LIMIT_UNAUTHENTICATED_PER_MINUTE=2)
    def test_unauthenticated_attempts_are_limited_per_ip(self):
        codes = [api_post(self.client, CHAT, MESSAGES, secret="guess").status_code for _ in range(3)]
        self.assertEqual(codes, [401, 401, 429])

    @override_settings(API_RATE_LIMIT_STAFF_PER_MINUTE=1)
    def test_staff_limit(self):
        User.objects.create_superuser("staff", "staff@example.com", "pw12345")
        self.client.login(username="staff", password="pw12345")
        codes = [api_post(self.client, CHAT, MESSAGES, secret=None).status_code for _ in range(2)]
        self.assertEqual(codes, [200, 429])


class SecretAndProxyTests(TestCase):
    def setUp(self):
        cache.clear()

    def test_placeholder_or_short_secret_never_authenticates(self):
        for weak in ("change-me", "secret", "short-secret"):
            with self.subTest(weak=weak), override_settings(VAPI_SECRET=weak):
                self.assertEqual(api_post(self.client, CHAT, MESSAGES, secret=weak).status_code, 401)

    def test_deploy_check_warns_about_missing_secret(self):
        from calls.checks import vapi_secret_check

        with override_settings(VAPI_SECRET="change-me"):
            self.assertEqual([w.id for w in vapi_secret_check(None)], ["calls.W001"])
        with override_settings(VAPI_SECRET=TEST_SECRET + "-long-enough"):
            self.assertEqual(vapi_secret_check(None), [])

    @override_settings(TRUST_X_FORWARDED_FOR=True)
    def test_client_ip_uses_proxy_appended_hop(self):
        from django.test import RequestFactory

        from calls.security import client_ip

        request = RequestFactory().get("/", HTTP_X_FORWARDED_FOR="1.2.3.4, 203.0.113.9", REMOTE_ADDR="10.0.0.1")
        self.assertEqual(client_ip(request), "203.0.113.9")
