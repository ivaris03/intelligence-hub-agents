"""Add the complete Intelligence Hub MVP domain model."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision: str = "20260813_0002"
down_revision: str | None = "20260813_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = postgresql.UUID(as_uuid=True)


def timestamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    ]


def upgrade() -> None:
    op.add_column(
        "conversations",
        sa.Column("last_activity_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.add_column(
        "conversations", sa.Column("memory_cursor", sa.DateTime(timezone=True), nullable=True)
    )
    op.create_index("ix_conversations_last_activity_at", "conversations", ["last_activity_at"])

    op.create_table(
        "skills",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("normalized_name", sa.String(80), nullable=False, unique=True),
        sa.Column("description", sa.String(500), nullable=False, server_default=""),
        sa.Column("instructions", sa.Text(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        *timestamps(),
    )
    op.create_index("ix_skills_normalized_name", "skills", ["normalized_name"])
    op.create_table(
        "skill_snapshots",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("skill_id", UUID, nullable=True),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("description", sa.String(500), nullable=False, server_default=""),
        sa.Column("instructions", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["skill_id"], ["skills.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_skill_snapshots_skill_id", "skill_snapshots", ["skill_id"])
    op.create_index("ix_skill_snapshots_content_hash", "skill_snapshots", ["content_hash"])

    op.create_table(
        "app_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("memory_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("web_search_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("appearance", sa.String(20), nullable=False, server_default="system"),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.execute(
        "INSERT INTO app_settings (id, memory_enabled, web_search_enabled, appearance) "
        "VALUES (1, TRUE, TRUE, 'system') ON CONFLICT (id) DO NOTHING"
    )
    op.create_table(
        "memory_summaries",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("content", sa.Text(), nullable=False, server_default=""),
        sa.Column("source", sa.String(20), nullable=False, server_default="manual"),
        sa.Column("source_conversation_id", UUID, nullable=True),
        *timestamps(),
        sa.ForeignKeyConstraint(
            ["source_conversation_id"], ["conversations.id"], ondelete="SET NULL"
        ),
        sa.CheckConstraint("id = 1", name="ck_memory_summaries_singleton"),
    )
    op.execute(
        "INSERT INTO memory_summaries (id, content, source) VALUES (1, '', 'manual')"
    )
    op.create_index(
        "ix_memory_summaries_source_conversation_id",
        "memory_summaries",
        ["source_conversation_id"],
    )

    op.create_table(
        "files",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("conversation_id", UUID, nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("mime_type", sa.String(100), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("size", sa.BigInteger(), nullable=False),
        sa.Column("storage_key", sa.String(500), nullable=False, unique=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="processing"),
        sa.Column("error", sa.String(500), nullable=True),
        sa.Column("text_content", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_files_conversation_id", "files", ["conversation_id"])
    op.create_index("ix_files_created_at", "files", ["created_at"])
    op.create_table(
        "file_chunks",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("file_id", UUID, nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("locator", sa.String(255), nullable=False),
        sa.Column("embedding", Vector(1024), nullable=True),
        sa.ForeignKeyConstraint(["file_id"], ["files.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("file_id", "chunk_index"),
    )
    op.create_index("ix_file_chunks_file_id", "file_chunks", ["file_id"])

    op.create_table(
        "agent_runs",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("conversation_id", UUID, nullable=False),
        sa.Column("agent_type", sa.String(20), nullable=False),
        sa.Column("intent", sa.String(20), nullable=False, server_default="CREATE"),
        sa.Column("source_run_id", UUID, nullable=True),
        sa.Column("source_artifact_id", UUID, nullable=True),
        sa.Column("skill_snapshot_id", UUID, nullable=True),
        sa.Column("input", sa.Text(), nullable=False),
        sa.Column("stage", sa.String(50), nullable=False, server_default="queued"),
        sa.Column("status", sa.String(30), nullable=False, server_default="queued"),
        sa.Column("answer", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "public_state",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="{}",
        ),
        sa.Column("error", sa.String(500), nullable=True),
        *timestamps(),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_run_id"], ["agent_runs.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["skill_snapshot_id"], ["skill_snapshots.id"], ondelete="SET NULL"),
    )
    for column in (
        "conversation_id",
        "agent_type",
        "source_run_id",
        "skill_snapshot_id",
        "status",
        "created_at",
    ):
        op.create_index(f"ix_agent_runs_{column}", "agent_runs", [column])

    op.add_column("messages", sa.Column("agent_type", sa.String(20), nullable=True))
    op.add_column("messages", sa.Column("skill_snapshot_id", UUID, nullable=True))
    op.add_column("messages", sa.Column("run_id", UUID, nullable=True))
    op.add_column("messages", sa.Column("regenerated_from_id", UUID, nullable=True))
    op.add_column("messages", sa.Column("reasoning", sa.Text(), nullable=False, server_default=""))
    op.add_column("messages", sa.Column("follow_up", sa.Text(), nullable=True))
    op.add_column("messages", sa.Column("error", sa.String(500), nullable=True))
    op.add_column(
        "messages",
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_foreign_key(
        "fk_messages_skill_snapshot",
        "messages",
        "skill_snapshots",
        ["skill_snapshot_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_messages_run", "messages", "agent_runs", ["run_id"], ["id"], ondelete="SET NULL"
    )
    op.create_foreign_key(
        "fk_messages_regenerated_from",
        "messages",
        "messages",
        ["regenerated_from_id"],
        ["id"],
        ondelete="SET NULL",
    )
    for column in ("skill_snapshot_id", "run_id", "regenerated_from_id", "created_at"):
        op.create_index(f"ix_messages_{column}", "messages", [column])

    op.create_table(
        "message_parts",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("message_id", UUID, nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("type", sa.String(40), nullable=False),
        sa.Column("content", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "data", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="{}"
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["message_id"], ["messages.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("message_id", "seq"),
    )
    op.create_index("ix_message_parts_message_id", "message_parts", ["message_id"])
    op.create_table(
        "tool_calls",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("message_id", UUID, nullable=True),
        sa.Column("run_id", UUID, nullable=True),
        sa.Column("seq", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tool_name", sa.String(100), nullable=False),
        sa.Column("input_summary", sa.Text(), nullable=False, server_default=""),
        sa.Column("output_summary", sa.Text(), nullable=False, server_default=""),
        sa.Column("status", sa.String(20), nullable=False, server_default="preparing"),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["message_id"], ["messages.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["run_id"], ["agent_runs.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_tool_calls_message_id", "tool_calls", ["message_id"])
    op.create_index("ix_tool_calls_run_id", "tool_calls", ["run_id"])
    op.create_table(
        "message_files",
        sa.Column("message_id", UUID, primary_key=True),
        sa.Column("file_id", UUID, primary_key=True),
        sa.Column("purpose", sa.String(30), nullable=False, server_default="context"),
        sa.ForeignKeyConstraint(["message_id"], ["messages.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["file_id"], ["files.id"], ondelete="CASCADE"),
    )
    op.create_table(
        "run_files",
        sa.Column("run_id", UUID, primary_key=True),
        sa.Column("file_id", UUID, primary_key=True),
        sa.Column("purpose", sa.String(30), nullable=False, server_default="input"),
        sa.ForeignKeyConstraint(["run_id"], ["agent_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["file_id"], ["files.id"], ondelete="CASCADE"),
    )
    op.create_table(
        "run_events",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("run_id", UUID, nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("type", sa.String(50), nullable=False),
        sa.Column(
            "payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="{}"
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["run_id"], ["agent_runs.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("run_id", "seq"),
    )
    op.create_index("ix_run_events_run_id", "run_events", ["run_id"])
    op.create_table(
        "run_checkpoints",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("run_id", UUID, nullable=False),
        sa.Column("stage", sa.String(50), nullable=False),
        sa.Column("checkpoint_id", sa.String(100), nullable=False),
        sa.Column("input_hash", sa.String(64), nullable=False),
        sa.Column(
            "state", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="{}"
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["run_id"], ["agent_runs.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("run_id", "checkpoint_id"),
    )
    op.create_index("ix_run_checkpoints_run_id", "run_checkpoints", ["run_id"])
    op.create_index("ix_run_checkpoints_input_hash", "run_checkpoints", ["input_hash"])
    op.create_index("ix_run_checkpoints_created_at", "run_checkpoints", ["created_at"])

    op.create_table(
        "artifacts",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("run_id", UUID, nullable=False),
        sa.Column("parent_artifact_id", UUID, nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("type", sa.String(20), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("storage_key", sa.String(500), nullable=False, unique=True),
        sa.Column("mime_type", sa.String(100), nullable=False),
        sa.Column("size", sa.BigInteger(), nullable=False),
        sa.Column(
            "metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="{}"
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["run_id"], ["agent_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["parent_artifact_id"], ["artifacts.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("run_id", "type", "version"),
    )
    op.create_index("ix_artifacts_run_id", "artifacts", ["run_id"])
    op.create_index("ix_artifacts_parent_artifact_id", "artifacts", ["parent_artifact_id"])
    op.create_index("ix_artifacts_created_at", "artifacts", ["created_at"])
    op.create_foreign_key(
        "fk_agent_runs_source_artifact",
        "agent_runs",
        "artifacts",
        ["source_artifact_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_agent_runs_source_artifact_id", "agent_runs", ["source_artifact_id"])


def downgrade() -> None:
    op.drop_index("ix_agent_runs_source_artifact_id", table_name="agent_runs")
    op.drop_constraint("fk_agent_runs_source_artifact", "agent_runs", type_="foreignkey")
    op.drop_table("artifacts")
    op.drop_table("run_checkpoints")
    op.drop_table("run_events")
    op.drop_table("run_files")
    op.drop_table("message_files")
    op.drop_table("tool_calls")
    op.drop_table("message_parts")
    for column in ("regenerated_from_id", "run_id", "skill_snapshot_id"):
        op.drop_index(f"ix_messages_{column}", table_name="messages")
    op.drop_index("ix_messages_created_at", table_name="messages")
    op.drop_constraint("fk_messages_regenerated_from", "messages", type_="foreignkey")
    op.drop_constraint("fk_messages_run", "messages", type_="foreignkey")
    op.drop_constraint("fk_messages_skill_snapshot", "messages", type_="foreignkey")
    for column in (
        "updated_at",
        "error",
        "follow_up",
        "reasoning",
        "regenerated_from_id",
        "run_id",
        "skill_snapshot_id",
        "agent_type",
    ):
        op.drop_column("messages", column)
    op.drop_table("agent_runs")
    op.drop_table("file_chunks")
    op.drop_table("files")
    op.drop_table("memory_summaries")
    op.drop_table("app_settings")
    op.drop_table("skill_snapshots")
    op.drop_table("skills")
    op.drop_index("ix_conversations_last_activity_at", table_name="conversations")
    op.drop_column("conversations", "memory_cursor")
    op.drop_column("conversations", "last_activity_at")
