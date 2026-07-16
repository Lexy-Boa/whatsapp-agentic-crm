from __future__ import annotations

import uuid

from sqlalchemy import Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base, TimestampMixin, UUIDMixin


class SystemEvent(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "system_events"

    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    event_level: Mapped[str] = mapped_column(String(20), nullable=False)
    event_status: Mapped[str | None] = mapped_column(String(30), nullable=True)
    component: Mapped[str] = mapped_column(String(50), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)

    conversation_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    message_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    handoff_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    customer_phone_masked: Mapped[str | None] = mapped_column(String(32), nullable=True)
    details: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    __table_args__ = (
        Index("ix_system_events_created_at", "created_at"),
        Index("ix_system_events_component", "component"),
        Index("ix_system_events_event_level", "event_level"),
        Index("ix_system_events_conversation_id", "conversation_id"),
        Index("ix_system_events_event_type", "event_type"),
    )
