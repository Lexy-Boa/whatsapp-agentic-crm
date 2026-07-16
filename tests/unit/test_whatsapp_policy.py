from __future__ import annotations

from datetime import datetime, timedelta, timezone

from src.services.whatsapp.policy import WhatsAppPolicy


def test_policy_allows_freeform_within_customer_service_window():
    now = datetime(2026, 4, 8, 12, 0, tzinfo=timezone.utc)
    policy = WhatsAppPolicy(mode="enforce", customer_service_window_hours=24)

    decision = policy.evaluate_freeform_send(
        last_customer_message_at=now - timedelta(hours=2),
        now=now,
    )

    assert decision.allowed is True
    assert decision.requires_template is False
    assert decision.reason is None


def test_policy_warns_outside_window_in_warn_mode():
    now = datetime(2026, 4, 8, 12, 0, tzinfo=timezone.utc)
    policy = WhatsAppPolicy(mode="warn", customer_service_window_hours=24)

    decision = policy.evaluate_freeform_send(
        last_customer_message_at=now - timedelta(hours=30),
        now=now,
    )

    assert decision.allowed is True
    assert decision.requires_template is True
    assert decision.reason == "outside_customer_service_window"


def test_policy_blocks_outside_window_in_enforce_mode():
    now = datetime(2026, 4, 8, 12, 0, tzinfo=timezone.utc)
    policy = WhatsAppPolicy(mode="enforce", customer_service_window_hours=24)

    decision = policy.evaluate_freeform_send(
        last_customer_message_at=now - timedelta(hours=30),
        now=now,
    )

    assert decision.allowed is False
    assert decision.requires_template is True
    assert decision.reason == "outside_customer_service_window"


def test_policy_blocks_without_last_customer_message_in_enforce_mode():
    policy = WhatsAppPolicy(mode="enforce", customer_service_window_hours=24)

    decision = policy.evaluate_freeform_send(last_customer_message_at=None)

    assert decision.allowed is False
    assert decision.requires_template is True
    assert decision.reason == "no_customer_service_window"
