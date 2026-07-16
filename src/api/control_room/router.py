from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse, PlainTextResponse, Response
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.api.control_room.schemas import (
    ControlRoomCustomer,
    ControlRoomHealth,
    ControlRoomMetricSet,
    ControlRoomSummary,
    ConversationRecord,
    ConversationSummary,
    EventSummary,
    HandoffDetail,
    HandoffRecord,
    MessageSummary,
    OwnerNoteRequest,
)
from src.config import get_settings
from src.db.postgres import check_db_health, get_session
from src.db.redis_client import check_redis_health, get_redis
from src.db.repositories.conversation_repo import ConversationRepository
from src.db.repositories.handoff_repo import HandoffRepository
from src.db.repositories.message_repo import MessageRepository
from src.db.repositories.system_event_repo import SystemEventRepository
from src.models.conversation import Conversation, ConversationStatus, Message
from src.models.handoff import Handoff, HandoffStatus
from src.models.system_event import SystemEvent
from src.services.exports.control_room_exports import (
    activity_to_csv,
    activity_to_markdown,
    conversation_detail_to_markdown,
    conversations_to_csv,
    conversations_to_markdown,
    handoffs_to_csv,
    handoffs_to_markdown,
)
from src.services.observability.events import emit_system_event
from src.workers.queue import DEAD_LETTER_QUEUE_KEY, PROCESSING_QUEUE_KEY, QUEUE_KEY

api_router = APIRouter(prefix="/api/control-room", tags=["control-room"])
ui_router = APIRouter(tags=["control-room"])


def _parse_range(value: str) -> datetime:
    now = datetime.now(timezone.utc)
    value = value.strip().lower()
    try:
        if value.endswith("h") and value[:-1]:
            return now - timedelta(hours=int(value[:-1]))
        if value.endswith("d") and value[:-1]:
            return now - timedelta(days=int(value[:-1]))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid range. Use formats like 24h or 7d.") from exc
    raise HTTPException(status_code=400, detail="Invalid range. Use formats like 24h or 7d.")


def _event_to_schema(event: SystemEvent) -> EventSummary:
    return EventSummary(
        id=event.id,
        created_at=event.created_at,
        component=event.component,
        event_type=event.event_type,
        event_level=event.event_level,
        event_status=event.event_status,
        summary=event.summary,
        customer_phone_masked=event.customer_phone_masked,
        conversation_id=event.conversation_id,
        message_id=event.message_id,
        handoff_id=event.handoff_id,
        details=event.details,
    )


def _message_to_schema(message: Message) -> MessageSummary:
    transcription = message.voice_transcription
    return MessageSummary(
        id=message.id,
        direction=message.direction.value,
        message_type=message.message_type.value,
        content=message.content,
        voice_transcription=transcription.transcript if transcription else None,
        created_at=message.created_at,
    )


def _conversation_row(conversation: Conversation) -> dict:
    customer = conversation.customer
    return {
        "conversation_id": str(conversation.id),
        "customer_name": customer.name,
        "customer_phone": customer.phone_number,
        "status": conversation.status.value,
        "message_count": conversation.message_count,
        "ai_response_count": conversation.ai_response_count,
        "started_at": conversation.created_at.isoformat(),
        "last_message_at": conversation.last_message_at.isoformat() if conversation.last_message_at else "",
    }


def _conversation_to_summary(conversation: Conversation) -> ConversationSummary:
    customer = conversation.customer
    return ConversationSummary(
        conversation_id=conversation.id,
        customer_id=customer.id,
        customer_name=customer.name,
        customer_phone=customer.phone_number,
        status=conversation.status.value,
        message_count=conversation.message_count,
        ai_response_count=conversation.ai_response_count,
        started_at=conversation.created_at,
        last_message_at=conversation.last_message_at,
    )


def _handoff_to_record(handoff: Handoff) -> HandoffRecord:
    customer = handoff.conversation.customer
    return HandoffRecord(
        id=handoff.id,
        conversation_id=handoff.conversation_id,
        customer_name=customer.name,
        customer_phone=customer.phone_number,
        reason=handoff.reason,
        context_summary=handoff.context_summary,
        suggested_response=handoff.suggested_response,
        priority=handoff.priority,
        status=handoff.status.value,
        created_at=handoff.created_at,
        resolved_at=handoff.resolved_at,
        notes=handoff.notes,
    )


