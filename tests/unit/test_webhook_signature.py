"""
Unit tests for WhatsApp webhook signature verification.

Validates HMAC-SHA256 signature checking — the #1 security gate
for inbound webhooks.
"""

from __future__ import annotations

import hashlib
import hmac
import json

from src.api.webhooks.whatsapp import _verify_signature


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_valid_signature_passes():
    """A correctly computed HMAC-SHA256 signature is accepted."""
    secret = "test_app_secret_123"
    body = json.dumps({"messages": [{"id": "msg1", "type": "text"}]}).encode()
    expected_hex = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    sig_header = f"sha256={expected_hex}"

    assert _verify_signature(body, sig_header, secret) is True


def test_invalid_signature_rejected():
    """A wrong signature is rejected."""
    secret = "test_app_secret_123"
    body = b'{"messages": []}'

    assert _verify_signature(body, "sha256=deadbeef0000", secret) is False


def test_empty_signature_rejected():
    """An empty signature header is rejected."""
    secret = "test_app_secret_123"
    body = b'{"messages": []}'

    assert _verify_signature(body, "", secret) is False


def test_missing_sha256_prefix_rejected():
    """A signature without the sha256= prefix is rejected."""
    secret = "test_app_secret_123"
    body = b'{"messages": []}'
    hex_digest = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()

    # Missing "sha256=" prefix
    assert _verify_signature(body, hex_digest, secret) is False


def test_empty_body_valid_signature():
    """An empty body with a correct signature is accepted."""
    secret = "test_app_secret_123"
    body = b""
    expected_hex = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    sig_header = f"sha256={expected_hex}"

    assert _verify_signature(body, sig_header, secret) is True


def test_different_secrets_produce_different_signatures():
    """Two different secrets produce different signatures for the same body."""
    body = b'{"test": true}'
    hex1 = hmac.new(b"secret_1", body, hashlib.sha256).hexdigest()
    hex2 = hmac.new(b"secret_2", body, hashlib.sha256).hexdigest()

    assert hex1 != hex2
    assert _verify_signature(body, f"sha256={hex1}", "secret_1") is True
    assert _verify_signature(body, f"sha256={hex1}", "secret_2") is False
