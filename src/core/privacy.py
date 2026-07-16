from __future__ import annotations

import re

_PHONEISH_RE = re.compile(r"\+?\d[\d\s().-]{6,}\d")
_SECRETISH_RE = re.compile(
    r"\b(?:EAA[A-Za-z0-9_-]{20,}|sk-[A-Za-z0-9_-]{20,}|gsk_[A-Za-z0-9_-]{20,}|shpat_[A-Za-z0-9_-]{10,})\b"
)


def mask_phone(phone_number: str | None) -> str:
    """
    Mask a phone number for operational logs.

    Examples:
    - ``+919876543210`` -> ``91987******10``
    - ``12345`` -> ``12*45``
    """
    if not phone_number:
        return ""

    normalized = phone_number.lstrip("+").strip()
    if not normalized:
        return ""

    if len(normalized) <= 4:
        return normalized[0] + ("*" * max(0, len(normalized) - 2)) + normalized[-1]

    prefix_len = min(5, max(2, len(normalized) // 2))
    suffix_len = 2
    hidden_len = max(1, len(normalized) - prefix_len - suffix_len)
    return f"{normalized[:prefix_len]}{'*' * hidden_len}{normalized[-suffix_len:]}"


def redact_operational_text(value: object, *, max_length: int = 240) -> str:
    """
    Redact obvious secrets and phone-like values before operational logging.

    This is intentionally conservative and small. Business records may retain
    full-fidelity data, but logs and Control Room system events should not grow
    a second uncontrolled copy of customer PII or credentials.
    """
    text = str(value)
    text = _SECRETISH_RE.sub("[REDACTED_SECRET]", text)

    def _mask_match(match: re.Match[str]) -> str:
        digits = re.sub(r"\D", "", match.group(0))
        return mask_phone(digits)

    text = _PHONEISH_RE.sub(_mask_match, text)
    if len(text) > max_length:
        return f"{text[:max_length]}..."
    return text


def redact_operational_data(value: object) -> object:
    """Recursively redact strings inside operational event metadata."""
    if isinstance(value, str):
        return redact_operational_text(value)
    if isinstance(value, dict):
        return {key: redact_operational_data(item) for key, item in value.items()}
    if isinstance(value, list):
        return [redact_operational_data(item) for item in value]
    if isinstance(value, tuple):
        return tuple(redact_operational_data(item) for item in value)
    return value


def summarize_exception_for_operations(exc: BaseException | object) -> str:
    """
    Return a low-PII exception summary for logs and Control Room events.

    Provider exceptions can sometimes include request snippets, URLs, or echoed
    input. For operational streams we prefer the stable exception type over raw
    exception text; full business records remain in the database where intended.
    """
    if isinstance(exc, BaseException):
        return exc.__class__.__name__
    return redact_operational_text(exc)
