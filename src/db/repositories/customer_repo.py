"""
Customer repository — database access layer for customers.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import structlog
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.privacy import mask_phone
from src.models.customer import Customer

logger = structlog.get_logger(__name__)


class CustomerRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_phone(self, phone_number: str) -> Customer | None:
        result = await self._session.execute(
            select(Customer).where(Customer.phone_number == phone_number)
        )
        return result.scalar_one_or_none()

    async def get_or_create(
        self,
        phone_number: str,
        language_preference: str = "ml",
    ) -> tuple[Customer, bool]:
        """
        Return (customer, created) — created=True if a new record was inserted.

        Normalises the phone number by stripping a leading '+'.
        """
        # Normalise: store without leading +
        normalised = phone_number.lstrip("+")

        customer = await self.get_by_phone(normalised)
        if customer:
            return customer, False

        customer = Customer(
            phone_number=normalised,
            language_preference=language_preference,
        )
        self._session.add(customer)
        await self._session.flush()
        logger.info("customer_created", phone=mask_phone(normalised))
        return customer, True

    async def update_language(
        self,
        customer_id: uuid.UUID,
        language: str,
        dialect: str | None = None,
    ) -> None:
        """Update detected language and dialect from voice transcription."""
        values: dict = {"detected_language": language}
        if dialect is not None:
            values["detected_dialect"] = dialect
        await self._session.execute(
            update(Customer).where(Customer.id == customer_id).values(**values)
        )

    async def update_last_seen(self, customer_id: uuid.UUID) -> None:
        await self._session.execute(
            update(Customer)
            .where(Customer.id == customer_id)
            .values(last_seen_at=datetime.now(timezone.utc))
        )
