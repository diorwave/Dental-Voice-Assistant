import os
from pathlib import Path
from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent


def env_bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).strip().lower() in ("1", "true", "yes", "on")


def env_list(name: str, default: str = "") -> list[str]:
    return [item.strip() for item in os.getenv(name, default).split(",") if item.strip()]


# Secure by default: DEBUG must be switched on explicitly for local development.
DEBUG = env_bool("DEBUG", False)

_INSECURE_SECRET_KEYS = {"", "your-secret-key-here", "django-insecure-change-me-in-production"}
SECRET_KEY = os.getenv("SECRET_KEY", "")
if SECRET_KEY in _INSECURE_SECRET_KEYS:
    if not DEBUG:
        raise ImproperlyConfigured(
            "SECRET_KEY must be set to a unique, unpredictable value when DEBUG is off. "
            "Generate one with: python3 -c \"import secrets; print(secrets.token_urlsafe(50))\""
        )
    SECRET_KEY = "django-insecure-local-development-only"

ALLOWED_HOSTS = env_list("ALLOWED_HOSTS", "localhost,127.0.0.1")

CSRF_TRUSTED_ORIGINS = env_list("CSRF_TRUSTED_ORIGINS")
if DEBUG:
    # Convenience for local testing through an ngrok tunnel (Vapi, admin login).
    # In production list your real domain(s) in ALLOWED_HOSTS / CSRF_TRUSTED_ORIGINS.
    ALLOWED_HOSTS += [".ngrok-free.dev", ".ngrok-free.app", ".ngrok.io"]
    CSRF_TRUSTED_ORIGINS += [
        "https://*.ngrok-free.dev",
        "https://*.ngrok-free.app",
        "https://*.ngrok.io",
    ]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "calls",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "receptionist_project.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "receptionist_project.wsgi.application"

if env_bool("USE_SQLITE"):
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": os.getenv("DB_NAME", "ai_receptionist"),
            "USER": os.getenv("DB_USER", "postgres"),
            "PASSWORD": os.getenv("DB_PASSWORD", ""),
            "HOST": os.getenv("DB_HOST", "db"),
            "PORT": os.getenv("DB_PORT", "5432"),
        }
    }

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# ─── Clinic ──────────────────────────────────────────────────
# The clinic's local timezone drives the agent's clock, calendar slots and the
# dashboard's notion of "today". Keep Django's TIME_ZONE in sync with it.
CLINIC_TIMEZONE = os.getenv("CLINIC_TIMEZONE", "America/New_York")
CLINIC_NAME = os.getenv("CLINIC_NAME", "Bright Smile Dental")

# Opening hours keyed by weekday (Monday=0 … Sunday=6). Omit a day = closed.
CLINIC_BUSINESS_HOURS = {
    0: ("08:00", "18:00"),
    1: ("08:00", "18:00"),
    2: ("08:00", "18:00"),
    3: ("08:00", "18:00"),
    4: ("08:00", "18:00"),
    5: ("09:00", "14:00"),
}
CLINIC_APPOINTMENT_DURATIONS = {"new_patient": 60, "returning": 30, "emergency": 30}
CLINIC_SLOT_INTERVAL_MINUTES = 30

LANGUAGE_CODE = "en-us"
TIME_ZONE = CLINIC_TIMEZONE
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATIC_ROOT = os.path.join(BASE_DIR, "staticfiles")
# WhiteNoise serves collected static files (admin CSS/JS) from gunicorn.
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        "BACKEND": (
            "django.contrib.staticfiles.storage.StaticFilesStorage"
            if DEBUG
            else "whitenoise.storage.CompressedManifestStaticFilesStorage"
        )
    },
}
WHITENOISE_MANIFEST_STRICT = False

# ─── HTTPS / security headers (production) ──────────────────
# Assumes TLS terminates at a reverse proxy / platform router that sets
# X-Forwarded-Proto. Each setting can be overridden from the environment.
if not DEBUG:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_SSL_REDIRECT = env_bool("SECURE_SSL_REDIRECT", True)
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = int(os.getenv("SECURE_HSTS_SECONDS", "31536000"))
    SECURE_HSTS_INCLUDE_SUBDOMAINS = env_bool("SECURE_HSTS_INCLUDE_SUBDOMAINS", False)
    SECURE_HSTS_PRELOAD = env_bool("SECURE_HSTS_PRELOAD", False)
    SECURE_CONTENT_TYPE_NOSNIFF = True
    SECURE_REFERRER_POLICY = "same-origin"
    X_FRAME_OPTIONS = "DENY"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Redirect @login_required (dashboard) to the Django admin login.
