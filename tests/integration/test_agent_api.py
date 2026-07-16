"""
Integration tests for the Agent Dashboard API.

All DB/Redis are mocked — no real connections needed.
"""

from __future__ import annotations

import types
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from src.core.orchestrator import ConversationOrchestrator
from src.db.postgres import get_session
from src.db.repositories.conversation_repo import ConversationRepository
from src.db.repositories.handoff_repo import HandoffRepository
from src.main import app
from src.models.conversation import ConversationStatus, MessageDirection
from src.models.handoff import HandoffStatus
from src.services.ai.claude_client import ToolCompletionResult
from src.services.ai.response_generator import DEFAULT_STORE_CONFIG

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

STORE_ID = uuid.uuid4()
CUSTOMER_ID = uuid.uuid4()
CONVERSATION_ID = uuid.uuid4()
HANDOFF_ID = uuid.uuid4()


def _make_customer(**overrides):
    base = dict(
        id=CUSTOMER_ID,
        phone_number="919876543210",
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
        message_count=3,
        ai_response_count=1,
        created_at=datetime.now(timezone.utc),
        customer=_make_customer(),
    )
    base.update(overrides)
    return types.SimpleNamespace(**base)


def _make_handoff(**overrides):
    conv = _make_conversation()
    base = dict(
        id=HANDOFF_ID,
        conversation_id=CONVERSATION_ID,
        store_id=STORE_ID,
        reason="complaint",
        context_summary="Customer complained about damaged product",
        suggested_response=None,
        priority=2,
        status=HandoffStatus.pending,
        created_at=datetime.now(timezone.utc),
        conversation=conv,
    )
    base.update(overrides)
    return types.SimpleNamespace(**base)


# ---------------------------------------------------------------------------
# Shared fixture
# ---------------------------------------------------------------------------

@pytest.fixture
async def api_client():
    async def override_session():
        yield AsyncMock()

    app.dependency_overrides[get_session] = override_session

    with (
        patch("src.main._validate_required_settings"),
        patch("src.main.init_db"),
        patch("src.main.init_redis"),
        patch("src.main.close_db"),
        patch("src.main.close_redis"),
    ):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as c:
            yield c

    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Test 1: list handoffs returns pending
# ---------------------------------------------------------------------------

async def test_list_handoffs_returns_pending(api_client: AsyncClient):
    mock_handoff = _make_handoff()

    with patch.object(
        HandoffRepository,
        "get_by_status",
        new=AsyncMock(return_value=[mock_handoff]),
    ):
        response = await api_client.get(
            f"/api/agent/handoffs?store_id={STORE_ID}&status=pending"
        )

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["reason"] == "complaint"
    assert data[0]["priority"] == 2
    assert data[0]["customer_phone"] == "919876543210"


# ---------------------------------------------------------------------------
# Test 2: takeover sets conversation status
# ---------------------------------------------------------------------------

async def test_takeover_sets_conversation_status(api_client: AsyncClient):
    mock_conv = _make_conversation(status=ConversationStatus.bot)
    update_status_mock = AsyncMock(return_value=None)

    with (
        patch.object(
            ConversationRepository,
            "get_by_id",
            new=AsyncMock(return_value=mock_conv),
        ),
        patch.object(
            ConversationRepository,
            "update_status",
            new=update_status_mock,
        ),
    ):
        response = await api_client.post(
            f"/api/agent/conversations/{CONVERSATION_ID}/takeover",
            json={"agent_id": "agent-001"},
        )

    assert response.status_code == 200
    assert response.json() == {"success": True}

    # Verify update_status was called with human_takeover
    update_status_mock.assert_called_once()
    call_args = update_status_mock.call_args
    assert call_args.args[1] == ConversationStatus.human_takeover


# ---------------------------------------------------------------------------
# Test 3: human_takeover status skips AI response in orchestrator
# ---------------------------------------------------------------------------

def _make_inbound_msg():
    return types.SimpleNamespace(
        id=uuid.uuid4(),
        conversation_id=CONVERSATION_ID,
        direction=MessageDirection.inbound,
        content="Hi",
        message_type="text",
    )


def _build_orchestrator_for_takeover() -> ConversationOrchestrator:
    customer = _make_customer()
    conversation = _make_conversation(status=ConversationStatus.human_takeover)
    inbound_msg = _make_inbound_msg()

    customer_repo = AsyncMock()
    customer_repo.get_or_create.return_value = (customer, False)
    customer_repo.update_last_seen.return_value = None

    conversation_repo = AsyncMock()
    conversation_repo.get_active.return_value = conversation
    conversation_repo.increment_message_count.return_value = None

    message_repo = AsyncMock()
    message_repo.save_inbound.return_value = inbound_msg

    handoff_repo = AsyncMock()

    claude_client = AsyncMock()
    tool_executor = AsyncMock()
    whatsapp_client = AsyncMock()
    transcriber = AsyncMock()

    return ConversationOrchestrator(
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


async def test_human_takeover_skips_ai_response():
    orchestrator = _build_orchestrator_for_takeover()

    result = await orchestrator.process_message(
        customer_phone="919876543210",
        message_type="text",
        content="Hi",
    )

    assert result.success
    assert not result.response_sent
    assert result.response_type == "none"
    assert not result.handoff_created

    # Claude should NOT have been called
    orchestrator._claude.complete_with_tools.assert_not_called()
