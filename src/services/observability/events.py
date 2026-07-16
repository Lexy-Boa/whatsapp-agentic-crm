from __future__ import annotations

import uuid

import structlog

from src.core.privacy import redact_operational_data, summarize_exception_for_operations
from src.db.postgres import get_session
from src.db.repositories.system_event_repo import SystemEventRepository

logger = structlog.get_logger(__name__)


async def emit_system_event(
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
) -> None:
    """
    Persist a privacy-safe operational event for Control Room.

    Event emission is intentionally best-effort so operational visibility never
    becomes a new hot-path failure mode.
    """
    try:
        async for session in get_session():
            repo = SystemEventRepository(session)
            await repo.create(
                event_type=event_type,
                event_level=event_level,
                component=component,
                summary=summary,
                event_status=event_status,
                conversation_id=conversation_id,
                message_id=message_id,
                handoff_id=handoff_id,
                customer_phone_masked=customer_phone_masked,
                details=redact_operational_data(details) if details is not None else None,
            )
    except Exception as exc:
        logger.warning(
            "system_event_emit_failed",
            component=component,
            event_type=event_type,
            error=summarize_exception_for_operations(exc),
        )
