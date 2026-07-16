"""
Integration tests for ConversationOrchestrator.

All external services (DB repositories, WhatsApp client, Claude, etc.) are
mocked with AsyncMock / SimpleNamespace — no real DB or API connections needed.
"""

from __future__ import annotations

import types
import uuid
from unittest.mock import AsyncMock

import pytest

from src.core.orchestrator import ConversationOrchestrator
from src.models.conversation import ConversationStatus, MessageDirection
from src.services.ai.claude_client import ToolCompletionResult, ToolCallLog
from src.services.ai.response_generator import DEFAULT_STORE_CONFIG
from src.services.speech.transcriber import TranscriptionResult

# ---------------------------------------------------------------------------
# Shared constants
# ---------------------------------------------------------------------------

STORE_ID = uuid.uuid4()
CUSTOMER_PHONE = "919876543210"
CUSTOMER_ID = uuid.uuid4()
CONVERSATION_ID = uuid.uuid4()
INBOUND_MSG_ID = uuid.uuid4()


# ---------------------------------------------------------------------------
# Helper factories
# ---------------------------------------------------------------------------

def _make_customer(**overrides):
    base = dict(
        id=CUSTOMER_ID,
        phone_number=CUSTOMER_PHONE,
        name="Test Customer",
        language_preference="en",
        detected_language=None,
        detected_dialect=None,
    )
    base.update(overrides)
    return types.SimpleNamespace(**base)


def _make_conversation(**overrides):
    base = dict(
        id=CONVERSATION_ID,
        customer_id=CUSTOMER_ID,
        status=ConversationStatus.bot,
        message_count=0,
        ai_response_count=0,
    )
    base.update(overrides)
    return types.SimpleNamespace(**base)


def _make_send_result(success: bool = True, message_id: str = "wa_out_001"):
    return types.SimpleNamespace(success=success, message_id=message_id)


def _make_inbound_msg():
    return types.SimpleNamespace(
        id=INBOUND_MSG_ID,
        conversation_id=CONVERSATION_ID,
        direction=MessageDirection.inbound,
        content="Hello",
        message_type="text",
    )


def _build_orchestrator(
    *,
    customer=None,
    conversation=None,
    tool_result: ToolCompletionResult,
) -> ConversationOrchestrator:
    """Build a ConversationOrchestrator with all dependencies mocked."""
    customer = customer or _make_customer()
    conversation = conversation or _make_conversation()
    inbound_msg = _make_inbound_msg()

    # -- Repositories ----------------------------------------------------------
    customer_repo = AsyncMock()
    customer_repo.get_or_create.return_value = (customer, False)
    customer_repo.update_language.return_value = None
    customer_repo.update_last_seen.return_value = None

    conversation_repo = AsyncMock()
    conversation_repo.get_active.return_value = None  # triggers create()
    conversation_repo.create.return_value = conversation
    conversation_repo.increment_message_count.return_value = None
    conversation_repo.increment_ai_response_count.return_value = None
    conversation_repo.update_status.return_value = None

    message_repo = AsyncMock()
    message_repo.save_inbound.return_value = inbound_msg
    message_repo.get_recent.return_value = []
    message_repo.save_outbound.return_value = None
    message_repo.save_transcription.return_value = None

    handoff_repo = AsyncMock()
    mock_handoff = types.SimpleNamespace(id=uuid.uuid4())
    handoff_repo.create.return_value = mock_handoff

    # -- Claude client (mock complete_with_tools) ------------------------------
    claude_client = AsyncMock()
    claude_client.complete_with_tools.return_value = tool_result

    # -- Tool executor (mocked, not actually called in these tests) ------------
    tool_executor = AsyncMock()

    # -- External clients ------------------------------------------------------
    whatsapp_client = AsyncMock()
    whatsapp_client.send_text.return_value = _make_send_result()
    whatsapp_client.send_voice.return_value = _make_send_result()

    transcriber = AsyncMock()

    orchestrator = ConversationOrchestrator(
        store_id=STORE_ID,
        store_config=DEFAULT_STORE_CONFIG,
        whatsapp_client=whatsapp_client,
        transcriber=transcriber,
        claude_client=claude_client,
        tool_executor=tool_executor,
        tts=None,
        customer_repo=customer_repo,
        conversation_repo=conversation_repo,
        message_repo=message_repo,
        handoff_repo=handoff_repo,
    )
    return orchestrator


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

async def test_text_message_flow():
    """A plain-text greeting flows through the pipeline and sends a text response."""
    tool_result = ToolCompletionResult(
        response_text="Hello! How can I help you today?",
        escalated=False,
        input_tokens=100,
        output_tokens=20,
    )

    orchestrator = _build_orchestrator(tool_result=tool_result)

    result = await orchestrator.process_message(
        customer_phone=CUSTOMER_PHONE,
        message_type="text",
        content="Hello!",
    )

    assert result.success
    assert result.response_sent
    assert result.response_type == "text"
    assert not result.handoff_created
    assert result.handoff_id is None
    assert result.error is None
    assert result.total_time_ms >= 0


