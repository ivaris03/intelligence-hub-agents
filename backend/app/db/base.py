from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


def uuid_pk_column():
    return mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("role IN ('admin', 'member')", name="ck_users_role"),
    )

    id: Mapped[UUID] = uuid_pk_column()
    phone: Mapped[str] = mapped_column(String(11), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    display_name: Mapped[str] = mapped_column(String(80))
    role: Mapped[str] = mapped_column(String(20), default="member", index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[UUID] = uuid_pk_column()
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    mode: Mapped[str] = mapped_column(String(20), default="chat", index=True)
    title: Mapped[str] = mapped_column(String(120), default="新会话")
    title_source: Mapped[str] = mapped_column(String(20), default="default")
    last_activity_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    memory_cursor: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    messages: Mapped[list[Message]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan"
    )
    files: Mapped[list[StoredFile]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan"
    )
    runs: Mapped[list[AgentRun]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan"
    )


class Skill(Base):
    __tablename__ = "skills"
    __table_args__ = (UniqueConstraint("user_id", "normalized_name"),)

    id: Mapped[UUID] = uuid_pk_column()
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(80))
    normalized_name: Mapped[str] = mapped_column(String(80), index=True)
    description: Mapped[str] = mapped_column(String(500), default="")
    instructions: Mapped[str] = mapped_column(Text)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class SkillSnapshot(Base):
    __tablename__ = "skill_snapshots"

    id: Mapped[UUID] = uuid_pk_column()
    skill_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("skills.id", ondelete="SET NULL"), index=True
    )
    name: Mapped[str] = mapped_column(String(80))
    description: Mapped[str] = mapped_column(String(500), default="")
    instructions: Mapped[str] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[UUID] = uuid_pk_column()
    conversation_id: Mapped[UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(20))
    mode: Mapped[str] = mapped_column(String(20), default="chat")
    agent_type: Mapped[str | None] = mapped_column(String(20))
    skill_snapshot_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("skill_snapshots.id", ondelete="SET NULL"), index=True
    )
    run_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("agent_runs.id", ondelete="SET NULL", use_alter=True), index=True
    )
    regenerated_from_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("messages.id", ondelete="SET NULL"), index=True
    )
    content: Mapped[str] = mapped_column(Text, default="")
    reasoning: Mapped[str] = mapped_column(Text, default="")
    follow_up: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    error: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    conversation: Mapped[Conversation] = relationship(back_populates="messages")
    skill_snapshot: Mapped[SkillSnapshot | None] = relationship()
    skill_links: Mapped[list[MessageSkill]] = relationship(
        back_populates="message",
        cascade="all, delete-orphan",
        order_by="MessageSkill.position",
    )
    parts: Mapped[list[MessagePart]] = relationship(
        back_populates="message",
        cascade="all, delete-orphan",
        order_by="MessagePart.seq",
    )
    tool_calls: Mapped[list[ToolCall]] = relationship(
        back_populates="message",
        cascade="all, delete-orphan",
        foreign_keys="ToolCall.message_id",
        order_by="ToolCall.seq",
    )
    file_links: Mapped[list[MessageFile]] = relationship(
        back_populates="message", cascade="all, delete-orphan"
    )


class MessagePart(Base):
    __tablename__ = "message_parts"
    __table_args__ = (UniqueConstraint("message_id", "seq"),)

    id: Mapped[UUID] = uuid_pk_column()
    message_id: Mapped[UUID] = mapped_column(
        ForeignKey("messages.id", ondelete="CASCADE"), index=True
    )
    seq: Mapped[int] = mapped_column(Integer)
    type: Mapped[str] = mapped_column(String(40))
    content: Mapped[str] = mapped_column(Text, default="")
    data: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    message: Mapped[Message] = relationship(back_populates="parts")


