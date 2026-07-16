from __future__ import annotations

import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, Enum, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.models.base import Base, TimestampMixin, UUIDMixin


class HandoffStatus(str, enum.Enum):
    pending = "pending"
    assigned = "assigned"
    resolved = "resolved"


class Handoff(UUIDMixin, TimestampMixin, Base):
    """
    Queued handoff to a human agent.

    Created when the orchestrator decides the conversation needs human attention.
    Linked to the Conversation so agents have full context.
    """

    __tablename__ = "handoffs"

    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
    )
    store_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    reason: Mapped[str] = mapped_column(String(255), nullable=False)
    context_summary: Mapped[str] = mapped_column(Text, nullable=False)
    suggested_response: Mapped[str | None] = mapped_column(Text, nullable=True)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    status: Mapped[HandoffStatus] = mapped_column(
        Enum(HandoffStatus, name="handoff_status"),
        nullable=False,
        default=HandoffStatus.pending,
    )
    assigned_agent_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    conversation: Mapped["Conversation"] = relationship()  # type: ignore[name-defined]

    __table_args__ = (
        Index("ix_handoffs_conversation_id", "conversation_id"),
        Index("ix_handoffs_store_id", "store_id"),
        Index("ix_handoffs_status", "status"),
        Index("ix_handoffs_priority", "priority"),
    )
