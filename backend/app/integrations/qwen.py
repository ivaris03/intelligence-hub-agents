from collections.abc import AsyncIterator

from langchain_core.messages import HumanMessage
from langchain_openai import ChatOpenAI

from app.core.config import Settings


class QwenAdapter:
    """Keeps provider details outside chat and agent orchestration."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def stream_text(self, prompt: str, mode: str = "chat") -> AsyncIterator[tuple[str, str]]:
        if not self.settings.model_ready:
            demo = "这是本地演示回复。配置 DASHSCOPE_API_KEY 后，我会通过百炼模型流式回答。"
            for fragment in demo:
                yield "text", fragment
            return

        model = ChatOpenAI(
            model=(
                self.settings.qwen_agent_model
                if mode == "work"
                else self.settings.qwen_chat_model
            ),
            api_key=self.settings.dashscope_api_key,
            base_url=self.settings.qwen_base_url,
            streaming=True,
        )
        async for chunk in model.astream([HumanMessage(content=prompt)]):
            reasoning = chunk.additional_kwargs.get("reasoning_content")
            if reasoning:
                yield "reasoning", str(reasoning)
            if isinstance(chunk.content, str) and chunk.content:
                yield "text", chunk.content
