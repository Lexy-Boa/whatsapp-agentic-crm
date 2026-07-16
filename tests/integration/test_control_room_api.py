from __future__ import annotations

import types
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from src.api.control_room.schemas import ControlRoomCustomer, ConversationRecord
from src.db.postgres import get_session
from src.db.repositories.conversation_repo import ConversationRepository
from src.db.repositories.handoff_repo import HandoffRepository
from src.db.repositories.system_event_repo import SystemEventRepository
from src.main import app


@pytest.fixture
async def api_client():
    session = AsyncMock()

    async def override_session():
        yield session

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
        ) as client:
            yield client, session

    app.dependency_overrides.clear()


async def test_control_room_summary_returns_metrics(api_client: tuple[AsyncClient, AsyncMock]):
    client, session = api_client
    latest_event = types.SimpleNamespace(created_at=datetime.now(timezone.utc))
    redis = AsyncMock()
    redis.llen = AsyncMock(side_effect=[2, 1, 0])
    session.scalar = AsyncMock(side_effect=[6, 1])

    with (
        patch("src.api.control_room.router.get_redis", return_value=redis),
        patch("src.api.control_room.router.check_db_health", new=AsyncMock(return_value=True)),
        patch("src.api.control_room.router.check_redis_health", new=AsyncMock(return_value=True)),
        patch("src.api.control_room.router._latest_component_state", new=AsyncMock(side_effect=["ok", "ok", "degraded", "ok"])),
        patch.object(SystemEventRepository, "latest_event", new=AsyncMock(return_value=latest_event)),
        patch.object(SystemEventRepository, "count_by_type", new=AsyncMock(side_effect=[12, 10, 1, 7, 2])),
        patch.object(SystemEventRepository, "average_detail_value", new=AsyncMock(return_value=842.2)),
    ):
        response = await client.get("/api/control-room/summary?range=24h")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "degraded"
    assert payload["queue_depth"] == 2
    assert payload["processing_depth"] == 1
    assert payload["metrics"]["messages_received"] == 12
    assert payload["metrics"]["open_conversations"] == 6
    assert payload["health"]["claude"] == "degraded"


async def test_control_room_page_renders_title(api_client: tuple[AsyncClient, AsyncMock]):
    client, _session = api_client
    response = await client.get("/control-room")
    assert response.status_code == 200
    assert "Control Room" in response.text


async def test_control_room_invalid_range_returns_400(api_client: tuple[AsyncClient, AsyncMock]):
    client, _session = api_client

    response = await client.get("/api/control-room/activity?range=h")

    assert response.status_code == 400


async def test_control_room_conversations_markdown_export(api_client: tuple[AsyncClient, AsyncMock]):
    client, _session = api_client
    conversation = types.SimpleNamespace(
        id=uuid.uuid4(),
        status=types.SimpleNamespace(value="bot"),
        message_count=4,
        ai_response_count=2,
        created_at=datetime.now(timezone.utc),
        last_message_at=datetime.now(timezone.utc),
        customer=types.SimpleNamespace(
            id=uuid.uuid4(),
            name="Kaithari Customer",
            phone_number="919876543210",
        ),
    )

    with patch("src.api.control_room.router._list_conversations", new=AsyncMock(return_value=[conversation])):
        response = await client.get("/api/control-room/exports/conversations.md")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert "Kaithari Customer" in response.text


async def test_control_room_handoffs_uses_configured_store_id(api_client: tuple[AsyncClient, AsyncMock]):
    client, _session = api_client
    store_id = uuid.uuid4()
    get_by_status_mock = AsyncMock(return_value=[])

    with (
        patch(
            "src.api.control_room.router.get_settings",
            return_value=types.SimpleNamespace(store_id=str(store_id)),
        ),
        patch.object(HandoffRepository, "get_by_status", new=get_by_status_mock),
    ):
        response = await client.get("/api/control-room/handoffs")

    assert response.status_code == 200
    assert response.json() == []
    assert get_by_status_mock.await_args.args[0] == store_id