def _resolve_store_id(store_id: uuid.UUID | None = None) -> uuid.UUID:
    if store_id is not None:
        return store_id

    configured_store_id = get_settings().store_id
    if not configured_store_id:
        raise HTTPException(status_code=400, detail="STORE_ID is not configured for this deployment")
    try:
        return uuid.UUID(configured_store_id)
    except ValueError as exc:
        raise HTTPException(status_code=500, detail="Configured STORE_ID is not a valid UUID") from exc


async def _list_conversations(
    session: AsyncSession,
    *,
    limit: int,
    status: str | None = None,
) -> list[Conversation]:
    stmt = (
        select(Conversation)
        .options(selectinload(Conversation.customer))
        .order_by(desc(func.coalesce(Conversation.last_message_at, Conversation.created_at)))
        .limit(limit)
    )
    if status == "open":
        stmt = stmt.where(Conversation.status != ConversationStatus.closed)
    elif status == "human_takeover":
        stmt = stmt.where(Conversation.status == ConversationStatus.human_takeover)
    elif status:
        try:
            stmt = stmt.where(Conversation.status == ConversationStatus(status))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=f"Invalid conversation status: {status}") from exc
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def _latest_component_state(repo: SystemEventRepository, component: str) -> str:
    latest = await repo.latest_for_component(component)
    if latest is None:
        return "unknown"
    if latest.event_level == "error":
        return "error"
    if latest.event_level == "warning":
        return "degraded"
    return latest.event_status or "ok"


@api_router.get("/summary", response_model=ControlRoomSummary)
async def get_summary(
    range: str = Query("24h"),
    session: AsyncSession = Depends(get_session),
):
    since = _parse_range(range)
    repo = SystemEventRepository(session)
    redis = get_redis()

    queue_depth = int(await redis.llen(QUEUE_KEY))
    processing_depth = int(await redis.llen(PROCESSING_QUEUE_KEY))
    dead_letter_depth = int(await redis.llen(DEAD_LETTER_QUEUE_KEY))

    open_conversations = await session.scalar(
        select(func.count())
        .select_from(Conversation)
        .where(Conversation.status != ConversationStatus.closed)
    )
    human_takeover_conversations = await session.scalar(
        select(func.count())
        .select_from(Conversation)
        .where(Conversation.status == ConversationStatus.human_takeover)
    )

    latest_event = await repo.latest_event()
    db_ok = await check_db_health()
    redis_ok = await check_redis_health()
    worker_state = await _latest_component_state(repo, "worker")
    whatsapp_state = await _latest_component_state(repo, "whatsapp")
    claude_state = await _latest_component_state(repo, "claude")
    speech_state = await _latest_component_state(repo, "speech")

    health = ControlRoomHealth(
        database="ok" if db_ok else "error",
        redis="ok" if redis_ok else "error",
        worker=worker_state,
        whatsapp=whatsapp_state,
        claude=claude_state,
        speech=speech_state,
    )

    states = [health.database, health.redis, health.worker, health.whatsapp, health.claude, health.speech]
    status = "online"
    if any(state == "error" for state in states):
        status = "degraded"
    elif any(state in {"degraded", "unknown"} for state in states):
        status = "degraded"
    if latest_event is None:
        status = "offline"

    return ControlRoomSummary(
        status=status,
        last_activity_at=latest_event.created_at if latest_event else None,
        queue_depth=queue_depth,
        processing_depth=processing_depth,
        dead_letter_depth=dead_letter_depth,
        metrics=ControlRoomMetricSet(
            messages_received=await repo.count_by_type("webhook_received", since=since),
            messages_processed=await repo.count_by_type("message_processed", since=since),
            messages_failed=await repo.count_by_type("message_processing_failed", since=since),
            auto_replies_sent=await repo.count_by_type("whatsapp_send_succeeded", since=since),
            handoffs_created=await repo.count_by_type("handoff_created", since=since),
            avg_processing_ms=await repo.average_detail_value(
                event_type="message_processed",
                detail_key="total_ms",
                since=since,
            ),
            open_conversations=int(open_conversations or 0),
            human_takeover_conversations=int(human_takeover_conversations or 0),
        ),
        health=health,
    )


