from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, ForeignKey, Index, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.models.base import Base, TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from src.models.order import OrderItem


class Product(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "products"

    # Core fields (from Task 2)
    sku: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    category: Mapped[str] = mapped_column(String(100), nullable=False)
    base_price: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    images: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    tags: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)

    # Shopify integration fields (added in Task 6)
    shopify_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    store_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    occasions: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)

    variants: Mapped[list[ProductVariant]] = relationship(back_populates="product")
    order_items: Mapped[list[OrderItem]] = relationship(back_populates="product")

    __table_args__ = (
        Index("ix_products_sku", "sku"),
        Index("ix_products_category", "category"),
        Index("ix_products_is_active", "is_active"),
        Index("ix_products_shopify_id", "shopify_id"),
        Index("ix_products_store_id", "store_id"),
    )


class ProductVariant(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "product_variants"

    product_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("products.id", ondelete="CASCADE"), nullable=False
    )
    sku: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    size: Mapped[str | None] = mapped_column(String(50), nullable=True)
    color: Mapped[str | None] = mapped_column(String(100), nullable=True)
    fabric: Mapped[str | None] = mapped_column(String(100), nullable=True)
    additional_price: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False, default=0)
    stock_quantity: Mapped[int] = mapped_column(nullable=False, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    product: Mapped[Product] = relationship(back_populates="variants")
    order_items: Mapped[list[OrderItem]] = relationship(back_populates="variant")

    __table_args__ = (
        Index("ix_product_variants_product_id", "product_id"),
        Index("ix_product_variants_sku", "sku"),
        Index("ix_product_variants_is_active", "is_active"),
    )
