from typing import Literal

from pydantic import BaseModel, Field, model_validator


class ChatRequest(BaseModel):
    content: str = Field(min_length=1, max_length=20_000)
    mode: Literal["chat", "work"] = "chat"
    agent_type: Literal["image", "slides", "research"] | None = None

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

