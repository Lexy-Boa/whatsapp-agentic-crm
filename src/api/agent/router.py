"""
Agent dashboard API router — REST endpoints for human agent handoff management.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.agent.schemas import (
    ConversationDetail,
    CustomerInfo,
    HandoffDetail,
    HandoffSummary,
    MessageInfo,
)
from src.config import get_settings
from src.core.privacy import mask_phone
from src.db.postgres import get_session
from src.db.repositories.conversation_repo import ConversationRepository
from src.db.repositories.handoff_repo import HandoffRepository
from src.db.repositories.message_repo import MessageRepository
from src.models.conversation import ConversationStatus, Message
from src.models.handoff import HandoffStatus
from src.services.whatsapp.client import WhatsAppClient
from src.services.whatsapp.policy import WhatsAppPolicy

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/agent", tags=["agent"])


# ---------------------------------------------------------------------------
# Request body models
# ---------------------------------------------------------------------------

class AssignRequest(BaseModel):
    agent_id: str


class ResolveRequest(BaseModel):
    notes: str | None = None


class SendMessageRequest(BaseModel):
    text: str
    agent_id: str


class TakeoverRequest(BaseModel):
    agent_id: str


# ---------------------------------------------------------------------------
# Module-level helper
# ---------------------------------------------------------------------------

def _message_to_info(msg: Message) -> MessageInfo:
    vt = msg.voice_transcription
    return MessageInfo(
        id=msg.id,
        direction=msg.direction.value,
        message_type=msg.message_type.value,
        content=msg.content,
        voice_transcription=vt.transcript if vt else None,
        created_at=msg.created_at,
    )


# ---------------------------------------------------------------------------
# Handoff endpoints
# ---------------------------------------------------------------------------

@router.get("/handoffs", response_model=list[HandoffSummary])
async def list_handoffs(
    store_id: uuid.UUID,
    status: str = "pending",
    limit: int = 20,
    session: AsyncSession = Depends(get_session),
):
    """List handoffs for a store filtered by status."""
    try:
        handoff_status = HandoffStatus(status)
    except ValueError:
        valid = [s.value for s in HandoffStatus]
        raise HTTPException(status_code=400, detail=f"Invalid status '{status}'. Valid values: {valid}")

    handoff_repo = HandoffRepository(session)
    handoffs = await handoff_repo.get_by_status(store_id, handoff_status, limit=limit)

    now = datetime.now(timezone.utc)
    summaries = []
    for h in handoffs:
        conv = h.conversation
        customer = conv.customer
        created_at = h.created_at
        # Ensure timezone-aware for arithmetic
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        minutes_waiting = int((now - created_at).total_seconds() / 60)
        summaries.append(
            HandoffSummary(
                id=h.id,
                customer_name=customer.name,
                customer_phone=customer.phone_number,
                reason=h.reason,
                priority=h.priority,
                context_summary=h.context_summary[:200],
                created_at=h.created_at,
                minutes_waiting=minutes_waiting,
            )
        )
    return summaries


@router.get("/handoffs/{handoff_id}", response_model=HandoffDetail)
async def get_handoff_detail(
    handoff_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
):
    """Get full detail for a single handoff including recent messages."""
    handoff_repo = HandoffRepository(session)
    msg_repo = MessageRepository(session)

    handoff = await handoff_repo.get_by_id(handoff_id)
    if not handoff:
        raise HTTPException(status_code=404, detail="Handoff not found")

    conv = handoff.conversation
    customer = conv.customer
    messages = await msg_repo.get_for_agent(conv.id, limit=20)

    return HandoffDetail(
        id=handoff.id,
        conversation_id=conv.id,
        customer=CustomerInfo(
            id=customer.id,
            phone=customer.phone_number,
            name=customer.name,
            language=customer.language_preference,
            dialect=customer.detected_dialect,
        ),
        reason=handoff.reason,
        context_summary=handoff.context_summary,
        suggested_response=handoff.suggested_response,
        priority=handoff.priority,
        status=handoff.status.value,
        created_at=handoff.created_at,
        messages=[_message_to_info(m) for m in messages],
    )


@router.post("/handoffs/{handoff_id}/assign")
async def assign_handoff(
    handoff_id: uuid.UUID,
    body: AssignRequest,
    session: AsyncSession = Depends(get_session),
):
    """Assign a pending handoff to a human agent."""
    handoff_repo = HandoffRepository(session)
    ok = await handoff_repo.assign(handoff_id, body.agent_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Handoff not found or not in pending state")
    logger.info("handoff_assigned", handoff_id=str(handoff_id), agent_id=body.agent_id)
    return {"success": True}


@router.post("/handoffs/{handoff_id}/resolve")
async def resolve_handoff(
    handoff_id: uuid.UUID,
    body: ResolveRequest,
    session: AsyncSession = Depends(get_session),
):
    """Mark a handoff as resolved."""
    handoff_repo = HandoffRepository(session)
    ok = await handoff_repo.resolve(handoff_id, notes=body.notes)
    if not ok:
        raise HTTPException(status_code=404, detail="Handoff not found")
    logger.info("handoff_resolved", handoff_id=str(handoff_id))
    return {"success": True}


# ---------------------------------------------------------------------------
# Conversation endpoints
# ---------------------------------------------------------------------------

@router.get("/conversations/{conversation_id}", response_model=ConversationDetail)
async def get_conversation(
    conversation_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
):
    """Get a conversation with recent messages for the agent dashboard."""
    conv_repo = ConversationRepository(session)
    msg_repo = MessageRepository(session)

    conv = await conv_repo.get_by_id(conversation_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")

    customer = conv.customer
    messages = await msg_repo.get_for_agent(conversation_id, limit=50)

    return ConversationDetail(
        id=conv.id,
        customer=CustomerInfo(
            id=customer.id,
            phone=customer.phone_number,
            name=customer.name,
            language=customer.language_preference,
            dialect=customer.detected_dialect,
        ),
        status=conv.status.value,
        started_at=conv.created_at,
        message_count=conv.message_count,
        messages=[_message_to_info(m) for m in messages],
    )


@router.post("/conversations/{conversation_id}/send")
async def send_message(
    conversation_id: uuid.UUID,
    body: SendMessageRequest,
    session: AsyncSession = Depends(get_session),
):
    """Send a text message to the customer as a human agent."""
    conv_repo = ConversationRepository(session)
    msg_repo = MessageRepository(session)

    conv = await conv_repo.get_by_id(conversation_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")

    settings = get_settings()
    whatsapp = WhatsAppClient(access_token=settings.whatsapp_access_token, phone_number_id=settings.whatsapp_phone_number_id)
    policy = WhatsAppPolicy(
        mode=settings.whatsapp_policy_mode,  # type: ignore[arg-type]
        customer_service_window_hours=settings.whatsapp_customer_service_window_hours,
    )
    try:
        decision = policy.evaluate_freeform_send(conv.last_message_at)
        if not decision.allowed:
            logger.warning(
                "agent_message_blocked_by_policy",
                conversation_id=str(conversation_id),
                customer_phone=mask_phone(conv.customer.phone_number),
                reason=decision.reason,
            )
            return {
                "success": False,
                "message_id": None,
                "error": "Free-form WhatsApp message blocked by policy; template flow required.",
            }

        send_result = await whatsapp.send_text(conv.customer.phone_number, body.text)
        if send_result.success:
            msg = await msg_repo.save_outbound(
                conversation_id=conversation_id,
                customer_id=conv.customer_id,
                message_type="text",
                content=body.text,
                whatsapp_message_id=send_result.message_id,
            )
            logger.info(
                "agent_message_sent",
                conversation_id=str(conversation_id),
                agent_id=body.agent_id,
                message_id=str(msg.id),
            )
            return {"success": True, "message_id": str(msg.id), "error": None}
        else:
            logger.warning(
                "agent_message_send_failed",
                conversation_id=str(conversation_id),
                error=send_result.error,
            )
            return {"success": False, "message_id": None, "error": send_result.error}
    finally:
        await whatsapp.close()


@router.post("/conversations/{conversation_id}/takeover")
async def takeover_conversation(
    conversation_id: uuid.UUID,
    body: TakeoverRequest,
    session: AsyncSession = Depends(get_session),
):
    """Set conversation to human_takeover status (disables AI responses)."""
    conv_repo = ConversationRepository(session)

    conv = await conv_repo.get_by_id(conversation_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")

    await conv_repo.update_status(conversation_id, ConversationStatus.human_takeover)
    logger.info(
        "conversation_takeover",
        conversation_id=str(conversation_id),
        agent_id=body.agent_id,
    )
    return {"success": True}


@router.post("/conversations/{conversation_id}/release")
async def release_conversation(
    conversation_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
):
    """Release human control — bot resumes handling the conversation."""
    conv_repo = ConversationRepository(session)

    conv = await conv_repo.get_by_id(conversation_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")

    await conv_repo.update_status(conversation_id, ConversationStatus.bot)
    logger.info("conversation_released", conversation_id=str(conversation_id))
    return {"success": True}