@api_router.get("/activity", response_model=list[EventSummary])
async def get_activity(
    limit: int = Query(50, ge=1, le=200),
    range: str = Query("24h"),
    component: str | None = None,
    session: AsyncSession = Depends(get_session),
):
    repo = SystemEventRepository(session)
    events = await repo.list_filtered(
        limit=limit,
        since=_parse_range(range),
        component=component,
    )
    return [_event_to_schema(event) for event in events]


@api_router.get("/errors", response_model=list[EventSummary])
async def get_errors(
    limit: int = Query(50, ge=1, le=200),
    range: str = Query("7d"),
    session: AsyncSession = Depends(get_session),
):
    repo = SystemEventRepository(session)
    events = await repo.list_errors(limit=limit, since=_parse_range(range))
    return [_event_to_schema(event) for event in events]


@api_router.get("/handoffs", response_model=list[HandoffRecord])
async def get_handoffs(
    store_id: uuid.UUID | None = None,
    status: str = Query("pending"),
    limit: int = Query(20, ge=1, le=100),
    session: AsyncSession = Depends(get_session),
):
    repo = HandoffRepository(session)
    try:
        handoff_status = HandoffStatus(status)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid handoff status: {status}") from exc
    handoffs = await repo.get_by_status(_resolve_store_id(store_id), handoff_status, limit=limit)
    return [_handoff_to_record(handoff) for handoff in handoffs]


@api_router.get("/handoffs/{handoff_id}", response_model=HandoffDetail)
async def get_handoff_detail(
    handoff_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
):
    repo = HandoffRepository(session)
    handoff = await repo.get_by_id(handoff_id)
    if handoff is None:
        raise HTTPException(status_code=404, detail="Handoff not found")

    conversation = await get_conversation_detail(handoff.conversation_id, session)
    return HandoffDetail(
        **_handoff_to_record(handoff).model_dump(),
        conversation=conversation,
    )


@api_router.get("/conversations", response_model=list[ConversationSummary])
async def get_conversations(
    status: str | None = Query(None),
    limit: int = Query(25, ge=1, le=100),
    session: AsyncSession = Depends(get_session),
):
    conversations = await _list_conversations(session, limit=limit, status=status)
    return [_conversation_to_summary(conversation) for conversation in conversations]


