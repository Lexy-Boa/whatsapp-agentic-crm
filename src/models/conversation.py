from __future__ import annotations

import enum
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Enum, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.models.base import Base, TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from src.models.customer import Customer
    from src.models.order import Order


class ConversationStatus(str, enum.Enum):
    open = "open"
    pending = "pending"
    bot = "bot"
    human_takeover = "human_takeover"
    closed = "closed"


class MessageDirection(str, enum.Enum):
    inbound = "inbound"
    outbound = "outbound"


class MessageType(str, enum.Enum):
    text = "text"
    image = "image"
    audio = "audio"
    video = "video"
    document = "document"
    template = "template"
    interactive = "interactive"
    reaction = "reaction"


class MessageStatus(str, enum.Enum):
    pending = "pending"
    sent = "sent"
    delivered = "delivered"
    read = "read"
    failed = "failed"


class Conversation(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "conversations"

    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("customers.id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[ConversationStatus] = mapped_column(
        Enum(ConversationStatus, name="conversation_status"),
        nullable=False,
        default=ConversationStatus.bot,
    )
    whatsapp_conversation_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    assigned_agent: Mapped[str | None] = mapped_column(String(255), nullable=True)
    last_message_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    context_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Conversation metrics (added Task 7)
    message_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    ai_response_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    customer: Mapped[Customer] = relationship(back_populates="conversations")
    messages: Mapped[list[Message]] = relationship(back_populates="conversation")
    orders: Mapped[list[Order]] = relationship(back_populates="conversation")

    __table_args__ = (
        Index("ix_conversations_customer_id", "customer_id"),
        Index("ix_conversations_status", "status"),
        Index("ix_conversations_last_message_at", "last_message_at"),
    )


class Message(UUIDMixin, Base):
    __tablename__ = "messages"

    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False
    )
    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("customers.id", ondelete="RESTRICT"), nullable=False
    )
    direction: Mapped[MessageDirection] = mapped_column(
        Enum(MessageDirection, name="message_direction"), nullable=False
    )
    message_type: Mapped[MessageType] = mapped_column(
        Enum(MessageType, name="message_type"), nullable=False
    )
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    media_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    whatsapp_message_id: Mapped[str | None] = mapped_column(String(255), nullable=True, unique=True)
    status: Mapped[MessageStatus] = mapped_column(
        Enum(MessageStatus, name="message_status"),
        nullable=False,
        default=MessageStatus.pending,
    )
    # Named "metadata_" on the Python side to avoid shadowing SQLAlchemy's internal attribute
    metadata_: Mapped[dict | None] = mapped_column("metadata", JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    conversation: Mapped[Conversation] = relationship(back_populates="messages")
    customer: Mapped[Customer] = relationship(back_populates="messages")
    voice_transcription: Mapped[VoiceTranscription | None] = relationship(
        back_populates="message", uselist=False
    )

    __table_args__ = (
        Index("ix_messages_conversation_id", "conversation_id"),
        Index("ix_messages_whatsapp_message_id", "whatsapp_message_id"),
        Index("ix_messages_created_at", "created_at"),
    )


class VoiceTranscription(UUIDMixin, Base):
    __tablename__ = "voice_transcriptions"

    message_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("messages.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    audio_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    transcript: Mapped[str] = mapped_column(Text, nullable=False)
    detected_language: Mapped[str | None] = mapped_column(String(10), nullable=True)
    detected_dialect: Mapped[str | None] = mapped_column(String(50), nullable=True)
    confidence_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    duration_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    message: Mapped[Message] = relationship(back_populates="voice_transcription")