async def test_control_room_resolve_handoff_action(api_client: tuple[AsyncClient, AsyncMock]):
    client, _session = api_client
    handoff = types.SimpleNamespace(
        id=uuid.uuid4(),
        conversation_id=uuid.uuid4(),
        notes=None,
    )

    with (
        patch.object(HandoffRepository, "get_by_id", new=AsyncMock(return_value=handoff)),
        patch.object(HandoffRepository, "resolve", new=AsyncMock(return_value=True)) as resolve_mock,
        patch("src.api.control_room.router.emit_system_event", new=AsyncMock()),
    ):
        response = await client.post(
            f"/api/control-room/handoffs/{handoff.id}/resolve",
            json={"note": "Customer refund handled."},
        )

    assert response.status_code == 200
    assert response.json() == {"success": True}
    assert resolve_mock.await_args.kwargs["notes"] == "Customer refund handled."


async def test_control_room_handoff_detail_includes_conversation(api_client: tuple[AsyncClient, AsyncMock]):
    client, _session = api_client
    conversation_id = uuid.uuid4()
    handoff = types.SimpleNamespace(
        id=uuid.uuid4(),
        conversation_id=conversation_id,
        reason="refund_request",
        context_summary="Customer reported a damaged product.",
        suggested_response="We will check and get back to you.",
        priority=2,
        status=types.SimpleNamespace(value="pending"),
        created_at=datetime.now(timezone.utc),
        resolved_at=None,
        notes="Check order photo.",
        conversation=types.SimpleNamespace(
            customer=types.SimpleNamespace(
                name="Kaithari Customer",
                phone_number="919876543210",
            )
        ),
    )
    conversation = ConversationRecord(
        conversation_id=conversation_id,
        status="bot",
        started_at=datetime.now(timezone.utc),
        last_message_at=None,
        message_count=0,
        ai_response_count=0,
        customer=ControlRoomCustomer(
            id=uuid.uuid4(),
            name="Kaithari Customer",
            phone="919876543210",
            language="ml",
            dialect=None,
        ),
        messages=[],
    )

    with (
        patch.object(HandoffRepository, "get_by_id", new=AsyncMock(return_value=handoff)),
        patch("src.api.control_room.router.get_conversation_detail", new=AsyncMock(return_value=conversation)),
    ):
        response = await client.get(f"/api/control-room/handoffs/{handoff.id}")

    assert response.status_code == 200
    payload = response.json()
    assert payload["reason"] == "refund_request"
    assert payload["notes"] == "Check order photo."
    assert payload["conversation"]["conversation_id"] == str(conversation_id)


async def test_control_room_save_handoff_note(api_client: tuple[AsyncClient, AsyncMock]):
    client, _session = api_client
    handoff = types.SimpleNamespace(
        id=uuid.uuid4(),
        conversation_id=uuid.uuid4(),
    )

    with (
        patch.object(HandoffRepository, "get_by_id", new=AsyncMock(return_value=handoff)),
        patch.object(HandoffRepository, "update_notes", new=AsyncMock(return_value=True)) as update_notes_mock,
        patch("src.api.control_room.router.emit_system_event", new=AsyncMock()),
    ):
        response = await client.post(
            f"/api/control-room/handoffs/{handoff.id}/notes",
            json={"note": "Owner will call customer tomorrow."},
        )

    assert response.status_code == 200
    assert response.json() == {"success": True}
    assert update_notes_mock.await_args.args == (
        handoff.id,
        "Owner will call customer tomorrow.",
    )


async def test_control_room_takeover_and_release_actions(api_client: tuple[AsyncClient, AsyncMock]):
    client, _session = api_client
    conversation_id = uuid.uuid4()
    conversation = types.SimpleNamespace(id=conversation_id)
    update_status_mock = AsyncMock()

    with (
        patch.object(ConversationRepository, "get_by_id", new=AsyncMock(return_value=conversation)),
        patch.object(ConversationRepository, "update_status", new=update_status_mock),
        patch("src.api.control_room.router.emit_system_event", new=AsyncMock()),
    ):
        takeover_response = await client.post(f"/api/control-room/conversations/{conversation_id}/takeover")
        release_response = await client.post(f"/api/control-room/conversations/{conversation_id}/release")

    assert takeover_response.status_code == 200
    assert release_response.status_code == 200
    assert update_status_mock.await_count == 2
