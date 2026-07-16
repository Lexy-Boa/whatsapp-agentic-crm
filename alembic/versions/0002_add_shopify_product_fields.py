"""add shopify product fields

Revision ID: 0002
Revises: 0001
Create Date: 2026-02-21 00:00:00.000000

Adds three columns to the products table to support Shopify integration
and vector-based product search (Task 6):
  - shopify_id: tracks the Shopify product ID for sync
  - store_id:   multi-store support (nullable UUID)
  - occasions:  JSONB list of occasion tags (wedding, festival, etc.)
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "products",
        sa.Column("shopify_id", sa.String(255), nullable=True),
    )
    op.add_column(
        "products",
        sa.Column("store_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "products",
        sa.Column(
            "occasions",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="[]",
        ),
    )

    op.create_index("ix_products_shopify_id", "products", ["shopify_id"])
    op.create_index("ix_products_store_id", "products", ["store_id"])


def downgrade() -> None:
    op.drop_index("ix_products_store_id", table_name="products")
    op.drop_index("ix_products_shopify_id", table_name="products")
    op.drop_column("products", "occasions")
    op.drop_column("products", "store_id")
    op.drop_column("products", "shopify_id")
