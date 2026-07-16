"""
Handoff repository — manage the human-agent handoff queue.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import structlog
from sqlalchemy import desc, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.models.conversation import Conversation
from src.models.customer import Customer
from src.models.handoff import Handoff, HandoffStatus

logger = structlog.get_logger(__name__)


class HandoffRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        conversation_id: uuid.UUID,
        store_id: uuid.UUID,
        reason: str,
        context_summary: str,
        suggested_response: str | None = None,
        priority: int = 5,
    ) -> Handoff:
        """Create a new pending handoff and flush it to the DB."""
        handoff = Handoff(
            conversation_id=conversation_id,
            store_id=store_id,
            reason=reason,
            context_summary=context_summary,
            suggested_response=suggested_response,
            priority=priority,
            status=HandoffStatus.pending,
        )
        self._session.add(handoff)
        await self._session.flush()
        logger.info(
            "handoff_created",
            handoff_id=str(handoff.id),
            reason=reason,
            priority=priority,
        )
        return handoff

    async def get_pending(
        self, store_id: uuid.UUID, limit: int = 20
    ) -> list[Handoff]:
        """Return pending handoffs for a store, ordered by priority (1=urgent first)."""
        result = await self._session.execute(
            select(Handoff)
            .where(
                Handoff.store_id == store_id,
                Handoff.status == HandoffStatus.pending,
            )
            .order_by(Handoff.priority.asc(), Handoff.created_at.asc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def assign(self, handoff_id: uuid.UUID, agent_id: str) -> bool:
        """Assign a handoff to a human agent. Returns False if not found."""
        result = await self._session.execute(
            update(Handoff)
            .where(Handoff.id == handoff_id, Handoff.status == HandoffStatus.pending)
            .values(status=HandoffStatus.assigned, assigned_agent_id=agent_id)
            .returning(Handoff.id)
        )
        return result.scalar_one_or_none() is not None

    async def resolve(self, handoff_id: uuid.UUID, notes: str | None = None) -> bool:
        """Mark a handoff as resolved. Returns False if not found."""
        values: dict = {
            "status": HandoffStatus.resolved,
            "resolved_at": datetime.now(timezone.utc),
        }
        if notes:
            values["notes"] = notes
        result = await self._session.execute(
            update(Handoff)
            .where(Handoff.id == handoff_id)
            .values(**values)
            .returning(Handoff.id)
        )
        return result.scalar_one_or_none() is not None

    async def update_notes(self, handoff_id: uuid.UUID, notes: str | None) -> bool:
        """Replace owner notes on a handoff. Returns False if not found."""
        result = await self._session.execute(
            update(Handoff)
            .where(Handoff.id == handoff_id)
            .values(notes=notes)
            .returning(Handoff.id)
        )
        return result.scalar_one_or_none() is not None

    async def get_by_status(
        self, store_id: uuid.UUID, status: HandoffStatus, limit: int = 20
    ) -> list[Handoff]:
        """Return handoffs for a store filtered by status, with conversation+customer eagerly loaded."""
        result = await self._session.execute(
            select(Handoff)
            .options(
                selectinload(Handoff.conversation).selectinload(Conversation.customer)
            )
            .where(
                Handoff.store_id == store_id,
                Handoff.status == status,
            )
            .order_by(Handoff.priority.asc(), Handoff.created_at.asc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def get_by_id(self, handoff_id: uuid.UUID) -> Handoff | None:
        """Return a handoff by ID with conversation+customer eagerly loaded."""
        result = await self._session.execute(
            select(Handoff)
            .options(
                selectinload(Handoff.conversation).selectinload(Conversation.customer)
            )
            .where(Handoff.id == handoff_id)
        )
        return result.scalar_one_or_none()
