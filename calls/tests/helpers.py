import json


def api_post(client, path, payload, **headers):
    """POST JSON to a Vapi-facing endpoint."""
    return client.post(path, data=json.dumps(payload), content_type="application/json", headers=headers)
