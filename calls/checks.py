from django.core.checks import Warning, register

from .security import configured_secret


@register(deploy=True)
def vapi_secret_check(app_configs, **kwargs):
    if configured_secret():
        return []
    return [
        Warning(
            "VAPI_SECRET is missing, a placeholder, or shorter than 16 characters.",
            hint="The Vapi API rejects every request until it is set. Generate one with "
            "python3 -c \"import secrets; print(secrets.token_urlsafe(32))\".",
            id="calls.W001",
        )
    ]
