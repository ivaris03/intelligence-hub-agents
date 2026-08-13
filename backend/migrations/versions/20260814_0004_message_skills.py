"""Allow multiple Skill snapshots on Chat messages."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260814_0004"
down_revision: str | None = "20260814_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "message_skills",
        sa.Column("message_id", sa.Uuid(), nullable=False),
        sa.Column("skill_snapshot_id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["message_id"], ["messages.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["skill_snapshot_id"], ["skill_snapshots.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("message_id", "skill_snapshot_id"),
        sa.UniqueConstraint("message_id", "position"),
    )
    op.execute(
        sa.text(
            """
            INSERT INTO message_skills (message_id, skill_snapshot_id, position)
            SELECT id, skill_snapshot_id, 0
            FROM messages
            WHERE skill_snapshot_id IS NOT NULL
            """
        )
    )


def downgrade() -> None:
    op.drop_table("message_skills")
