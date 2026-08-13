"""Separate Chat and Work conversations."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260814_0003"
down_revision: str | None = "20260813_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "conversations",
        sa.Column("mode", sa.String(20), nullable=False, server_default="chat"),
    )
    op.create_check_constraint(
        "ck_conversations_mode", "conversations", "mode IN ('chat', 'work')"
    )
    op.create_index("ix_conversations_mode", "conversations", ["mode"])


def downgrade() -> None:
    op.drop_index("ix_conversations_mode", table_name="conversations")
    op.drop_constraint("ck_conversations_mode", "conversations", type_="check")
    op.drop_column("conversations", "mode")
