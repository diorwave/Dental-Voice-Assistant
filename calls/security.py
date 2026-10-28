"""Authentication and rate limiting for the Vapi-facing API.

Both API endpoints run the real agent (OpenAI spend, Calendar writes, SMS) or
write call records, so neither may be callable anonymously. A request is
accepted when it carries either:

* the shared secret (``VAPI_SECRET``) as ``X-Vapi-Secret: <secret>`` (Vapi's
  server/webhook secret header) or ``Authorization: Bearer <secret>`` (Vapi's
  Custom LLM credential); or
* for the chat completions endpoint only, a logged-in *staff* session with a
  valid CSRF token — this is how the in-browser chat tester talks to the agent.

If VAPI_SECRET is unset, a placeholder, or shorter than 16 characters the API
fails closed (only staff sessions work) and `check --deploy` warns.

Rate limits use Django's cache. The default LocMemCache is per-process, so
limits are per worker; configure a shared cache (e.g. Redis) in production
for global limits.
"""
from __future__ import annotations

import functools
import hmac
import logging

from django.conf import settings
from django.core.cache import cache
from django.http import JsonResponse
from django.middleware.csrf import CsrfViewMiddleware

logger = logging.getLogger(__name__)

PRINCIPAL_VAPI = "vapi"
PRINCIPAL_STAFF = "staff"


def client_ip(request) -> str:
    if settings.TRUST_X_FORWARDED_FOR:
        # Use the right-most entry: it was appended by our own proxy. Entries to
        # its left are client-controlled and trivially spoofed.
        forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
        hops = [hop.strip() for hop in forwarded.split(",") if hop.strip()]
        if hops:
            return hops[-1]
    return request.META.get("REMOTE_ADDR", "unknown")


def _provided_secret(request) -> str:
    header = request.headers.get("X-Vapi-Secret")
    if header:
        return header
    auth = request.headers.get("Authorization", "")
    scheme, _, token = auth.partition(" ")
    return token.strip() if scheme.lower() == "bearer" else ""


MIN_SECRET_LENGTH = 16
_PLACEHOLDER_SECRETS = {"change-me", "changeme", "your-vapi-secret", "secret"}


def configured_secret() -> str:
    """VAPI_SECRET, or "" when it is missing, a known placeholder or too short —
    so a copied-over .env.example can never open the API."""
    secret = (settings.VAPI_SECRET or "").strip()
    if secret.lower() in _PLACEHOLDER_SECRETS or len(secret) < MIN_SECRET_LENGTH:
        return ""
    return secret


def has_valid_secret(request) -> bool:
    expected = configured_secret()
    provided = _provided_secret(request)
    if not expected or not provided:
        return False
    return hmac.compare_digest(provided.encode(), expected.encode())


def _csrf_ok(request) -> bool:
    # The view is csrf_exempt (Vapi can't send CSRF tokens), so enforce CSRF
    # explicitly for cookie-authenticated browser requests.
    return CsrfViewMiddleware(lambda r: None).process_view(request, None, (), {}) is None


def authenticate(request, *, allow_staff_session: bool) -> str | None:
    if has_valid_secret(request):
        return PRINCIPAL_VAPI
    user = getattr(request, "user", None)
    if allow_staff_session and user is not None and user.is_active and user.is_staff and _csrf_ok(request):
        return PRINCIPAL_STAFF
    return None


def is_rate_limited(scope: str, ident, limit: int, window_seconds: int = 60) -> bool:
    """Fixed-window counter. Returns True once ``limit`` is exceeded in the window."""
    if limit <= 0:
        return False
    key = f"ratelimit:{scope}:{ident}"
    cache.add(key, 0, timeout=window_seconds)
    try:
        count = cache.incr(key)
    except ValueError:  # expired between add() and incr()
        cache.set(key, 1, timeout=window_seconds)
        count = 1
    return count > limit


def too_many_requests() -> JsonResponse:
    return JsonResponse({"error": "Too many requests"}, status=429)


def require_api_auth(*, allow_staff_session: bool = False):
    """Reject unauthenticated requests with 401 (and rate-limit the attempts)."""

    def decorator(view):
        @functools.wraps(view)
        def wrapped(request, *args, **kwargs):
            principal = authenticate(request, allow_staff_session=allow_staff_session)
            if principal is None:
                ip = client_ip(request)
                if is_rate_limited("unauthenticated", ip, settings.API_RATE_LIMIT_UNAUTHENTICATED_PER_MINUTE):
                    return too_many_requests()
                logger.warning("[AUTH] rejected %s %s from %s", request.method, request.path, ip)
                return JsonResponse({"error": "Unauthorized"}, status=401)
            if principal == PRINCIPAL_STAFF and is_rate_limited(
                "staff", request.user.pk, settings.API_RATE_LIMIT_STAFF_PER_MINUTE
            ):
                return too_many_requests()
            request.api_principal = principal
            return view(request, *args, **kwargs)

        return wrapped

    return decorator