class ToolCall(Base):
    __tablename__ = "tool_calls"

    id: Mapped[UUID] = uuid_pk_column()
    message_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("messages.id", ondelete="CASCADE"), index=True
    )
    run_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("agent_runs.id", ondelete="CASCADE"), index=True
    )
    seq: Mapped[int] = mapped_column(Integer, default=0)
    tool_name: Mapped[str] = mapped_column(String(100))
    input_summary: Mapped[str] = mapped_column(Text, default="")
    output_summary: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(20), default="preparing")
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    message: Mapped[Message | None] = relationship(
        back_populates="tool_calls", foreign_keys=[message_id]
    )


class AppSettings(Base):
    __tablename__ = "app_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), unique=True, index=True
    )
    memory_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    web_search_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    appearance: Mapped[str] = mapped_column(String(20), default="system")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class MemorySummary(Base):
    __tablename__ = "memory_summaries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), unique=True, index=True
    )
    content: Mapped[str] = mapped_column(Text, default="")
    source: Mapped[str] = mapped_column(String(20), default="manual")
    source_conversation_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("conversations.id", ondelete="SET NULL"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class MemoryChatMessage(Base):
    __tablename__ = "memory_chat_messages"

    id: Mapped[UUID] = uuid_pk_column()
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(20))
    content: Mapped[str] = mapped_column(Text)
    memory_changed: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )


class PendingMemoryConversation(Base):
    __tablename__ = "pending_memory_conversations"

    conversation_id: Mapped[UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    through_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    process_after: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    queued_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class StoredFile(Base):
    __tablename__ = "files"

    id: Mapped[UUID] = uuid_pk_column()
    conversation_id: Mapped[UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(255))
    mime_type: Mapped[str] = mapped_column(String(100))
    kind: Mapped[str] = mapped_column(String(20))
    size: Mapped[int] = mapped_column(BigInteger)
    storage_key: Mapped[str] = mapped_column(String(500), unique=True)
    status: Mapped[str] = mapped_column(String(20), default="processing")
    error: Mapped[str | None] = mapped_column(String(500))
    text_content: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )

    conversation: Mapped[Conversation] = relationship(back_populates="files")
    chunks: Mapped[list[FileChunk]] = relationship(
        back_populates="file", cascade="all, delete-orphan"
    )


class FileChunk(Base):
    __tablename__ = "file_chunks"
    __table_args__ = (UniqueConstraint("file_id", "chunk_index"),)

    id: Mapped[UUID] = uuid_pk_column()
    file_id: Mapped[UUID] = mapped_column(ForeignKey("files.id", ondelete="CASCADE"), index=True)
    chunk_index: Mapped[int] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(Text)
    locator: Mapped[str] = mapped_column(String(255))
    embedding: Mapped[list[float] | None] = mapped_column(
        Vector(1024).with_variant(JSON(), "sqlite")
    )

    file: Mapped[StoredFile] = relationship(back_populates="chunks")


class MessageFile(Base):
    __tablename__ = "message_files"

    message_id: Mapped[UUID] = mapped_column(
        ForeignKey("messages.id", ondelete="CASCADE"), primary_key=True
    )
    file_id: Mapped[UUID] = mapped_column(
        ForeignKey("files.id", ondelete="CASCADE"), primary_key=True
    )
    purpose: Mapped[str] = mapped_column(String(30), default="context")

    message: Mapped[Message] = relationship(back_populates="file_links")
    file: Mapped[StoredFile] = relationship()


class MessageSkill(Base):
    __tablename__ = "message_skills"
    __table_args__ = (UniqueConstraint("message_id", "position"),)

    message_id: Mapped[UUID] = mapped_column(
        ForeignKey("messages.id", ondelete="CASCADE"), primary_key=True
    )
    skill_snapshot_id: Mapped[UUID] = mapped_column(
        ForeignKey("skill_snapshots.id", ondelete="CASCADE"), primary_key=True
    )
    position: Mapped[int] = mapped_column(Integer)

    message: Mapped[Message] = relationship(back_populates="skill_links")
    skill_snapshot: Mapped[SkillSnapshot] = relationship()


