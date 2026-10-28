import os
import subprocess
import sys
from pathlib import Path

from django.test import SimpleTestCase

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def load_settings(**env):
    """Import settings in a fresh interpreter with a controlled environment."""
    clean = {k: v for k, v in os.environ.items() if k not in {"DEBUG", "SECRET_KEY", "ALLOWED_HOSTS"}}
    clean.update(env, DJANGO_SETTINGS_MODULE="receptionist_project.settings", USE_SQLITE="True")
    code = (
        "import django; django.setup(); from django.conf import settings as s; "
        "print(s.DEBUG, '*' in s.ALLOWED_HOSTS, getattr(s, 'SESSION_COOKIE_SECURE', None), s.SECURE_HSTS_SECONDS)"
    )
    # Variables passed explicitly (even as "") win over a developer's .env,
    # because load_dotenv() never overrides existing environment variables.
    return subprocess.run(
        [sys.executable, "-c", code], cwd=PROJECT_ROOT, env=clean, capture_output=True, text=True,
    )


class ProductionDefaultsTests(SimpleTestCase):
    def test_debug_is_off_and_secret_key_required_by_default(self):
        result = load_settings(DEBUG="", SECRET_KEY="")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("SECRET_KEY must be set", result.stderr)

    def test_placeholder_secret_key_is_rejected_in_production(self):
        result = load_settings(SECRET_KEY="your-secret-key-here", DEBUG="False")
        self.assertIn("SECRET_KEY must be set", result.stderr)

    def test_production_settings_are_hardened(self):
        result = load_settings(SECRET_KEY="a" * 60, DEBUG="False")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "False False True 31536000")

    def test_debug_allows_missing_key_for_local_development(self):
        result = load_settings(SECRET_KEY="", DEBUG="True")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(result.stdout.startswith("True"))
