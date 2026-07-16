"""add system events

Revision ID: 0004
Revises: 0003
Create Date: 2026-04-15 00:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "system_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_type", sa.String(length=100), nullable=False),
        sa.Column("event_level", sa.String(length=20), nullable=False),
        sa.Column("event_status", sa.String(length=30), nullable=True),
        sa.Column("component", sa.String(length=50), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("message_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("handoff_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("customer_phone_masked", sa.String(length=32), nullable=True),
        sa.Column("details", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_system_events_created_at", "system_events", ["created_at"])
    op.create_index("ix_system_events_component", "system_events", ["component"])
    op.create_index("ix_system_events_event_level", "system_events", ["event_level"])
    op.create_index("ix_system_events_conversation_id", "system_events", ["conversation_id"])
    op.create_index("ix_system_events_event_type", "system_events", ["event_type"])


def downgrade() -> None:
    op.drop_index("ix_system_events_event_type", table_name="system_events")
    op.drop_index("ix_system_events_conversation_id", table_name="system_events")
    op.drop_index("ix_system_events_event_level", table_name="system_events")
    op.drop_index("ix_system_events_component", table_name="system_events")
    op.drop_index("ix_system_events_created_at", table_name="system_events")
    op.drop_table("system_events")