@api_router.get("/conversations/{conversation_id}", response_model=ConversationRecord)
async def get_conversation_detail(
    conversation_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(
        select(Conversation)
        .options(selectinload(Conversation.customer))
        .where(Conversation.id == conversation_id)
    )
    conversation = result.scalar_one_or_none()
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    message_repo = MessageRepository(session)
    messages = await message_repo.get_for_agent(conversation_id, limit=100)
    customer = conversation.customer
    return ConversationRecord(
        conversation_id=conversation.id,
        status=conversation.status.value,
        started_at=conversation.created_at,
        last_message_at=conversation.last_message_at,
        message_count=conversation.message_count,
        ai_response_count=conversation.ai_response_count,
        customer=ControlRoomCustomer(
            id=customer.id,
            name=customer.name,
            phone=customer.phone_number,
            language=customer.language_preference,
            dialect=customer.detected_dialect,
        ),
        messages=[_message_to_schema(message) for message in messages],
    )


@api_router.post("/handoffs/{handoff_id}/resolve")
async def resolve_handoff(
    handoff_id: uuid.UUID,
    payload: OwnerNoteRequest | None = None,
    session: AsyncSession = Depends(get_session),
):
    repo = HandoffRepository(session)
    handoff = await repo.get_by_id(handoff_id)
    if handoff is None:
        raise HTTPException(status_code=404, detail="Handoff not found")

    note = payload.note if payload and payload.note is not None else handoff.notes
    ok = await repo.resolve(handoff_id, notes=note or "Resolved from Control Room")
    if not ok:
        raise HTTPException(status_code=400, detail="Unable to resolve handoff")

    await emit_system_event(
        event_type="handoff_resolved",
        event_level="info",
        component="dashboard",
        summary="Owner resolved a pending handoff from Control Room.",
        event_status="resolved",
        conversation_id=handoff.conversation_id,
        handoff_id=handoff.id,
        details={"source": "control_room", "has_owner_note": bool(note)},
    )
    return {"success": True}


@api_router.post("/handoffs/{handoff_id}/notes")
async def save_handoff_note(
    handoff_id: uuid.UUID,
    payload: OwnerNoteRequest,
    session: AsyncSession = Depends(get_session),
):
    repo = HandoffRepository(session)
    handoff = await repo.get_by_id(handoff_id)
    if handoff is None:
        raise HTTPException(status_code=404, detail="Handoff not found")

    note = payload.note.strip() if payload.note else None
    ok = await repo.update_notes(handoff_id, note)
    if not ok:
        raise HTTPException(status_code=400, detail="Unable to save handoff note")

    await emit_system_event(
        event_type="handoff_note_saved",
        event_level="info",
        component="dashboard",
        summary="Owner saved an internal handoff note from Control Room.",
        event_status="saved",
        conversation_id=handoff.conversation_id,
        handoff_id=handoff.id,
        details={"source": "control_room", "has_owner_note": bool(note)},
    )
    return {"success": True}


@api_router.post("/conversations/{conversation_id}/takeover")
async def takeover_conversation(
    conversation_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
):
    repo = ConversationRepository(session)
    conversation = await repo.get_by_id(conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    await repo.update_status(conversation_id, ConversationStatus.human_takeover)
    await emit_system_event(
        event_type="conversation_takeover",
        event_level="warning",
        component="dashboard",
        summary="Owner moved a conversation into human takeover.",
        event_status="human_takeover",
        conversation_id=conversation.id,
        details={"source": "control_room"},
    )
    return {"success": True}


@api_router.post("/conversations/{conversation_id}/release")
async def release_conversation(
    conversation_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
):
    repo = ConversationRepository(session)
    conversation = await repo.get_by_id(conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    await repo.update_status(conversation_id, ConversationStatus.bot)
    await emit_system_event(
        event_type="conversation_released",
        event_level="info",
        component="dashboard",
        summary="Owner released a conversation back to the bot.",
        event_status="bot",
        conversation_id=conversation.id,
        details={"source": "control_room"},
    )
    return {"success": True}


@api_router.get("/exports/conversations.csv")
async def export_conversations_csv(
    status: str | None = Query(None),
    limit: int = Query(200, ge=1, le=1000),
    session: AsyncSession = Depends(get_session),
):
    conversations = await _list_conversations(session, limit=limit, status=status)
    content = conversations_to_csv([_conversation_row(conversation) for conversation in conversations])
    headers = {"Content-Disposition": 'attachment; filename="control-room-conversations.csv"'}
    return Response(content=content, media_type="text/csv", headers=headers)


@api_router.get("/exports/conversations.md")
async def export_conversations_markdown(
    conversation_id: uuid.UUID | None = None,
    limit: int = Query(50, ge=1, le=500),
    session: AsyncSession = Depends(get_session),
):
    if conversation_id:
        conversation = await get_conversation_detail(conversation_id, session)
        messages = await MessageRepository(session).get_for_agent(conversation_id, limit=100)
        content = conversation_detail_to_markdown(
            {
                "conversation_id": str(conversation.conversation_id),
                "customer_name": conversation.customer.name,
                "customer_phone": conversation.customer.phone,
                "status": conversation.status,
                "started_at": conversation.started_at.isoformat(),
                "last_message_at": conversation.last_message_at.isoformat() if conversation.last_message_at else "",
                "message_count": conversation.message_count,
            },
            messages,
        )
    else:
        conversations = await _list_conversations(session, limit=limit)
        content = conversations_to_markdown([_conversation_row(conversation) for conversation in conversations])
    headers = {"Content-Disposition": 'attachment; filename="control-room-conversations.md"'}
    return PlainTextResponse(content=content, headers=headers)


@api_router.get("/exports/handoffs.csv")
async def export_handoffs_csv(
    store_id: uuid.UUID | None = None,
    status: str = Query("pending"),
    limit: int = Query(200, ge=1, le=1000),
    session: AsyncSession = Depends(get_session),
):
    repo = HandoffRepository(session)
    try:
        handoff_status = HandoffStatus(status)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid handoff status: {status}") from exc
    handoffs = await repo.get_by_status(_resolve_store_id(store_id), handoff_status, limit=limit)
    content = handoffs_to_csv(handoffs)
    headers = {"Content-Disposition": 'attachment; filename="control-room-handoffs.csv"'}
    return Response(content=content, media_type="text/csv", headers=headers)


@api_router.get("/exports/handoffs.md")
async def export_handoffs_markdown(
    store_id: uuid.UUID | None = None,
    status: str = Query("pending"),
    limit: int = Query(200, ge=1, le=1000),
    session: AsyncSession = Depends(get_session),
):
    repo = HandoffRepository(session)
    try:
        handoff_status = HandoffStatus(status)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid handoff status: {status}") from exc
    handoffs = await repo.get_by_status(_resolve_store_id(store_id), handoff_status, limit=limit)
    content = handoffs_to_markdown(handoffs)
    headers = {"Content-Disposition": 'attachment; filename="control-room-handoffs.md"'}
    return PlainTextResponse(content=content, headers=headers)


@api_router.get("/exports/activity.csv")
async def export_activity_csv(
    range: str = Query("7d"),
    limit: int = Query(500, ge=1, le=2000),
    session: AsyncSession = Depends(get_session),
):
    repo = SystemEventRepository(session)
    events = await repo.list_recent(limit=limit, since=_parse_range(range))
    content = activity_to_csv(events)
    headers = {"Content-Disposition": 'attachment; filename="control-room-activity.csv"'}
    return Response(content=content, media_type="text/csv", headers=headers)


@api_router.get("/exports/activity.md")
async def export_activity_markdown(
    range: str = Query("7d"),
    limit: int = Query(500, ge=1, le=2000),
    session: AsyncSession = Depends(get_session),
):
    repo = SystemEventRepository(session)
    events = await repo.list_recent(limit=limit, since=_parse_range(range))
    content = activity_to_markdown(events)
    headers = {"Content-Disposition": 'attachment; filename="control-room-activity.md"'}
    return PlainTextResponse(content=content, headers=headers)


@ui_router.get("/control-room", response_class=HTMLResponse)
async def control_room_page() -> str:
    default_store_id = get_settings().store_id
    html = """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Control Room</title>
  <style>
    :root {
      --bg: #f4efe6;
      --card: #fffdf8;
      --ink: #1f1a17;
      --muted: #71685f;
      --line: #e8ddd0;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: Georgia, "Times New Roman", serif;
      color: var(--ink);
      background:
        radial-gradient(circle at top left, #efe4d4, transparent 25%),
        linear-gradient(180deg, #f8f3eb 0%, var(--bg) 100%);
    }
    .shell {
      max-width: 1200px;
      margin: 0 auto;
      padding: 32px 20px 56px;
    }
    .hero {
      display: grid;
      gap: 14px;
      margin-bottom: 22px;
    }
    .eyebrow { color: var(--muted); text-transform: uppercase; letter-spacing: 0.08em; font-size: 12px; }
    h1 { margin: 0; font-size: 40px; line-height: 1; }
    .sub { color: var(--muted); max-width: 720px; }
    .status-row, .grid { display: grid; gap: 16px; }
    .status-row { grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); margin-bottom: 16px; }
    .grid { grid-template-columns: 1.2fr 1fr; }
    .stack { display:grid; gap:16px; }
    .card {
      background: rgba(255,255,255,0.86);
      border: 1px solid var(--line);
      border-radius: 18px;
      padding: 18px;
      box-shadow: 0 12px 30px rgba(71, 44, 14, 0.05);
      backdrop-filter: blur(6px);
    }
    .metric { font-size: 32px; margin: 6px 0 0; }
    .label { color: var(--muted); font-size: 14px; }
    .section-title { margin: 0 0 12px; font-size: 20px; }
    .list { display: grid; gap: 10px; }
    .item {
      border: 1px solid var(--line);
      border-radius: 14px;
      padding: 12px;
      background: #fffdfa;
    }
    .item strong { display: block; margin-bottom: 6px; }
    .meta { color: var(--muted); font-size: 13px; }
    .chips { display: flex; flex-wrap: wrap; gap: 8px; }
    .chip {
      border-radius: 999px;
      padding: 4px 10px;
      font-size: 12px;
      background: #efe6da;
      color: #5f5245;
    }
    .chip.ok { background: #d7f1ea; color: #0f5d56; }
    .chip.degraded { background: #f9ecd1; color: #8a5606; }
    .chip.error { background: #f9d9d9; color: #8a1010; }
    .exports { display: flex; gap: 10px; flex-wrap: wrap; margin-top: 12px; }
    .exports a {
      text-decoration: none;
      color: var(--ink);
      border: 1px solid var(--line);
      border-radius: 999px;
      padding: 8px 12px;
      background: #fff;
    }
    .actions { display:flex; flex-wrap:wrap; gap:8px; margin-top:10px; }
    .actions button, .actions a {
      cursor: pointer;
      text-decoration: none;
      color: var(--ink);
      border: 1px solid var(--line);
      border-radius: 999px;
      padding: 7px 11px;
      background: #fff;
      font: inherit;
    }
    .actions button.primary { background: #ecf8f6; border-color: #bedfd8; }
    @media (max-width: 900px) { .grid { grid-template-columns: 1fr; } }
  </style>
</head>
<body>
  <div class="shell">
    <div class="hero">
      <div class="eyebrow">Owner Console</div>
      <h1>Control Room</h1>
      <div class="sub">A single place to see whether the assistant is healthy, what it has been doing, and where it needs attention.</div>
    </div>
    <div id="summary" class="status-row"></div>
    <div class="grid">
      <div class="card">
        <h2 class="section-title">Recent Activity</h2>
        <div id="activity" class="list"></div>
        <div class="exports">
          <a href="/api/control-room/exports/activity.csv">Export activity CSV</a>
          <a href="/api/control-room/exports/activity.md">Export activity Markdown</a>
        </div>
      </div>
      <div class="stack">
        <div class="card">
          <h2 class="section-title">Recent Errors</h2>
          <div id="errors" class="list"></div>
        </div>
        <div class="card">
          <h2 class="section-title">Pending Handoffs</h2>
          <div id="handoffs" class="list"></div>
        </div>
        <div class="card">
          <h2 class="section-title">Conversations</h2>
          <div id="conversations" class="list"></div>
        </div>
      </div>
    </div>
  </div>
  <script>
    const configuredStoreId = "__DEFAULT_STORE_ID__";
    const storeId = new URLSearchParams(window.location.search).get("store_id") || configuredStoreId;
    const handoffUrl = storeId
      ? `/api/control-room/handoffs?store_id=${encodeURIComponent(storeId)}`
      : null;

    async function postAction(url, body = null) {
      const options = { method: "POST" };
      if (body !== null) {
        options.headers = { "Content-Type": "application/json" };
        options.body = JSON.stringify(body);
      }
      const response = await fetch(url, options);
      if (!response.ok) {
        const text = await response.text();
        throw new Error(text || `Request failed: ${response.status}`);
      }
      return response.json();
    }

    function chipClass(value) {
      if (value === "ok" || value === "online") return "chip ok";
      if (value === "error" || value === "offline") return "chip error";
      return "chip degraded";
    }

    function renderSummary(data) {
      const metrics = data.metrics;
      const cards = [
        ["Status", data.status],
        ["Last activity", data.last_activity_at || "n/a"],
        ["Queue depth", `${data.queue_depth} queued / ${data.processing_depth} processing`],
        ["Dead letter", String(data.dead_letter_depth)],
        ["Messages received", String(metrics.messages_received)],
        ["Processed", String(metrics.messages_processed)],
        ["Failed", String(metrics.messages_failed)],
        ["Handoffs", String(metrics.handoffs_created)],
        ["Avg processing", metrics.avg_processing_ms ? `${Math.round(metrics.avg_processing_ms)} ms` : "n/a"],
      ];
      document.getElementById("summary").innerHTML = cards.map(([label, value]) => `
        <div class="card">
          <div class="label">${label}</div>
          <div class="metric">${value}</div>
        </div>
      `).join("");
      const health = Object.entries(data.health).map(([name, value]) => `<span class="${chipClass(value)}">${name}: ${value}</span>`).join("");
      const handoffLinks = storeId
        ? `<a href="/api/control-room/exports/handoffs.csv?store_id=${encodeURIComponent(storeId)}">Export handoffs CSV</a><a href="/api/control-room/exports/handoffs.md?store_id=${encodeURIComponent(storeId)}">Export handoffs Markdown</a>`
        : "";
      document.getElementById("summary").insertAdjacentHTML("beforeend", `<div class="card"><div class="label">Dependency health</div><div class="chips" style="margin-top:12px;">${health}</div><div class="exports"><a href="/api/control-room/exports/conversations.csv">Export conversations CSV</a><a href="/api/control-room/exports/conversations.md">Export conversations Markdown</a>${handoffLinks}</div></div>`);
    }

    function renderList(id, items, mapFn, emptyText) {
      const root = document.getElementById(id);
      if (!items.length) {
        root.innerHTML = `<div class="item"><strong>${emptyText}</strong></div>`;
        return;
      }
      root.innerHTML = items.map(mapFn).join("");
    }

    function escapeHtml(value) {
      return String(value || "")
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#039;");
    }

    async function showHandoffDetail(handoffId) {
      const root = document.getElementById(`handoff-detail-${handoffId}`);
      root.innerHTML = `<div class="meta">Loading handoff context...</div>`;
      const response = await fetch(`/api/control-room/handoffs/${handoffId}`);
      if (!response.ok) {
        root.innerHTML = `<div class="meta">Could not load handoff detail.</div>`;
        return;
      }
      const detail = await response.json();
      const messages = detail.conversation.messages.slice(-6).map(message => `
        <div class="item" style="margin-top:8px;">
          <strong>${escapeHtml(message.direction)} / ${escapeHtml(message.message_type)}</strong>
          <div>${escapeHtml(message.content || message.voice_transcription || "No text content")}</div>
          <div class="meta">${escapeHtml(message.created_at)}</div>
        </div>
      `).join("");
      root.innerHTML = `
        <div class="meta">Context: ${escapeHtml(detail.context_summary)}</div>
        ${detail.suggested_response ? `<div class="meta">Suggested: ${escapeHtml(detail.suggested_response)}</div>` : ""}
        <div style="margin-top:10px;">${messages || "<div class='meta'>No messages available.</div>"}</div>
      `;
    }

    async function load() {
      const [summaryResp, activityResp, errorResp, conversationsResp] = await Promise.all([
        fetch("/api/control-room/summary"),
        fetch("/api/control-room/activity?limit=12"),
        fetch("/api/control-room/errors?limit=8"),
        fetch("/api/control-room/conversations?limit=12"),
      ]);
      renderSummary(await summaryResp.json());
      renderList("activity", await activityResp.json(), event => `
        <div class="item">
          <strong>${event.summary}</strong>
          <div class="meta">${event.component} - ${event.event_type} - ${event.created_at}</div>
        </div>
      `, "No recent activity yet.");
      renderList("errors", await errorResp.json(), event => `
        <div class="item">
          <strong>${event.summary}</strong>
          <div class="meta">${event.component} - ${event.event_level} - ${event.created_at}</div>
        </div>
      `, "No recent errors.");
      renderList("conversations", await conversationsResp.json(), conversation => `
        <div class="item">
          <strong>${conversation.customer_name || conversation.customer_phone}</strong>
          <div class="meta">${conversation.status} - ${conversation.message_count} messages - last activity ${conversation.last_message_at || "n/a"}</div>
          <div class="actions">
            ${conversation.status === "human_takeover"
              ? `<button class="primary" data-action="release" data-id="${conversation.conversation_id}">Release to bot</button>`
              : `<button class="primary" data-action="takeover" data-id="${conversation.conversation_id}">Take over</button>`}
            <a href="/api/control-room/conversations/${conversation.conversation_id}" target="_blank" rel="noreferrer">View JSON</a>
            <a href="/api/control-room/exports/conversations.md?conversation_id=${conversation.conversation_id}" target="_blank" rel="noreferrer">Export Markdown</a>
          </div>
        </div>
      `, "No conversations yet.");
      if (handoffUrl) {
        const handoffResp = await fetch(handoffUrl);
        renderList("handoffs", await handoffResp.json(), handoff => `
          <div class="item">
            <strong>${handoff.reason}</strong>
            <div class="meta">${handoff.customer_name || handoff.customer_phone} - priority ${handoff.priority} - ${handoff.created_at}</div>
            <textarea data-note-for="${handoff.id}" rows="3" style="width:100%;margin-top:10px;border:1px solid var(--line);border-radius:12px;padding:10px;font:inherit;">${escapeHtml(handoff.notes || "")}</textarea>
            <div class="actions">
              <button data-action="show-handoff-detail" data-id="${handoff.id}">Show detail</button>
              <button data-action="save-handoff-note" data-id="${handoff.id}">Save note</button>
              <button class="primary" data-action="resolve-handoff" data-id="${handoff.id}">Resolve with note</button>
              <a href="/api/control-room/handoffs/${handoff.id}" target="_blank" rel="noreferrer">Detail JSON</a>
              <a href="/api/control-room/exports/conversations.md?conversation_id=${handoff.conversation_id}" target="_blank" rel="noreferrer">Conversation export</a>
            </div>
            <div id="handoff-detail-${handoff.id}" style="margin-top:10px;"></div>
          </div>
        `, "No handoffs yet.");
      } else {
        document.getElementById("handoffs").innerHTML = `<div class="item"><strong>STORE_ID is not configured, so handoffs and handoff exports cannot load yet.</strong></div>`;
      }

      document.querySelectorAll("[data-action='resolve-handoff']").forEach(button => {
        button.onclick = async () => {
          button.disabled = true;
          try {
            const textarea = document.querySelector(`[data-note-for='${button.dataset.id}']`);
            await postAction(`/api/control-room/handoffs/${button.dataset.id}/resolve`, { note: textarea ? textarea.value : null });
            await load();
          } catch (error) {
            alert(`Could not resolve handoff: ${error}`);
            button.disabled = false;
          }
        };
      });

      document.querySelectorAll("[data-action='save-handoff-note']").forEach(button => {
        button.onclick = async () => {
          button.disabled = true;
          try {
            const textarea = document.querySelector(`[data-note-for='${button.dataset.id}']`);
            await postAction(`/api/control-room/handoffs/${button.dataset.id}/notes`, { note: textarea ? textarea.value : null });
            await load();
          } catch (error) {
            alert(`Could not save note: ${error}`);
            button.disabled = false;
          }
        };
      });

      document.querySelectorAll("[data-action='show-handoff-detail']").forEach(button => {
        button.onclick = async () => {
          try {
            await showHandoffDetail(button.dataset.id);
          } catch (error) {
            alert(`Could not load handoff detail: ${error}`);
          }
        };
      });

      document.querySelectorAll("[data-action='takeover']").forEach(button => {
        button.onclick = async () => {
          button.disabled = true;
          try {
            await postAction(`/api/control-room/conversations/${button.dataset.id}/takeover`);
            await load();
          } catch (error) {
            alert(`Could not take over conversation: ${error}`);
            button.disabled = false;
          }
        };
      });

      document.querySelectorAll("[data-action='release']").forEach(button => {
        button.onclick = async () => {
          button.disabled = true;
          try {
            await postAction(`/api/control-room/conversations/${button.dataset.id}/release`);
            await load();
          } catch (error) {
            alert(`Could not release conversation: ${error}`);
            button.disabled = false;
          }
        };
      });
    }

    load().catch(error => {
      document.body.insertAdjacentHTML("beforeend", `<div style="padding:20px;color:#8a1010;">Control Room failed to load: ${error}</div>`);
    });
  </script>
</body>
</html>
"""
    return html.replace("__DEFAULT_STORE_ID__", default_store_id)
