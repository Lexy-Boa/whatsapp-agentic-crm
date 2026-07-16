"""
Product repository — database access layer for the products table.
"""

from __future__ import annotations

import uuid

import structlog
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.models.product import Product, ProductVariant

logger = structlog.get_logger(__name__)


class ProductRepository:
    """
    All database operations for Products.

    Pass an AsyncSession at construction; re-use the same instance
    within a single request / unit-of-work.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ------------------------------------------------------------------
    # Basic lookups
    # ------------------------------------------------------------------

    async def get_by_id(self, product_id: uuid.UUID) -> Product | None:
        """Fetch a single product by its primary key."""
        result = await self._session.execute(
            select(Product)
            .options(selectinload(Product.variants))
            .where(Product.id == product_id)
        )
        return result.scalar_one_or_none()

    async def get_by_sku(self, store_id: uuid.UUID | None, sku: str) -> Product | None:
        """Find an active product by SKU, optionally scoped to a store."""
        stmt = (
            select(Product)
            .options(selectinload(Product.variants))
            .where(Product.sku == sku, Product.is_active == True)
        )
        if store_id is not None:
            stmt = stmt.where(Product.store_id == store_id)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_shopify_id(
        self, store_id: uuid.UUID | None, shopify_id: str
    ) -> Product | None:
        """Find a product by its Shopify product ID."""
        stmt = (
            select(Product)
            .options(selectinload(Product.variants))
            .where(Product.shopify_id == shopify_id)
        )
        if store_id is not None:
            stmt = stmt.where(Product.store_id == store_id)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_ids(
        self,
        product_ids: list[uuid.UUID],
        store_id: uuid.UUID | None = None,
    ) -> list[Product]:
        """Batch-fetch active products by primary key, optionally scoped to a store."""
        if not product_ids:
            return []
        stmt = (
            select(Product)
            .options(selectinload(Product.variants))
            .where(Product.id.in_(product_ids), Product.is_active == True)
        )
        if store_id is not None:
            stmt = stmt.where(Product.store_id == store_id)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    # ------------------------------------------------------------------
    # Text search (fallback when vector search is unavailable)
    # ------------------------------------------------------------------

    async def search_by_name(
        self,
        store_id: uuid.UUID | None,
        query: str,
        limit: int = 10,
    ) -> list[Product]:
        """Case-insensitive substring search on product name."""
        stmt = (
            select(Product)
            .options(selectinload(Product.variants))
            .where(Product.name.ilike(f"%{query}%"), Product.is_active == True)
            .limit(limit)
        )
        if store_id is not None:
            stmt = stmt.where(Product.store_id == store_id)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def search_text(
        self,
        store_id: uuid.UUID | None,
        query: str,
        limit: int = 10,
    ) -> list[Product]:
        """Case-insensitive fallback search across demo-relevant product fields."""
        pattern = f"%{query}%"
        stmt = (
            select(Product)
            .options(selectinload(Product.variants))
            .where(
                Product.is_active == True,
                or_(
                    Product.name.ilike(pattern),
                    Product.description.ilike(pattern),
                    Product.category.ilike(pattern),
                    Product.tags.contains([query.lower()]),
                    Product.occasions.contains([query.lower()]),
                ),
            )
            .limit(limit)
        )
        if store_id is not None:
            stmt = stmt.where(Product.store_id == store_id)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    # ------------------------------------------------------------------
    # Write operations
    # ------------------------------------------------------------------

    async def upsert(self, data: dict) -> tuple[Product, bool]:
        """
        Insert or update a product keyed by (store_id, shopify_id).

        Returns (product, created) where created=True if it was inserted.
        """
        shopify_id = data.get("shopify_id")
        store_id = data.get("store_id")

        existing: Product | None = None
        if shopify_id:
            existing = await self.get_by_shopify_id(store_id, shopify_id)

        if existing:
            for key, val in data.items():
                setattr(existing, key, val)
            await self._session.flush()
            return existing, False
        else:
            product = Product(**data)
            self._session.add(product)
            await self._session.flush()
            logger.info("product_created", sku=data.get("sku"), shopify_id=shopify_id)
            return product, True

    async def delete(self, product_id: uuid.UUID) -> bool:
        """Soft-delete a product by marking it inactive."""
        product = await self.get_by_id(product_id)
        if not product:
            return False
        product.is_active = False
        await self._session.flush()
        return True

    async def upsert_variant(
        self,
        *,
        product_id: uuid.UUID,
        sku: str,
        stock_quantity: int,
        size: str | None = None,
        color: str | None = None,
        fabric: str | None = None,
        additional_price: float = 0,
    ) -> tuple[ProductVariant, bool]:
        result = await self._session.execute(
            select(ProductVariant).where(ProductVariant.sku == sku)
        )
        existing = result.scalar_one_or_none()

        if existing:
            existing.product_id = product_id
            existing.size = size
            existing.color = color
            existing.fabric = fabric
            existing.additional_price = additional_price
            existing.stock_quantity = stock_quantity
            existing.is_active = True
            await self._session.flush()
            return existing, False

        variant = ProductVariant(
            product_id=product_id,
            sku=sku,
            size=size,
            color=color,
            fabric=fabric,
            additional_price=additional_price,
            stock_quantity=stock_quantity,
            is_active=True,
        )
        self._session.add(variant)
        await self._session.flush()
        return variant, True
