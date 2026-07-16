"""
Conversation repository — database access layer for conversations.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import structlog
from sqlalchemy import desc, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.models.conversation import Conversation, ConversationStatus
from src.models.customer import Customer

logger = structlog.get_logger(__name__)


class ConversationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_active(self, customer_id: uuid.UUID) -> Conversation | None:
        """
        Return the most recent non-closed conversation for this customer.

        "Active" means the bot can still post to it (status != closed).
        """
        result = await self._session.execute(
            select(Conversation)
            .where(
                Conversation.customer_id == customer_id,
                Conversation.status != ConversationStatus.closed,
            )
            .order_by(desc(Conversation.created_at))
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def create(self, customer_id: uuid.UUID) -> Conversation:
        conv = Conversation(
            customer_id=customer_id,
            status=ConversationStatus.bot,
            message_count=0,
            ai_response_count=0,
        )
        self._session.add(conv)
        await self._session.flush()
        logger.info("conversation_created", customer_id=str(customer_id))
        return conv

    async def update_status(
        self, conversation_id: uuid.UUID, status: ConversationStatus
    ) -> None:
        await self._session.execute(
            update(Conversation)
            .where(Conversation.id == conversation_id)
            .values(status=status)
        )

    async def increment_message_count(self, conversation_id: uuid.UUID) -> None:
        await self._session.execute(
            update(Conversation)
            .where(Conversation.id == conversation_id)
            .values(
                message_count=Conversation.message_count + 1,
                last_message_at=datetime.now(timezone.utc),
            )
        )

    async def increment_ai_response_count(self, conversation_id: uuid.UUID) -> None:
        await self._session.execute(
            update(Conversation)
            .where(Conversation.id == conversation_id)
            .values(ai_response_count=Conversation.ai_response_count + 1)
        )

    async def get_by_id(self, conversation_id: uuid.UUID) -> Conversation | None:
        """Return a conversation by ID with customer eagerly loaded."""
        result = await self._session.execute(
            select(Conversation)
            .options(selectinload(Conversation.customer))
            .where(Conversation.id == conversation_id)
        )
        return result.scalar_one_or_none()
