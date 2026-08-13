"""Queue idle conversations for nightly memory refinement."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260814_0007"
down_revision: str | None = "20260814_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "pending_memory_conversations",
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("through_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("process_after", sa.DateTime(timezone=True), nullable=False),
        sa.Column("queued_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["conversation_id"], ["conversations.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("conversation_id"),
    )
    op.create_index(
        "ix_pending_memory_conversations_user_id",
        "pending_memory_conversations",
        ["user_id"],
    )
    op.create_index(
        "ix_pending_memory_conversations_process_after",
        "pending_memory_conversations",
        ["process_after"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_pending_memory_conversations_process_after",
        table_name="pending_memory_conversations",
    )
    op.drop_index(
        "ix_pending_memory_conversations_user_id",
        table_name="pending_memory_conversations",
    )
    op.drop_table("pending_memory_conversations")
