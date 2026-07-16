"""add orchestrator fields

Revision ID: 0003
Revises: 0002
Create Date: 2026-02-21 00:00:00.000000

Adds fields needed by the conversation orchestrator (Task 7):
  customers:     detected_language, detected_dialect
  conversations: message_count, ai_response_count
  new table:     handoffs
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

handoff_status = sa.Enum("pending", "assigned", "resolved", name="handoff_status")


def upgrade() -> None:
    # --- customers: language/dialect detection fields ---
    op.add_column("customers", sa.Column("detected_language", sa.String(10), nullable=True))
    op.add_column("customers", sa.Column("detected_dialect", sa.String(50), nullable=True))

    # --- conversations: message counters ---
    op.add_column(
        "conversations",
        sa.Column("message_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "conversations",
        sa.Column("ai_response_count", sa.Integer(), nullable=False, server_default="0"),
    )

    # --- handoffs table ---
    op.create_table(
        "handoffs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("store_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("reason", sa.String(255), nullable=False),
        sa.Column("context_summary", sa.Text(), nullable=False),
        sa.Column("suggested_response", sa.Text(), nullable=True),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("status", handoff_status, nullable=False, server_default="pending"),
        sa.Column("assigned_agent_id", sa.String(255), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["conversation_id"], ["conversations.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_handoffs_conversation_id", "handoffs", ["conversation_id"])
    op.create_index("ix_handoffs_store_id", "handoffs", ["store_id"])
    op.create_index("ix_handoffs_status", "handoffs", ["status"])
    op.create_index("ix_handoffs_priority", "handoffs", ["priority"])


def downgrade() -> None:
    op.drop_index("ix_handoffs_priority", table_name="handoffs")
    op.drop_index("ix_handoffs_status", table_name="handoffs")
    op.drop_index("ix_handoffs_store_id", table_name="handoffs")
    op.drop_index("ix_handoffs_conversation_id", table_name="handoffs")
    op.drop_table("handoffs")
    handoff_status.drop(op.get_bind(), checkfirst=True)

    op.drop_column("conversations", "ai_response_count")
    op.drop_column("conversations", "message_count")
    op.drop_column("customers", "detected_dialect")
    op.drop_column("customers", "detected_language")
