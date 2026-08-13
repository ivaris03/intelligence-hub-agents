"""Add persistent chat history for the user memory summary."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260814_0006"
down_revision: str | None = "20260814_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "memory_chat_messages",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("memory_changed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.CheckConstraint("role IN ('user', 'assistant')", name="ck_memory_chat_messages_role"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_memory_chat_messages_user_id", "memory_chat_messages", ["user_id"]
    )
    op.create_index(
        "ix_memory_chat_messages_created_at", "memory_chat_messages", ["created_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_memory_chat_messages_created_at", table_name="memory_chat_messages")
    op.drop_index("ix_memory_chat_messages_user_id", table_name="memory_chat_messages")
    op.drop_table("memory_chat_messages")
