import asyncio
import json
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from app.api.schemas import ChatRequest, HealthResponse
from app.core.config import Settings, get_settings
from app.integrations.qwen import QwenAdapter

router = APIRouter()
SettingsDep = Annotated[Settings, Depends(get_settings)]


def encode_event(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@router.get("/health", response_model=HealthResponse)
async def health(settings: SettingsDep) -> HealthResponse:
    return HealthResponse(
        service=settings.app_name,
        environment=settings.app_env,
        model_ready=settings.model_ready,
    )


@router.post("/chat/stream")
async def chat_stream(
    payload: ChatRequest, settings: SettingsDep
) -> StreamingResponse:
    async def events() -> AsyncIterator[str]:
        seq = 0
        adapter = QwenAdapter(settings)
        try:
            async for kind, delta in adapter.stream_text(payload.content, payload.mode):
                seq += 1
                event = "reasoning.delta" if kind == "reasoning" else "message.delta"
                yield encode_event(event, {"seq": seq, "delta": delta})
                if not settings.model_ready:
                    await asyncio.sleep(0.012)
            seq += 1
            yield encode_event("completed", {"seq": seq})
        except asyncio.CancelledError:
            raise
        except Exception:
            seq += 1
            yield encode_event(
                "failed", {"seq": seq, "message": "模型服务暂时不可用，请稍后重试。"}
            )

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
