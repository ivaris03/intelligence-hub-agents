from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=("../.env", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "Intelligence Hub API"
    app_env: str = "development"
    app_host: str = "127.0.0.1"
    app_port: int = 8000
    api_prefix: str = "/api"
    web_origin: str = "http://localhost:5173"

    database_url: str = (
        "postgresql+asyncpg://postgres:postgres@localhost:5432/intelligence_hub_agents"
    )

    dashscope_api_key: str | None = Field(default=None, repr=False)
    qwen_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    qwen_chat_model: str = "qwen3.7-flash"
    qwen_agent_model: str = "qwen3.7-plus"
    qwen_vision_model: str = "qwen-vl-plus"
    qwen_embedding_model: str = "qwen3.7-text-embedding"
    qwen_image_model: str = "qwen-image-3.0"

    langsmith_tracing: bool = False
    langsmith_api_key: str | None = Field(default=None, repr=False)
    langsmith_project: str = "intelligence-hub"
    langsmith_endpoint: str = "https://api.smith.langchain.com"

    tavily_mcp_url: str = "https://mcp.tavily.com/mcp/"
    tavily_api_key: str | None = Field(default=None, repr=False)
    storage_backend: str = "local"
    storage_path: Path = Path("./storage")

    @property
    def model_ready(self) -> bool:
        return bool(self.dashscope_api_key)

    @property
    def langsmith_ready(self) -> bool:
        return self.langsmith_tracing and bool(self.langsmith_api_key)


@lru_cache
def get_settings() -> Settings:
    return Settings()
