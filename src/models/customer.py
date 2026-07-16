from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.models.base import Base, TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from src.models.conversation import Conversation, Message
    from src.models.order import Order


class Customer(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "customers"

    phone_number: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    language_preference: Mapped[str] = mapped_column(String(10), nullable=False, default="en")
    is_blocked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Detected from voice transcription / message content (added Task 7)
    detected_language: Mapped[str | None] = mapped_column(String(10), nullable=True)
    detected_dialect: Mapped[str | None] = mapped_column(String(50), nullable=True)

    conversations: Mapped[list[Conversation]] = relationship(back_populates="customer")
    orders: Mapped[list[Order]] = relationship(back_populates="customer")
    messages: Mapped[list[Message]] = relationship(back_populates="customer")
    tag_assignments: Mapped[list[CustomerTagAssignment]] = relationship(back_populates="customer")

    __table_args__ = (
        Index("ix_customers_phone_number", "phone_number"),
        Index("ix_customers_is_blocked", "is_blocked"),
    )


class CustomerTag(UUIDMixin, Base):
    __tablename__ = "customer_tags"

    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    color: Mapped[str] = mapped_column(String(7), nullable=False, default="#000000")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    assignments: Mapped[list[CustomerTagAssignment]] = relationship(back_populates="tag")


class CustomerTagAssignment(Base):
    __tablename__ = "customer_tag_assignments"

    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("customers.id", ondelete="CASCADE"), primary_key=True
    )
    tag_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("customer_tags.id", ondelete="CASCADE"), primary_key=True
    )
    assigned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    customer: Mapped[Customer] = relationship(back_populates="tag_assignments")
    tag: Mapped[CustomerTag] = relationship(back_populates="assignments")
