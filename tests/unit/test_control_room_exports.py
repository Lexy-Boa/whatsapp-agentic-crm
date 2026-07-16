from __future__ import annotations

import types
import uuid
from datetime import datetime, timezone

from src.services.exports.control_room_exports import (
    activity_to_csv,
    conversations_to_markdown,
    handoffs_to_csv,
    handoffs_to_markdown,
)


def test_conversations_to_markdown_includes_owner_fields():
    content = conversations_to_markdown(
        [
            {
                "conversation_id": str(uuid.uuid4()),
                "customer_name": "Anitha",
                "customer_phone": "919876543210",
                "status": "bot",
                "message_count": 5,
                "ai_response_count": 3,
                "started_at": "2026-04-15T04:00:00+00:00",
                "last_message_at": "2026-04-15T04:05:00+00:00",
            }
        ]
    )

    assert "# Conversations" in content
    assert "Anitha" in content
    assert "AI replies: 3" in content


def test_activity_to_csv_uses_masked_phone_column():
    event = types.SimpleNamespace(
        id=uuid.uuid4(),
        created_at=datetime.now(timezone.utc),
        component="worker",
        event_type="message_processed",
        event_level="info",
        event_status="ok",
        summary="Processed successfully",
        customer_phone_masked="91987*****10",
        conversation_id=None,
        message_id=None,
        handoff_id=None,
    )

    content = activity_to_csv([event])

    assert "customer_phone_masked" in content
    assert "91987*****10" in content


def test_handoff_exports_include_owner_notes():
    handoff = types.SimpleNamespace(
        id=uuid.uuid4(),
        conversation_id=uuid.uuid4(),
        reason="refund_request",
        status=types.SimpleNamespace(value="resolved"),
        priority=2,
        created_at=datetime.now(timezone.utc),
        resolved_at=datetime.now(timezone.utc),
        context_summary="Customer reported a damaged product.",
        suggested_response="We will follow up.",
        notes="Owner approved replacement.",
    )

    csv_content = handoffs_to_csv([handoff])
    markdown_content = handoffs_to_markdown([handoff])

    assert "owner_notes" in csv_content
    assert "Owner approved replacement." in csv_content
    assert "Owner notes: Owner approved replacement." in markdown_content
