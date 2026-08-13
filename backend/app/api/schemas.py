from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.config import ThinkingEffort

AgentType = Literal["image", "slides", "research"]


class LoginRequest(BaseModel):
    phone: str = Field(pattern=r"^1[3-9]\d{9}$")
    password: str = Field(min_length=8, max_length=128)


class UserOut(BaseModel):
    id: UUID
    phone: str
    display_name: str
    role: Literal["admin", "member"]
    permissions: list[str]
    is_active: bool
    created_at: datetime

class AdminUserCreate(BaseModel):
    phone: str = Field(pattern=r"^1[3-9]\d{9}$")
    password: str = Field(min_length=8, max_length=128)
    display_name: str = Field(min_length=1, max_length=80)
    role: Literal["admin", "member"] = "member"

class AdminUserPatch(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=80)
    role: Literal["admin", "member"] | None = None
    is_active: bool | None = None
    password: str | None = Field(default=None, min_length=8, max_length=128)


class AuthTokenOut(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int
    user: UserOut


class ChatRequest(BaseModel):
    """Compatibility payload for the stateless M0 streaming endpoint."""

    content: str = Field(min_length=1, max_length=20_000)
    mode: Literal["chat", "work"] = "chat"
    agent_type: AgentType | None = None
    thinking_effort: ThinkingEffort = "medium"

    @model_validator(mode="after")
    def validate_mode(self):
        if self.mode == "chat" and self.agent_type is not None:
            raise ValueError("Chat 模式不能指定 Agent")
        if self.mode == "work" and self.agent_type is None:
            raise ValueError("Work 模式必须指定 Agent")
        return self


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
    service: str
    environment: str
    model_ready: bool
    tavily_ready: bool
    storage_backend: str


class ConversationCreate(BaseModel):
    title: str = Field(default="新会话", min_length=1, max_length=120)
    mode: Literal["chat", "work"] = "chat"


class ConversationPatch(BaseModel):
    title: str = Field(min_length=1, max_length=120)


class ConversationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    mode: Literal["chat", "work"]
    title: str
    title_source: str
    created_at: datetime
    updated_at: datetime
    last_activity_at: datetime
    match_snippet: str | None = None


class MessageRequest(BaseModel):
    content: str = Field(min_length=1, max_length=20_000)
    mode: Literal["chat", "work"] = "chat"
    agent_type: AgentType | None = None
    file_ids: list[UUID] = Field(default_factory=list, max_length=3)
    skill_id: UUID | None = None
    skill_ids: list[UUID] = Field(default_factory=list, max_length=8)
    thinking_effort: ThinkingEffort = "medium"

    @model_validator(mode="after")
    def validate_mode(self):
        if self.mode == "chat" and self.agent_type is not None:
            raise ValueError("Chat 模式不能指定 Agent")
        if self.mode == "work" and self.agent_type is None:
            raise ValueError("Work 模式必须指定 Agent")
        if self.skill_id and self.skill_ids:
            raise ValueError("skill_id 与 skill_ids 不能同时提交")
        if len(set(self.skill_ids)) != len(self.skill_ids):
            raise ValueError("不能重复选择同一个 Skill")
        return self

    @property
    def effective_skill_ids(self) -> list[UUID]:
        return self.skill_ids or ([self.skill_id] if self.skill_id else [])


class MessageRegenerateRequest(BaseModel):
    thinking_effort: ThinkingEffort = "medium"


class MessagePartOut(BaseModel):
    seq: int
    type: str
    content: str
    data: dict[str, Any] = Field(default_factory=dict)


class ToolCallOut(BaseModel):
    id: UUID
    seq: int
    tool_name: str
    input_summary: str
    output_summary: str
    status: str
    duration_ms: int | None


class FileOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    conversation_id: UUID
    name: str
    mime_type: str
    kind: str
    size: int
    status: str
    error: str | None
    created_at: datetime


class SkillSummary(BaseModel):
    id: UUID | None = None
    name: str
    description: str = ""


class MessageOut(BaseModel):
    id: UUID
    conversation_id: UUID
    role: str
    mode: str
    agent_type: str | None
    content: str
    reasoning: str
    follow_up: str | None
    status: str
    error: str | None
    created_at: datetime
    parts: list[MessagePartOut] = Field(default_factory=list)
    tool_calls: list[ToolCallOut] = Field(default_factory=list)
    files: list[FileOut] = Field(default_factory=list)
    skill: SkillSummary | None = None
    skills: list[SkillSummary] = Field(default_factory=list)
    run_id: UUID | None = None


class SkillCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    description: str = Field(default="", max_length=500)
    instructions: str = Field(min_length=1, max_length=20_000)
    enabled: bool = True


class SkillPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    description: str | None = Field(default=None, max_length=500)
    instructions: str | None = Field(default=None, min_length=1, max_length=20_000)
    enabled: bool | None = None


class SkillOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    description: str
    instructions: str
    enabled: bool
    created_at: datetime
    updated_at: datetime


class MemorySummaryUpdate(BaseModel):
    content: str = Field(max_length=4_000)


class MemorySummaryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    content: str
    source: str
    source_conversation_id: UUID | None
    created_at: datetime
    updated_at: datetime


class AppSettingsPatch(BaseModel):
    memory_enabled: bool | None = None
    web_search_enabled: bool | None = None
    appearance: Literal["system", "light", "dark"] | None = None


class AppSettingsOut(BaseModel):
    memory_enabled: bool
    web_search_enabled: bool
    appearance: str
    chat_model: str
    agent_model: str
    model_ready: bool
    tavily_ready: bool
    storage_backend: str


class AgentInfo(BaseModel):
    type: AgentType
    name: str
    description: str
    accepts_images: bool
    output_type: str


class AgentRunRequest(BaseModel):
    conversation_id: UUID
    agent_type: AgentType
    input: str = Field(min_length=1, max_length=20_000)
    file_ids: list[UUID] = Field(default_factory=list, max_length=3)
    skill_id: UUID | None = None
    skill_ids: list[UUID] = Field(default_factory=list, max_length=8)
    intent: Literal["CREATE", "MODIFY", "RESUME"] | None = None
    source_run_id: UUID | None = None
    source_artifact_id: UUID | None = None
    thinking_effort: ThinkingEffort = "medium"

    @model_validator(mode="after")
    def validate_skills(self):
        if self.skill_id and self.skill_ids:
            raise ValueError("skill_id 与 skill_ids 不能同时提交")
        if len(set(self.skill_ids)) != len(self.skill_ids):
            raise ValueError("不能重复选择同一个 Skill")
        return self

    @property
    def effective_skill_ids(self) -> list[UUID]:
        return self.skill_ids or ([self.skill_id] if self.skill_id else [])


class AgentRunCommand(BaseModel):
    action: Literal["confirm", "cancel", "retry"]
    input: str | None = Field(default=None, max_length=20_000)


class ArtifactOut(BaseModel):
    id: UUID
    run_id: UUID
    parent_artifact_id: UUID | None
    version: int
    type: str
    name: str
    mime_type: str
    size: int
    metadata: dict[str, Any] = Field(default_factory=dict)
    download_url: str
    created_at: datetime


class RunEventOut(BaseModel):
    seq: int
    type: str
    payload: dict[str, Any]
    created_at: datetime


class AgentRunOut(BaseModel):
    id: UUID
    conversation_id: UUID
    agent_type: str
    intent: str
    source_run_id: UUID | None
    source_artifact_id: UUID | None
    input: str
    stage: str
    status: str
    answer: str
    public_state: dict[str, Any]
    error: str | None
    events: list[RunEventOut] = Field(default_factory=list)
    artifacts: list[ArtifactOut] = Field(default_factory=list)
    files: list[FileOut] = Field(default_factory=list)
    skill: SkillSummary | None = None
    skills: list[SkillSummary] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime
