import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.getenv("SECRET_KEY", "django-insecure-change-me-in-production")

DEBUG = os.getenv("DEBUG", "True") == "True"

ALLOWED_HOSTS = os.getenv("ALLOWED_HOSTS", "localhost,127.0.0.1,0.0.0.0").split(",")

# Trust HTTPS tunnel domains (ngrok) for CSRF-protected POSTs like the admin login.
CSRF_TRUSTED_ORIGINS = [
    "https://*.ngrok-free.dev",
    "https://*.ngrok-free.app",
    "https://*.ngrok.io",
]
_extra_csrf = os.getenv("CSRF_TRUSTED_ORIGINS", "")
if _extra_csrf:
    CSRF_TRUSTED_ORIGINS += _extra_csrf.split(",")

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

if os.getenv("USE_SQLITE") == "True":
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
            "PASSWORD": os.getenv("DB_PASSWORD", "postgres"),
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

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Redirect @login_required (dashboard) to the Django admin login.
LOGIN_URL = "/admin/login/"

# API Configuration
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
VAPI_API_KEY = os.getenv("VAPI_API_KEY")
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

# Background work (SMS delivery). EAGER runs tasks inline — used by tests.
BACKGROUND_TASK_WORKERS = int(os.getenv("BACKGROUND_TASK_WORKERS", "4"))
BACKGROUND_TASKS_EAGER = os.getenv("BACKGROUND_TASKS_EAGER", "False") == "True"

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
        "level": "INFO",
    },
}
