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
    qwen_image_endpoint: str = (
        "https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation"
    )
    qwen_embedding_dimensions: int = 1024
    qwen_thinking_budget: int = 1024

    langsmith_tracing: bool = False
    langsmith_api_key: str | None = Field(default=None, repr=False)
    langsmith_project: str = "intelligence-hub"
    langsmith_endpoint: str = "https://api.smith.langchain.com"

    tavily_mcp_url: str = "https://mcp.tavily.com/mcp/"
    tavily_api_key: str | None = Field(default=None, repr=False)
    storage_backend: str = "local"
    storage_path: Path = Path("./storage")
    minio_endpoint: str = "localhost:9000"
    minio_access_key: str = Field(default="minioadmin", repr=False)
    minio_secret_key: str = Field(default="minioadmin", repr=False)
    minio_bucket: str = "intelligence-hub"
    minio_secure: bool = False

    max_upload_bytes: int = 20 * 1024 * 1024
    max_files_per_request: int = 3
    max_image_pixels: int = 24_000_000
    document_inline_chars: int = 12_000
    document_chunk_chars: int = 1_200
    document_chunk_overlap: int = 150
    recent_message_limit: int = 12
    memory_max_items: int = 5
    memory_context_chars: int = 1_500
    research_max_searches: int = 4
    research_timeout_seconds: int = 120
    slides_max_pages: int = 15

    @property
    def model_ready(self) -> bool:
        return bool(self.dashscope_api_key)

    @property
    def langsmith_ready(self) -> bool:
        return self.langsmith_tracing and bool(self.langsmith_api_key)

    @property
    def tavily_ready(self) -> bool:
        return bool(self.tavily_api_key)

    @property
    def langgraph_database_url(self) -> str:
        """Return a psycopg-compatible URL for LangGraph's Postgres checkpointer."""
        return self.database_url.replace("postgresql+asyncpg://", "postgresql://", 1)


@lru_cache
def get_settings() -> Settings:
    return Settings()