class AgentRun(Base):
    __tablename__ = "agent_runs"

    id: Mapped[UUID] = uuid_pk_column()
    conversation_id: Mapped[UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    agent_type: Mapped[str] = mapped_column(String(20), index=True)
    intent: Mapped[str] = mapped_column(String(20), default="CREATE")
    source_run_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("agent_runs.id", ondelete="SET NULL"), index=True
    )
    source_artifact_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("artifacts.id", ondelete="SET NULL", use_alter=True), index=True
    )
    skill_snapshot_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("skill_snapshots.id", ondelete="SET NULL"), index=True
    )
    input: Mapped[str] = mapped_column(Text)
    stage: Mapped[str] = mapped_column(String(50), default="queued")
    status: Mapped[str] = mapped_column(String(30), default="queued", index=True)
    answer: Mapped[str] = mapped_column(Text, default="")
    public_state: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    error: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    conversation: Mapped[Conversation] = relationship(back_populates="runs")
    skill_snapshot: Mapped[SkillSnapshot | None] = relationship()
    file_links: Mapped[list[RunFile]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )
    events: Mapped[list[RunEvent]] = relationship(
        back_populates="run", cascade="all, delete-orphan", order_by="RunEvent.seq"
    )
    artifacts: Mapped[list[Artifact]] = relationship(
        back_populates="run",
        cascade="all, delete-orphan",
        foreign_keys="Artifact.run_id",
    )


class RunFile(Base):
    __tablename__ = "run_files"

    run_id: Mapped[UUID] = mapped_column(
        ForeignKey("agent_runs.id", ondelete="CASCADE"), primary_key=True
    )
    file_id: Mapped[UUID] = mapped_column(
        ForeignKey("files.id", ondelete="CASCADE"), primary_key=True
    )
    purpose: Mapped[str] = mapped_column(String(30), default="input")

    run: Mapped[AgentRun] = relationship(back_populates="file_links")
    file: Mapped[StoredFile] = relationship()


class RunEvent(Base):
    __tablename__ = "run_events"
    __table_args__ = (UniqueConstraint("run_id", "seq"),)

    id: Mapped[UUID] = uuid_pk_column()
    run_id: Mapped[UUID] = mapped_column(
        ForeignKey("agent_runs.id", ondelete="CASCADE"), index=True
    )
    seq: Mapped[int] = mapped_column(Integer)
    type: Mapped[str] = mapped_column(String(50))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    run: Mapped[AgentRun] = relationship(back_populates="events")


class RunCheckpoint(Base):
    __tablename__ = "run_checkpoints"
    __table_args__ = (UniqueConstraint("run_id", "checkpoint_id"),)

    id: Mapped[UUID] = uuid_pk_column()
    run_id: Mapped[UUID] = mapped_column(
        ForeignKey("agent_runs.id", ondelete="CASCADE"), index=True
    )
    stage: Mapped[str] = mapped_column(String(50))
    checkpoint_id: Mapped[str] = mapped_column(String(100))
    input_hash: Mapped[str] = mapped_column(String(64), index=True)
    state: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )


class Artifact(Base):
    __tablename__ = "artifacts"
    __table_args__ = (UniqueConstraint("run_id", "type", "version"),)

    id: Mapped[UUID] = uuid_pk_column()
    run_id: Mapped[UUID] = mapped_column(
        ForeignKey("agent_runs.id", ondelete="CASCADE"), index=True
    )
    parent_artifact_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("artifacts.id", ondelete="SET NULL"), index=True
    )
    version: Mapped[int] = mapped_column(Integer, default=1)
    type: Mapped[str] = mapped_column(String(20))
    name: Mapped[str] = mapped_column(String(255))
    storage_key: Mapped[str] = mapped_column(String(500), unique=True)
    mime_type: Mapped[str] = mapped_column(String(100))
    size: Mapped[int] = mapped_column(BigInteger)
    artifact_metadata: Mapped[dict[str, Any]] = mapped_column("metadata", JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )

    run: Mapped[AgentRun] = relationship(back_populates="artifacts", foreign_keys=[run_id])
    parent: Mapped[Artifact | None] = relationship(remote_side=[id])