async def test_voice_message_flow():
    """A voice message is transcribed then answered with a text response."""
    tool_result = ToolCompletionResult(
        response_text="We have lovely kasavu sarees! \u2728",
        escalated=False,
        tool_calls_log=[
            ToolCallLog(
                tool_name="search_products",
                tool_input={"query": "kasavu saree"},
                result='{"products": []}',
            )
        ],
        input_tokens=200,
        output_tokens=30,
    )

    orchestrator = _build_orchestrator(tool_result=tool_result)

    # Configure the transcriber mock on the already-built orchestrator
    mock_transcription = TranscriptionResult(
        text="I want kasavu saree",
        raw_text="I want kasavu saree",
        language="ml",
        dialect="thrissur",
        dialect_confidence=0.75,
        transcription_confidence=0.92,
        duration_seconds=3.5,
        word_count=4,
    )
    orchestrator._transcriber.transcribe.return_value = mock_transcription

    result = await orchestrator.process_message(
        customer_phone=CUSTOMER_PHONE,
        message_type="voice",
        media_bytes=b"fake_audio_data",
        media_mime_type="audio/ogg",
    )

    assert result.success
    assert result.response_sent
    assert result.transcription_time_ms is not None
    assert result.transcription_time_ms >= 0
    assert not result.handoff_created
    assert result.error is None


async def test_complaint_triggers_handoff():
    """A complaint triggers escalation via the escalate_to_human tool."""
    handoff_id = uuid.uuid4()

    tool_result = ToolCompletionResult(
        response_text="I'm sorry to hear that. Let me connect you with our team.",
        escalated=True,
        escalation_reason="Customer complaint about damaged product",
        escalation_priority=2,
        escalation_summary="Customer received damaged product, requesting refund.",
        tool_calls_log=[
            ToolCallLog(
                tool_name="escalate_to_human",
                tool_input={
                    "reason": "Customer complaint about damaged product",
                    "priority": 2,
                    "summary": "Customer received damaged product, requesting refund.",
                },
                result='{"status": "escalation_requested"}',
            )
        ],
        input_tokens=150,
        output_tokens=40,
    )

    orchestrator = _build_orchestrator(tool_result=tool_result)

    # Override handoff repo to return a specific handoff ID
    orchestrator._handoff_repo.create.return_value = types.SimpleNamespace(id=handoff_id)

    result = await orchestrator.process_message(
        customer_phone=CUSTOMER_PHONE,
        message_type="text",
        content="I received a damaged product and want a refund!",
    )

    assert result.success
    assert result.handoff_created
    assert result.handoff_id == handoff_id
    assert result.response_sent  # acknowledgment sent
    assert result.response_type == "text"
    assert result.error is None


async def test_product_search_flow():
    """Product search tool is called and results incorporated into response."""
    tool_result = ToolCompletionResult(
        response_text="Here are some red silk sarees we have \u2728",
        escalated=False,
        tool_calls_log=[
            ToolCallLog(
                tool_name="search_products",
                tool_input={"query": "red silk saree", "occasion": "wedding"},
                result='{"products": [{"name": "Red Silk Saree", "sku": "DMB-001", "price": 12000}]}',
            )
        ],
        products_referenced=[
            {"name": "Red Silk Saree", "sku": "DMB-001", "price": 12000}
        ],
        input_tokens=200,
        output_tokens=50,
    )

    orchestrator = _build_orchestrator(tool_result=tool_result)

    result = await orchestrator.process_message(
        customer_phone=CUSTOMER_PHONE,
        message_type="text",
        content="looking for a red silk saree for wedding under 15k",
    )

    assert result.success
    assert result.response_sent
    assert result.response_type == "text"
    assert not result.handoff_created


async def test_human_takeover_short_circuit():
    """Messages during human takeover are saved but no AI response is generated."""
    conversation = _make_conversation(status=ConversationStatus.human_takeover)

    tool_result = ToolCompletionResult(response_text="")  # should not be used

    orchestrator = _build_orchestrator(
        conversation=conversation,
        tool_result=tool_result,
    )
    # Ensure conversation is returned from get_active instead of create
    orchestrator._conversation_repo.get_active.return_value = conversation

    result = await orchestrator.process_message(
        customer_phone=CUSTOMER_PHONE,
        message_type="text",
        content="Hello, is anyone there?",
    )

    assert result.success
    assert not result.response_sent
    assert result.response_type == "none"
    assert not result.handoff_created
    # Claude should NOT have been called
    orchestrator._claude.complete_with_tools.assert_not_called()


async def test_claude_failure_falls_back_to_handoff():
    """Claude billing/outage failures should create a handoff and send a safe fallback."""
    tool_result = ToolCompletionResult(response_text="unused")
    orchestrator = _build_orchestrator(tool_result=tool_result)
    handoff_id = uuid.uuid4()

    orchestrator._claude.complete_with_tools.side_effect = Exception(
        "Anthropic billing error"
    )
    orchestrator._handoff_repo.create.return_value = types.SimpleNamespace(id=handoff_id)

    result = await orchestrator.process_message(
        customer_phone=CUSTOMER_PHONE,
        message_type="text",
        content="Hello Avni",
    )

    assert result.success
    assert result.handoff_created
    assert result.handoff_id == handoff_id
    assert result.response_sent
    assert result.response_type == "text"
    assert result.error is None
    orchestrator._conversation_repo.update_status.assert_not_awaited()
    orchestrator._message_repo.save_outbound.assert_awaited()
