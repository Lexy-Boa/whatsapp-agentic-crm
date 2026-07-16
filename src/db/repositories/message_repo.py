"""
Message repository — save and retrieve conversation messages.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import structlog
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.models.conversation import (
    Message,
    MessageDirection,
    MessageStatus,
    MessageType,
    VoiceTranscription,
)

logger = structlog.get_logger(__name__)


class MessageRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def save_inbound(
        self,
        conversation_id: uuid.UUID,
        customer_id: uuid.UUID,
        message_type: str,
        content: str | None = None,
        media_url: str | None = None,
        whatsapp_message_id: str | None = None,
    ) -> Message:
        """Persist an inbound (customer → bot) message."""
        msg = Message(
            conversation_id=conversation_id,
            customer_id=customer_id,
            direction=MessageDirection.inbound,
            message_type=_to_message_type(message_type),
            content=content,
            media_url=media_url,
            whatsapp_message_id=whatsapp_message_id,
            status=MessageStatus.delivered,
            created_at=await self._next_created_at(conversation_id),
        )
        self._session.add(msg)
        await self._session.flush()
        return msg

    async def save_outbound(
        self,
        conversation_id: uuid.UUID,
        customer_id: uuid.UUID,
        message_type: str,
        content: str | None = None,
        media_url: str | None = None,
        whatsapp_message_id: str | None = None,
    ) -> Message:
        """Persist an outbound (bot → customer) message."""
        msg = Message(
            conversation_id=conversation_id,
            customer_id=customer_id,
            direction=MessageDirection.outbound,
            message_type=_to_message_type(message_type),
            content=content,
            media_url=media_url,
            whatsapp_message_id=whatsapp_message_id,
            status=MessageStatus.sent if whatsapp_message_id else MessageStatus.pending,
            created_at=await self._next_created_at(conversation_id),
        )
        self._session.add(msg)
        await self._session.flush()
        return msg

    async def save_transcription(
        self,
        message_id: uuid.UUID,
        audio_url: str,
        transcript: str,
        language: str | None = None,
        dialect: str | None = None,
        confidence: float | None = None,
        duration: float | None = None,
    ) -> VoiceTranscription:
        """Attach a voice transcription record to an audio message."""
        vt = VoiceTranscription(
            message_id=message_id,
            audio_url=audio_url,
            transcript=transcript,
            detected_language=language,
            detected_dialect=dialect,
            confidence_score=confidence,
            duration_seconds=duration,
        )
        self._session.add(vt)
        await self._session.flush()
        return vt

    async def get_recent(
        self, conversation_id: uuid.UUID, limit: int = 10
    ) -> list[Message]:
        """Return the most recent messages in a conversation, oldest first."""
        result = await self._session.execute(
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at.desc())
            .limit(limit)
        )
        messages = list(result.scalars().all())
        messages.reverse()  # oldest → newest
        return messages

    async def get_for_agent(
        self, conversation_id: uuid.UUID, limit: int = 50
    ) -> list[Message]:
        """Return recent messages with voice_transcription eagerly loaded, oldest first."""
        result = await self._session.execute(
            select(Message)
            .options(selectinload(Message.voice_transcription))
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at.desc())
            .limit(limit)
        )
        messages = list(result.scalars().all())
        messages.reverse()  # oldest → newest
        return messages

    async def _next_created_at(self, conversation_id: uuid.UUID) -> datetime:
        """
        Return a timestamp that preserves message order inside a conversation.

        Fast inserts can share the same clock tick, which makes recent-message
        queries nondeterministic. Bump ties by one microsecond so chat history
        stays stable without adding a new sequence column yet.
        """
        now = datetime.now(timezone.utc)
        result = await self._session.execute(
            select(Message.created_at)
            .where(Message.conversation_id == conversation_id)
            .order_by(desc(Message.created_at))
            .limit(1)
        )
        latest = result.scalar_one_or_none()
        if latest is None:
            return now
        if latest.tzinfo is None:
            latest = latest.replace(tzinfo=timezone.utc)
        if latest >= now:
            return latest + timedelta(microseconds=1)
        return now


def _to_message_type(raw: str) -> MessageType:
    """Map a string message type to the MessageType enum."""
    mapping = {
        "text": MessageType.text,
        "voice": MessageType.audio,
        "audio": MessageType.audio,
        "image": MessageType.image,
        "document": MessageType.document,
    }
    return mapping.get(raw, MessageType.text)
