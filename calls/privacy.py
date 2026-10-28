"""Helpers for keeping patient data (PII/PHI) out of logs."""
from __future__ import annotations

SENSITIVE_KEYS = {
    "patient_name",
    "patient_phone",
    "caller_phone",
    "customerNumber",
    "number",
    "to",
    "phone",
}


def mask_phone(phone: str | None) -> str:
    """'+15551234567' -> '***4567'. Never returns more than the last 4 digits."""
    if not phone:
        return "-"
    digits = "".join(ch for ch in str(phone) if ch.isdigit())
    return f"***{digits[-4:]}" if len(digits) >= 4 else "***"


def redact(value):
    """Deep-copy ``value`` with sensitive fields masked, for DEBUG logging."""
    if isinstance(value, dict):
        out = {}
        for key, item in value.items():
            if key in SENSITIVE_KEYS and isinstance(item, str):
                out[key] = mask_phone(item) if "name" not in key else "[redacted]"
            else:
                out[key] = redact(item)
        return out
    if isinstance(value, list):
        return [redact(item) for item in value]
    return value


def outcome(result: dict | None) -> str:
    """Short, PII-free summary of a tool result for INFO logs."""
    if not isinstance(result, dict):
        return "no-result"
    if result.get("success"):
        return "ok"
    return f"error={result.get('error', 'unknown')}"
