"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-02-21 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Reusable named ENUM type objects.
# SQLAlchemy auto-creates each type when the first table that uses it is created.
# create_type=True (default) means SQLAlchemy manages creation; we drop them explicitly
# in downgrade() because op.drop_table does not cascade to ENUM types.
conversation_status = sa.Enum(
    "open", "pending", "bot", "human_takeover", "closed",
    name="conversation_status",
)
message_direction = sa.Enum("inbound", "outbound", name="message_direction")
message_type = sa.Enum(
    "text", "image", "audio", "video", "document", "template", "interactive", "reaction",
    name="message_type",
)
message_status = sa.Enum(
    "pending", "sent", "delivered", "read", "failed",
    name="message_status",
)
order_status = sa.Enum(
    "pending", "confirmed", "processing", "shipped", "delivered", "cancelled", "returned",
    name="order_status",
)
payment_status = sa.Enum("pending", "paid", "failed", "refunded", name="payment_status")


def upgrade() -> None:
    # --- customers ---
    op.create_table(
        "customers",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("phone_number", sa.String(20), nullable=False),
        sa.Column("name", sa.String(255), nullable=True),
        sa.Column("email", sa.String(255), nullable=True),
        sa.Column("language_preference", sa.String(10), nullable=False, server_default="en"),
        sa.Column("is_blocked", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("phone_number"),
    )
    op.create_index("ix_customers_phone_number", "customers", ["phone_number"])
    op.create_index("ix_customers_is_blocked", "customers", ["is_blocked"])

    # --- customer_tags ---
    op.create_table(
        "customer_tags",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("color", sa.String(7), nullable=False, server_default="#000000"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )

    # --- customer_tag_assignments ---
    op.create_table(
        "customer_tag_assignments",
        sa.Column("customer_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tag_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("assigned_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["customer_id"], ["customers.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tag_id"], ["customer_tags.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("customer_id", "tag_id"),
    )

    # --- products ---
    op.create_table(
        "products",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("sku", sa.String(100), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("category", sa.String(100), nullable=False),
        sa.Column("base_price", sa.Numeric(10, 2), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column(
            "images",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="[]",
        ),
        sa.Column(
            "tags",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="[]",
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("sku"),
    )
    op.create_index("ix_products_sku", "products", ["sku"])
    op.create_index("ix_products_category", "products", ["category"])
    op.create_index("ix_products_is_active", "products", ["is_active"])

    # --- product_variants ---
    op.create_table(
        "product_variants",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("product_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("sku", sa.String(100), nullable=False),
        sa.Column("size", sa.String(50), nullable=True),
        sa.Column("color", sa.String(100), nullable=True),
        sa.Column("fabric", sa.String(100), nullable=True),
        sa.Column("additional_price", sa.Numeric(10, 2), nullable=False, server_default="0"),
        sa.Column("stock_quantity", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("sku"),
    )
    op.create_index("ix_product_variants_product_id", "product_variants", ["product_id"])
    op.create_index("ix_product_variants_sku", "product_variants", ["sku"])
    op.create_index("ix_product_variants_is_active", "product_variants", ["is_active"])

    # --- conversations (creates conversation_status ENUM type automatically) ---
    op.create_table(
        "conversations",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("customer_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", conversation_status, nullable=False),
        sa.Column("whatsapp_conversation_id", sa.String(255), nullable=True),
        sa.Column("assigned_agent", sa.String(255), nullable=True),
        sa.Column("last_message_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("context_summary", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["customer_id"], ["customers.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_conversations_customer_id", "conversations", ["customer_id"])
    op.create_index("ix_conversations_status", "conversations", ["status"])
    op.create_index("ix_conversations_last_message_at", "conversations", ["last_message_at"])

    # --- messages (creates message_direction, message_type, message_status ENUMs) ---
    op.create_table(
        "messages",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("customer_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("direction", message_direction, nullable=False),
        sa.Column("message_type", message_type, nullable=False),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("media_url", sa.String(2048), nullable=True),
        sa.Column("whatsapp_message_id", sa.String(255), nullable=True),
        sa.Column("status", message_status, nullable=False, server_default="pending"),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["customer_id"], ["customers.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("whatsapp_message_id"),
    )
    op.create_index("ix_messages_conversation_id", "messages", ["conversation_id"])
    op.create_index("ix_messages_whatsapp_message_id", "messages", ["whatsapp_message_id"])
    op.create_index("ix_messages_created_at", "messages", ["created_at"])

    # --- voice_transcriptions ---
    op.create_table(
        "voice_transcriptions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("message_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("audio_url", sa.String(2048), nullable=False),
        sa.Column("transcript", sa.Text(), nullable=False),
        sa.Column("detected_language", sa.String(10), nullable=True),
        sa.Column("detected_dialect", sa.String(50), nullable=True),
        sa.Column("confidence_score", sa.Float(), nullable=True),
        sa.Column("duration_seconds", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["message_id"], ["messages.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("message_id"),
    )

    # --- orders (creates order_status and payment_status ENUMs) ---
    op.create_table(
        "orders",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("order_number", sa.String(30), nullable=False),
        sa.Column("customer_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("status", order_status, nullable=False, server_default="pending"),
        sa.Column("subtotal", sa.Numeric(10, 2), nullable=False),
        sa.Column("discount_amount", sa.Numeric(10, 2), nullable=False, server_default="0"),
        sa.Column("tax_amount", sa.Numeric(10, 2), nullable=False, server_default="0"),
        sa.Column("shipping_amount", sa.Numeric(10, 2), nullable=False, server_default="0"),
        sa.Column("total_amount", sa.Numeric(10, 2), nullable=False),
        sa.Column("shipping_address", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("payment_method", sa.String(100), nullable=True),
        sa.Column("payment_status", payment_status, nullable=False, server_default="pending"),
        sa.Column("payment_reference", sa.String(255), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["customer_id"], ["customers.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("order_number"),
    )
    op.create_index("ix_orders_customer_id", "orders", ["customer_id"])
    op.create_index("ix_orders_order_number", "orders", ["order_number"])
    op.create_index("ix_orders_status", "orders", ["status"])
    op.create_index("ix_orders_created_at", "orders", ["created_at"])

    # --- order_items ---
    op.create_table(
        "order_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("order_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("product_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("variant_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("product_name", sa.String(255), nullable=False),
        sa.Column("variant_details", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("unit_price", sa.Numeric(10, 2), nullable=False),
        sa.Column("total_price", sa.Numeric(10, 2), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["variant_id"], ["product_variants.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("order_items")
    op.drop_table("orders")
    op.drop_table("voice_transcriptions")
    op.drop_table("messages")
    op.drop_table("conversations")
    op.drop_table("product_variants")
    op.drop_table("products")
    op.drop_table("customer_tag_assignments")
    op.drop_table("customer_tags")
    op.drop_table("customers")

    # Drop ENUM types explicitly — op.drop_table does not cascade to custom types
    payment_status.drop(op.get_bind(), checkfirst=True)
    order_status.drop(op.get_bind(), checkfirst=True)
    message_status.drop(op.get_bind(), checkfirst=True)
    message_type.drop(op.get_bind(), checkfirst=True)
    message_direction.drop(op.get_bind(), checkfirst=True)
    conversation_status.drop(op.get_bind(), checkfirst=True)
