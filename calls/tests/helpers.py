import json

TEST_SECRET = "test-vapi-secret-0123456789"


def api_post(client, path, payload, *, secret=TEST_SECRET, **headers):
    """POST JSON to a Vapi-facing endpoint, authenticated with the shared secret
    unless ``secret=None``. Pair with ``override_settings(VAPI_SECRET=TEST_SECRET)``."""
    if secret is not None:
        headers.setdefault("X-Vapi-Secret", secret)
    return client.post(path, data=json.dumps(payload), content_type="application/json", headers=headers)
