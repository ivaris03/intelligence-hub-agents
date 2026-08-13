from __future__ import annotations

import json
from collections.abc import AsyncIterator
from io import BytesIO
from typing import Any

import httpx
from langchain_core.messages import HumanMessage
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from PIL import Image, ImageDraw

from app.core.config import Settings, ThinkingEffort
from app.observability.langsmith import finish_trace, trace_operation


class QwenAdapter:
    """Keeps all Alibaba Cloud provider details behind one server-side boundary."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def chat_model(self, *, work: bool = False, vision: bool = False) -> ChatOpenAI:
        if not self.settings.dashscope_api_key:
            raise RuntimeError("模型服务未配置")
        model = (
            self.settings.qwen_vision_model
            if vision
            else self.settings.qwen_agent_model
            if work
            else self.settings.qwen_chat_model
        )
        return ChatOpenAI(
            model=model,
            api_key=self.settings.dashscope_api_key,
            base_url=self.settings.qwen_base_url,
            streaming=True,
            timeout=120,
            max_retries=2,
            **({"extra_body": self.thinking_parameters()} if not vision else {}),
        )

    async def stream_text(
        self,
        prompt: str,
        mode: str = "chat",
        *,
        thinking_effort: ThinkingEffort = "medium",
    ) -> AsyncIterator[tuple[str, str]]:
        adapter = QwenAdapter(self.settings.with_thinking_effort(thinking_effort))
        async for item in adapter.stream_chat(
            [{"role": "user", "content": prompt}], work=mode == "work"
        ):
            yield item

    def thinking_parameters(self) -> dict[str, bool | int]:
        return {
            "enable_thinking": True,
            "thinking_budget": self.settings.effective_qwen_thinking_budget,
        }

    async def stream_chat(
        self,
        messages: list[dict[str, str]],
        *,
        system_context: str = "",
        images: list[dict[str, str]] | None = None,
        work: bool = False,
    ) -> AsyncIterator[tuple[str, str]]:
        images = images or []
        model = (
            self.settings.qwen_vision_model
            if images
            else self.settings.qwen_agent_model
            if work
            else self.settings.qwen_chat_model
        )
        with trace_operation(
            self.settings,
            "qwen.chat.completions.stream",
            inputs={
                "messages": [
                    *(
                        [{"role": "system", "content": system_context[:30_000]}]
                        if system_context
                        else []
                    ),
                    *messages,
                ],
                "images": [
                    {"file_id": item.get("file_id"), "name": item.get("name")} for item in images
                ],
            },
            run_type="llm",
            tags=["qwen", "streaming"],
            metadata={
                "ls_provider": "alibaba_dashscope",
                "ls_model_name": model,
                "ls_model_type": "chat",
                "work": work,
                "vision": bool(images),
            },
        ) as trace:
            answer = ""
            reasoning = ""
            async for kind, delta in self._stream_chat(
                messages,
                system_context=system_context,
                images=images,
                work=work,
            ):
                if kind == "reasoning":
                    reasoning += delta
                else:
                    answer += delta
                yield kind, delta
            finish_trace(
                trace,
                {
                    "choices": [{"message": {"role": "assistant", "content": answer}}],
                    "reasoning": reasoning,
                },
            )

    async def _stream_chat(
        self,
        messages: list[dict[str, str]],
        *,
        system_context: str = "",
        images: list[dict[str, str]] | None = None,
        work: bool = False,
    ) -> AsyncIterator[tuple[str, str]]:
        images = images or []
        if not self.settings.model_ready:
            latest = messages[-1]["content"] if messages else ""
            demo = (
                "这是本地演示回复。"
                f"我已收到：{latest[:160]}"
                "\n\n配置 `DASHSCOPE_API_KEY` 后，将由百炼 Qwen 根据完整多轮上下文回答。"
            )
            if system_context:
                demo += "\n\n本轮已应用所选的文件、Skill 或 Memory 上下文。"
            if images:
                demo += f"\n\n本轮关联了 {len(images)} 张已校验图片。"
            for fragment in demo:
                yield "text", fragment
            return

        provider_messages: list[dict[str, Any]] = []
        if system_context:
            provider_messages.append({"role": "system", "content": system_context})
        for index, item in enumerate(messages):
            role = item["role"]
            content: str | list[dict[str, Any]] = item["content"]
            if role == "user" and index == len(messages) - 1 and images:
                content = [{"type": "text", "text": item["content"]}]
                content.extend(
                    {
                        "type": "image_url",
                        "image_url": {"url": image["data_url"]},
                    }
                    for image in images
                )
            provider_messages.append({"role": role, "content": content})

        model = (
            self.settings.qwen_vision_model
            if images
            else self.settings.qwen_agent_model
            if work
            else self.settings.qwen_chat_model
        )
        payload: dict[str, Any] = {
            "model": model,
            "messages": provider_messages,
            "stream": True,
        }
        # The OpenAI-compatible response includes `reasoning_content`, but the
        # LangChain adapter currently drops that non-standard streaming field.
        # Parse provider SSE directly so the UI can render reasoning separately.
        if not images:
            payload.update(self.thinking_parameters())
        headers = {"Authorization": f"Bearer {self.settings.dashscope_api_key}"}
        timeout = httpx.Timeout(120, connect=15)
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            async with client.stream(
                "POST",
                f"{self.settings.qwen_base_url.rstrip('/')}/chat/completions",
                headers=headers,
                json=payload,
            ) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line.startswith("data: ") or line == "data: [DONE]":
                        continue
                    event = json.loads(line[6:])
                    for part in self._stream_delta_parts(event):
                        yield part

    @staticmethod
    def _stream_delta_parts(event: dict[str, Any]) -> list[tuple[str, str]]:
        choices = event.get("choices") or []
        if not choices:
            return []
        delta = choices[0].get("delta") or {}
        parts: list[tuple[str, str]] = []
        reasoning = delta.get("reasoning_content")
        if reasoning:
            parts.append(("reasoning", str(reasoning)))
        content = delta.get("content")
        if isinstance(content, str) and content:
            parts.append(("text", content))
        elif isinstance(content, list):
            parts.extend(
                ("text", str(block.get("text", "")))
                for block in content
                if isinstance(block, dict) and block.get("type") == "text" and block.get("text")
            )
        return parts

    async def complete_text(
        self,
        prompt: str,
        *,
        fallback: str,
        work: bool = False,
        max_chars: int = 500,
    ) -> str:
        if not self.settings.model_ready:
            return fallback[:max_chars]
        model = self.chat_model(work=work)
        response = await model.ainvoke([HumanMessage(content=prompt)])
        content = response.content if isinstance(response.content, str) else ""
        return (content.strip() or fallback)[:max_chars]

    async def embed_documents(self, texts: list[str]) -> list[list[float] | None]:
        if not texts:
            return []
        if not self.settings.model_ready:
            return [None] * len(texts)
        embeddings = OpenAIEmbeddings(
            model=self.settings.qwen_embedding_model,
            api_key=self.settings.dashscope_api_key,
            base_url=self.settings.qwen_base_url,
            dimensions=self.settings.qwen_embedding_dimensions,
            # DashScope's OpenAI-compatible endpoint expects the original
            # strings.  LangChain otherwise tokenizes long inputs locally and
            # sends integer arrays, which DashScope rejects.
            check_embedding_ctx_length=False,
            timeout=60,
            max_retries=2,
        )
        values = await embeddings.aembed_documents(texts)
        vectors = [list(value) for value in values]
        if any(len(vector) != self.settings.qwen_embedding_dimensions for vector in vectors):
            raise RuntimeError("Embedding 服务返回了不兼容的向量维度")
        return vectors

    async def generate_image(self, prompt: str, reference_images: list[str] | None = None) -> bytes:
        references = reference_images or []
        with trace_operation(
            self.settings,
            "qwen.image.generate",
            inputs={"prompt": prompt, "reference_count": len(references)},
            run_type="tool",
            tags=["qwen", "image-generation"],
            metadata={
                "ls_provider": "alibaba_dashscope",
                "ls_model_name": self.settings.qwen_image_model,
            },
        ) as trace:
            data = await self._generate_image(prompt, references)
            finish_trace(trace, {"format": "png", "size_bytes": len(data)})
            return data

    async def _generate_image(self, prompt: str, references: list[str]) -> bytes:
        if not self.settings.model_ready:
            return self._demo_image()
        content: list[dict[str, str]] = [{"image": image} for image in references[:3]]
        content.append({"text": prompt})
        payload = {
            "model": self.settings.qwen_image_model,
            "input": {"messages": [{"role": "user", "content": content}]},
            "parameters": {"prompt_extend": True, "n": 1, "watermark": False},
        }
        headers = {"Authorization": f"Bearer {self.settings.dashscope_api_key}"}
        async with httpx.AsyncClient(timeout=180, follow_redirects=True) as client:
            response = await client.post(
                self.settings.qwen_image_endpoint, json=payload, headers=headers
            )
            response.raise_for_status()
            body = response.json()
            choices = body.get("output", {}).get("choices", [])
            if not choices:
                raise RuntimeError("图片模型未返回结果")
            blocks = choices[0].get("message", {}).get("content", [])
            url = next((block.get("image") for block in blocks if block.get("image")), None)
            if not url:
                raise RuntimeError("图片模型未返回下载地址")
            image_response = await client.get(url)
            image_response.raise_for_status()
            if len(image_response.content) > self.settings.max_upload_bytes:
                raise RuntimeError("图片模型返回文件过大")
            return image_response.content

    @staticmethod
    def _demo_image() -> bytes:
        image = Image.new("RGB", (1280, 768), "#e4eee9")
        draw = ImageDraw.Draw(image)
        for y in range(image.height):
            ratio = y / image.height
            color = (
                int(226 - ratio * 28),
                int(239 - ratio * 20),
                int(234 - ratio * 6),
            )
            draw.line((0, y, image.width, y), fill=color)
        draw.ellipse((845, 90, 1170, 415), fill="#d9b56f")
        draw.rounded_rectangle((110, 120, 820, 650), radius=48, fill="#fbfaf7")
        draw.text((175, 250), "INTELLIGENCE HUB", fill="#275f54")
        draw.text((175, 300), "LOCAL IMAGE AGENT PREVIEW", fill="#25241f")
        draw.text((175, 350), "Configure DASHSCOPE_API_KEY for Qwen Image", fill="#77736a")
        output = BytesIO()
        image.save(output, format="PNG")
        return output.getvalue()
