from __future__ import annotations

from src.core.privacy import (
    mask_phone,
    redact_operational_data,
    redact_operational_text,
    summarize_exception_for_operations,
)


def test_mask_phone_masks_long_numbers():
    assert mask_phone("+919876543210") == "91987*****10"


def test_mask_phone_masks_short_numbers():
    assert mask_phone("1234") == "1**4"
    assert mask_phone("12") == "12"


def test_mask_phone_handles_empty_values():
    assert mask_phone("") == ""
    assert mask_phone(None) == ""


def test_redact_operational_text_masks_phone_like_values_and_secrets():
    text = (
        "Meta error for +91 79946 85550 using "
        "EAAabcdefghijklmnopqrstuvwxyz1234567890"
    )

    redacted = redact_operational_text(text)

    assert "79946 85550" not in redacted
    assert "EAAabcdefghijklmnopqrstuvwxyz1234567890" not in redacted
    assert "91799*****50" in redacted
    assert "[REDACTED_SECRET]" in redacted


def test_redact_operational_text_truncates_long_values():
    redacted = redact_operational_text("x" * 20, max_length=5)

    assert redacted == "xxxxx..."


def test_summarize_exception_for_operations_uses_exception_type_only():
    exc = RuntimeError("customer said my phone is +91 79946 85550")

    summary = summarize_exception_for_operations(exc)

    assert summary == "RuntimeError"
    assert "79946" not in summary


def test_redact_operational_data_recurses_through_metadata():
    data = {
        "error": "token EAAabcdefghijklmnopqrstuvwxyz1234567890 failed",
        "nested": ["call +91 79946 85550"],
    }

    redacted = redact_operational_data(data)

    assert "EAAabcdefghijklmnopqrstuvwxyz1234567890" not in str(redacted)
    assert "79946 85550" not in str(redacted)
    assert "[REDACTED_SECRET]" in str(redacted)
