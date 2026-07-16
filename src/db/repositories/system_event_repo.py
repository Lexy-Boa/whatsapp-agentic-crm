"""
System event repository - privacy-safe operational event storage for Control Room.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Float, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.system_event import SystemEvent


class SystemEventRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        *,
        event_type: str,
        event_level: str,
        component: str,
        summary: str,
        event_status: str | None = None,
        conversation_id: uuid.UUID | None = None,
        message_id: uuid.UUID | None = None,
        handoff_id: uuid.UUID | None = None,
        customer_phone_masked: str | None = None,
        details: dict | None = None,
    ) -> SystemEvent:
        event = SystemEvent(
            event_type=event_type,
            event_level=event_level,
            event_status=event_status,
            component=component,
            summary=summary,
            conversation_id=conversation_id,
            message_id=message_id,
            handoff_id=handoff_id,
            customer_phone_masked=customer_phone_masked,
            details=details,
        )
        self._session.add(event)
        await self._session.flush()
        return event

    async def list_recent(self, *, limit: int = 50, since: datetime | None = None) -> list[SystemEvent]:
        stmt = select(SystemEvent)
        if since is not None:
            stmt = stmt.where(SystemEvent.created_at >= since)
        stmt = stmt.order_by(desc(SystemEvent.created_at)).limit(limit)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def list_filtered(
        self,
        *,
        limit: int = 50,
        since: datetime | None = None,
        component: str | None = None,
        event_level: str | None = None,
    ) -> list[SystemEvent]:
        stmt = select(SystemEvent)
        if since is not None:
            stmt = stmt.where(SystemEvent.created_at >= since)
        if component:
            stmt = stmt.where(SystemEvent.component == component)
        if event_level:
            stmt = stmt.where(SystemEvent.event_level == event_level)
        stmt = stmt.order_by(desc(SystemEvent.created_at)).limit(limit)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def list_errors(self, *, limit: int = 50, since: datetime | None = None) -> list[SystemEvent]:
        stmt = select(SystemEvent).where(SystemEvent.event_level.in_(("warning", "error")))
        if since is not None:
            stmt = stmt.where(SystemEvent.created_at >= since)
        stmt = stmt.order_by(desc(SystemEvent.created_at)).limit(limit)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def count_by_type(self, event_type: str, *, since: datetime | None = None) -> int:
        stmt = select(func.count()).select_from(SystemEvent).where(SystemEvent.event_type == event_type)
        if since is not None:
            stmt = stmt.where(SystemEvent.created_at >= since)
        result = await self._session.execute(stmt)
        return int(result.scalar() or 0)

    async def average_detail_value(
        self,
        *,
        event_type: str,
        detail_key: str,
        since: datetime | None = None,
    ) -> float | None:
        stmt = select(func.avg(SystemEvent.details[detail_key].astext.cast(Float)))
        stmt = stmt.where(SystemEvent.event_type == event_type)
        if since is not None:
            stmt = stmt.where(SystemEvent.created_at >= since)
        result = await self._session.execute(stmt)
        value = result.scalar()
        return float(value) if value is not None else None

    async def latest_for_component(self, component: str) -> SystemEvent | None:
        result = await self._session.execute(
            select(SystemEvent)
            .where(SystemEvent.component == component)
            .order_by(desc(SystemEvent.created_at))
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def latest_for_event_type(self, event_type: str) -> SystemEvent | None:
        result = await self._session.execute(
            select(SystemEvent)
            .where(SystemEvent.event_type == event_type)
            .order_by(desc(SystemEvent.created_at))
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def latest_event(self) -> SystemEvent | None:
        result = await self._session.execute(
            select(SystemEvent)
            .order_by(desc(SystemEvent.created_at))
            .limit(1)
        )
        return result.scalar_one_or_none()