LOGIN_URL = "/admin/login/"

# API Configuration
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
VAPI_API_KEY = os.getenv("VAPI_API_KEY")
# Shared secret Vapi must send on every API request (X-Vapi-Secret header or
# "Authorization: Bearer <secret>"). Unset = the API only accepts staff sessions.
VAPI_SECRET = os.getenv("VAPI_SECRET", "")
# Per-minute request limits. Vapi traffic is limited per call id, browser chat
# per staff user, and unauthenticated attempts per client IP.
API_RATE_LIMIT_PER_CALL_PER_MINUTE = int(os.getenv("API_RATE_LIMIT_PER_CALL_PER_MINUTE", "30"))
API_RATE_LIMIT_STAFF_PER_MINUTE = int(os.getenv("API_RATE_LIMIT_STAFF_PER_MINUTE", "20"))
API_RATE_LIMIT_UNAUTHENTICATED_PER_MINUTE = int(os.getenv("API_RATE_LIMIT_UNAUTHENTICATED_PER_MINUTE", "10"))
# Only enable behind a proxy that overwrites X-Forwarded-For.
TRUST_X_FORWARDED_FOR = env_bool("TRUST_X_FORWARDED_FOR")
# Public (browser-safe) Vapi credentials for the web voice widget on the landing page.
VAPI_PUBLIC_KEY = os.getenv("VAPI_PUBLIC_KEY", "")
VAPI_ASSISTANT_ID = os.getenv("VAPI_ASSISTANT_ID", "")
GOOGLE_CALENDAR_CREDENTIALS = os.getenv(
    "GOOGLE_CALENDAR_CREDENTIALS", "google-calendar-credentials.json"
)
GOOGLE_CALENDAR_ID = os.getenv("GOOGLE_CALENDAR_ID")
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_PHONE_NUMBER = os.getenv("TWILIO_PHONE_NUMBER")
# Max confirmation texts per recipient per rolling 24h (abuse / toll-fraud guard).
SMS_DAILY_LIMIT_PER_NUMBER = int(os.getenv("SMS_DAILY_LIMIT_PER_NUMBER", "3"))

# ─── Agent / upstream limits ────────────────────────────────
# Upper bound on model→tool round-trips per caller turn, and per-request
# timeouts for upstream APIs so a slow dependency can't hold a worker past
# Vapi's response window.
AGENT_MAX_TOOL_ITERATIONS = int(os.getenv("AGENT_MAX_TOOL_ITERATIONS", "5"))
OPENAI_TIMEOUT_SECONDS = float(os.getenv("OPENAI_TIMEOUT_SECONDS", "15"))
OPENAI_MAX_RETRIES = int(os.getenv("OPENAI_MAX_RETRIES", "1"))
GOOGLE_API_TIMEOUT_SECONDS = float(os.getenv("GOOGLE_API_TIMEOUT_SECONDS", "10"))
TWILIO_TIMEOUT_SECONDS = float(os.getenv("TWILIO_TIMEOUT_SECONDS", "10"))

# Background work (SMS delivery). EAGER runs tasks inline — used by tests.
BACKGROUND_TASK_WORKERS = int(os.getenv("BACKGROUND_TASK_WORKERS", "4"))
BACKGROUND_TASKS_EAGER = env_bool("BACKGROUND_TASKS_EAGER")

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "[{asctime}] [{levelname}] {message}",
            "style": "{",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "verbose",
        },
    },
    "root": {
        "handlers": ["console"],
        "level": os.getenv("LOG_LEVEL", "INFO"),
    },
}

# ─── Data retention ─────────────────────────────────────────
# `manage.py purge_call_data` clears call summaries/transcripts and masks caller
# numbers on call logs older than this many days. Schedule it (cron, etc.).
CALL_DATA_RETENTION_DAYS = int(os.getenv("CALL_DATA_RETENTION_DAYS", "90"))

TEST_RUNNER = "receptionist_project.test_runner.TestRunner"
