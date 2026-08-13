"""Add phone authentication, RBAC, and per-user data ownership."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260814_0005"
down_revision: str | None = "20260814_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ADMIN_ID = "10000000-0000-4000-8000-000000000000"
PASSWORD_HASH = (
    "pbkdf2_sha256$600000$aW50ZWxodWItc2VlZC12MQ$"
    "tNPkEEFOw0P3gDzM_JbTAQWlxiRjVSuCM3dvdOc_XSk"
)


def upgrade() -> None:
    uuid = postgresql.UUID(as_uuid=True)
    op.create_table(
        "users",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("phone", sa.String(11), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("display_name", sa.String(80), nullable=False),
        sa.Column("role", sa.String(20), nullable=False, server_default="member"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.CheckConstraint("role IN ('admin', 'member')", name="ck_users_role"),
        sa.UniqueConstraint("phone"),
    )
    op.create_index("ix_users_phone", "users", ["phone"], unique=True)
    op.create_index("ix_users_role", "users", ["role"])
    op.create_index("ix_users_is_active", "users", ["is_active"])

    values = [
        f"('{ADMIN_ID}', '13900000001', '{PASSWORD_HASH}', '管理员', 'admin', TRUE)"
    ]
    for index in range(1, 21):
        user_id = f"10000000-0000-4000-8000-{index:012d}"
        values.append(
            f"('{user_id}', '137000000{index:02d}', '{PASSWORD_HASH}', "
            f"'用户{index:02d}', 'member', TRUE)"
        )
    op.execute(
        "INSERT INTO users (id, phone, password_hash, display_name, role, is_active) VALUES "
        + ",".join(values)
    )

    for table in ("conversations", "skills", "app_settings", "memory_summaries"):
        op.add_column(table, sa.Column("user_id", uuid, nullable=True))
        op.execute(f"UPDATE {table} SET user_id = '{ADMIN_ID}' WHERE user_id IS NULL")
        op.alter_column(table, "user_id", nullable=False)
        op.create_foreign_key(
            f"fk_{table}_user_id",
            table,
            "users",
            ["user_id"],
            ["id"],
            ondelete="CASCADE",
        )
        op.create_index(f"ix_{table}_user_id", table, ["user_id"])

    op.drop_constraint("skills_normalized_name_key", "skills", type_="unique")
    op.create_unique_constraint(
        "uq_skills_user_id_normalized_name", "skills", ["user_id", "normalized_name"]
    )
    op.create_unique_constraint("uq_app_settings_user_id", "app_settings", ["user_id"])
    op.drop_constraint("ck_memory_summaries_singleton", "memory_summaries", type_="check")
    op.create_unique_constraint("uq_memory_summaries_user_id", "memory_summaries", ["user_id"])

    for table in ("app_settings", "memory_summaries"):
        sequence = f"{table}_id_seq"
        op.execute(f"CREATE SEQUENCE IF NOT EXISTS {sequence} OWNED BY {table}.id")
        op.execute(
            f"SELECT setval('{sequence}', COALESCE((SELECT MAX(id) FROM {table}), 0) + 1, false)"
        )
        op.execute(f"ALTER TABLE {table} ALTER COLUMN id SET DEFAULT nextval('{sequence}')")


def downgrade() -> None:
    op.execute(f"DELETE FROM users WHERE id <> '{ADMIN_ID}'")
    for table in ("memory_summaries", "app_settings"):
        op.execute(f"DELETE FROM {table} WHERE user_id <> '{ADMIN_ID}'")
    op.drop_constraint("uq_memory_summaries_user_id", "memory_summaries", type_="unique")
    op.create_check_constraint(
        "ck_memory_summaries_singleton", "memory_summaries", "id = 1"
    )
    op.drop_constraint("uq_app_settings_user_id", "app_settings", type_="unique")
    op.drop_constraint("uq_skills_user_id_normalized_name", "skills", type_="unique")
    op.create_unique_constraint("skills_normalized_name_key", "skills", ["normalized_name"])

    for table in ("app_settings", "memory_summaries"):
        op.execute(f"ALTER TABLE {table} ALTER COLUMN id DROP DEFAULT")
        op.execute(f"DROP SEQUENCE IF EXISTS {table}_id_seq")
    for table in ("memory_summaries", "app_settings", "skills", "conversations"):
        op.drop_index(f"ix_{table}_user_id", table_name=table)
        op.drop_constraint(f"fk_{table}_user_id", table, type_="foreignkey")
        op.drop_column(table, "user_id")

    op.drop_index("ix_users_is_active", table_name="users")
    op.drop_index("ix_users_role", table_name="users")
    op.drop_index("ix_users_phone", table_name="users")
    op.drop_table("users")
