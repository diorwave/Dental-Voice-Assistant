from django.conf import settings
from django.test.runner import DiscoverRunner


class TestRunner(DiscoverRunner):
    """Run the suite the same way regardless of DEBUG: the test client speaks
    plain HTTP, so the production HTTPS redirect would turn every response
    into a 301."""

    def setup_test_environment(self, **kwargs):
        super().setup_test_environment(**kwargs)
        settings.SECURE_SSL_REDIRECT = False
