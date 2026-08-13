from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from io import BytesIO
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    UploadFile,
    status,
)
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.agents.service import cancel_run, create_run, load_run, stream_run
from app.api.schemas import (
    AgentInfo,
    AgentRunCommand,
    AgentRunOut,
    AgentRunRequest,
    AppSettingsOut,
    AppSettingsPatch,
    ChatRequest,
    ConversationCreate,
    ConversationOut,
    ConversationPatch,
    FileOut,
    HealthResponse,
    MemorySummaryOut,
    MemorySummaryUpdate,
    MessageOut,
    MessageRequest,
    SkillCreate,
    SkillOut,
    SkillPatch,
)
from app.artifacts.service import artifact_payload
from app.chat.service import (
    cancel_message,
    prepare_message,
    prepare_regeneration,
    stream_prepared_message,
)
from app.core.config import Settings, get_settings
from app.core.security import contains_sensitive_memory
from app.db.base import (
    AgentRun,
    Artifact,
    Conversation,
    MemorySummary,
    Message,
    MessageFile,
    Skill,
    StoredFile,
)
from app.db.session import get_session
from app.files.service import FileValidationError, create_file
from app.files.storage import get_storage
from app.integrations.qwen import QwenAdapter
from app.memory.service import (
    get_app_settings,
    get_memory_summary_record,
    refine_idle_memory_summary,
)
from app.skills.service import normalize_skill_name

router = APIRouter()
SettingsDep = Annotated[Settings, Depends(get_settings)]
SessionDep = Annotated[AsyncSession, Depends(get_session)]


def encode_event(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"


async def sse_events(iterator) -> AsyncIterator[str]:
    async for event_type, payload in iterator:
        yield encode_event(event_type, payload)


def sse_response(iterator) -> StreamingResponse:
    return StreamingResponse(
        sse_events(iterator),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@router.get("/health", response_model=HealthResponse)
async def health(settings: SettingsDep) -> HealthResponse:
    return HealthResponse(
        service=settings.app_name,
        environment=settings.app_env,
        model_ready=settings.model_ready,
        tavily_ready=settings.tavily_ready,
        storage_backend=settings.storage_backend,
    )


@router.post("/chat/stream")
async def chat_stream(payload: ChatRequest, settings: SettingsDep) -> StreamingResponse:
    """Backward-compatible stateless stream; persistent Chat uses conversation messages."""

    async def events() -> AsyncIterator[str]:
        seq = 0
        try:
            async for kind, delta in QwenAdapter(settings).stream_text(
                payload.content, payload.mode
            ):
                seq += 1
                event = "reasoning.delta" if kind == "reasoning" else "message.delta"
                yield encode_event(event, {"seq": seq, "delta": delta})
                if not settings.model_ready:
                    await asyncio.sleep(0.004)
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


def _conversation_out(
    conversation: Conversation, match_snippet: str | None = None
) -> ConversationOut:
    return ConversationOut(
        id=conversation.id,
        mode=conversation.mode,
        title=conversation.title,
        title_source=conversation.title_source,
        created_at=conversation.created_at,
        updated_at=conversation.updated_at,
        last_activity_at=conversation.last_activity_at,
        match_snippet=match_snippet,
    )


def _snippet(text: str, keyword: str, radius: int = 42) -> str:
    lower = text.casefold()
    index = lower.find(keyword.casefold())
    if index < 0:
        return text[: radius * 2]
    start = max(0, index - radius)
    end = min(len(text), index + len(keyword) + radius)
    return ("…" if start else "") + text[start:end] + ("…" if end < len(text) else "")


@router.get("/conversations", response_model=list[ConversationOut])
async def list_conversations(
    session: SessionDep,
    q: Annotated[str | None, Query(max_length=120)] = None,
    mode: Annotated[Literal["chat", "work"] | None, Query()] = None,
) -> list[ConversationOut]:
    query = select(Conversation).order_by(Conversation.updated_at.desc())
    if mode is not None:
        query = query.where(Conversation.mode == mode)
    keyword = (q or "").strip()
    if keyword:
        pattern = f"%{keyword}%"
        if mode == "chat":
            query = query.outerjoin(Message).where(
                or_(Conversation.title.ilike(pattern), Message.content.ilike(pattern))
            )
        elif mode == "work":
            query = query.outerjoin(AgentRun).where(
                or_(Conversation.title.ilike(pattern), AgentRun.input.ilike(pattern))
            )
        else:
            query = (
                query.outerjoin(Message)
                .outerjoin(AgentRun)
                .where(
                    or_(
                        Conversation.title.ilike(pattern),
                        Message.content.ilike(pattern),
                        AgentRun.input.ilike(pattern),
                    )
                )
            )
        query = query.distinct()
    conversations = (await session.scalars(query)).all()
    output: list[ConversationOut] = []
    for conversation in conversations:
        snippet = None
        if keyword:
            content_column = (
                Message.content if conversation.mode == "chat" else AgentRun.input
            )
            content_model = Message if conversation.mode == "chat" else AgentRun
            matched = await session.scalar(
                select(content_column)
                .where(
                    content_model.conversation_id == conversation.id,
                    content_column.ilike(f"%{keyword}%"),
                )
                .order_by(content_model.created_at.desc())
                .limit(1)
            )
            snippet = (
                _snippet(matched, keyword) if matched else _snippet(conversation.title, keyword)
            )
        output.append(_conversation_out(conversation, snippet))
    return output


@router.post("/conversations", response_model=ConversationOut, status_code=status.HTTP_201_CREATED)
async def create_conversation(payload: ConversationCreate, session: SessionDep) -> ConversationOut:
    title = payload.title.strip()
    if payload.mode == "work" and title == "新会话":
        title = "新任务"
    conversation = Conversation(
        mode=payload.mode,
        title=title,
        title_source="manual" if title not in {"新会话", "新任务"} else "default",
    )
    session.add(conversation)
    await session.commit()
    await session.refresh(conversation)
    return _conversation_out(conversation)


@router.patch("/conversations/{conversation_id}", response_model=ConversationOut)
async def patch_conversation(
    conversation_id: UUID, payload: ConversationPatch, session: SessionDep
) -> ConversationOut:
    conversation = await session.get(Conversation, conversation_id)
    if conversation is None:
        raise HTTPException(404, "会话不存在")
    conversation.title = payload.title.strip()
    conversation.title_source = "manual"
    await session.commit()
    await session.refresh(conversation)
    return _conversation_out(conversation)


@router.delete("/conversations/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_conversation(
    conversation_id: UUID, session: SessionDep, settings: SettingsDep
) -> None:
    conversation = await session.scalar(
        select(Conversation)
        .where(Conversation.id == conversation_id)
        .options(
            selectinload(Conversation.files),
            selectinload(Conversation.runs).selectinload(AgentRun.artifacts),
        )
    )
    if conversation is None:
        raise HTTPException(404, "会话不存在")
    keys = [file.storage_key for file in conversation.files]
    keys.extend(artifact.storage_key for run in conversation.runs for artifact in run.artifacts)
    await session.delete(conversation)
    await session.commit()
    storage = get_storage(settings)
    for key in keys:
        try:
            await storage.delete(key)
        except Exception:
            pass


async def _message_query(session: AsyncSession, conversation_id: UUID):
    return (
        (
            await session.scalars(
                select(Message)
                .where(Message.conversation_id == conversation_id, Message.mode == "chat")
                .options(
                    selectinload(Message.parts),
                    selectinload(Message.tool_calls),
                    selectinload(Message.file_links).selectinload(MessageFile.file),
                    selectinload(Message.skill_snapshot),
                )
                .order_by(Message.created_at, Message.id)
            )
        )
        .unique()
        .all()
    )


def _file_out(file: StoredFile) -> dict[str, Any]:
    return FileOut.model_validate(file).model_dump()


def _message_out(message: Message) -> MessageOut:
    return MessageOut(
        id=message.id,
        conversation_id=message.conversation_id,
        role=message.role,
        mode=message.mode,
        agent_type=message.agent_type,
        content=message.content,
        reasoning=message.reasoning,
        follow_up=message.follow_up,
        status=message.status,
        error=message.error,
        created_at=message.created_at,
        parts=[
            {"seq": part.seq, "type": part.type, "content": part.content, "data": part.data}
            for part in message.parts
        ],
        tool_calls=[
            {
                "id": call.id,
                "seq": call.seq,
                "tool_name": call.tool_name,
                "input_summary": call.input_summary,
                "output_summary": call.output_summary,
                "status": call.status,
                "duration_ms": call.duration_ms,
            }
            for call in message.tool_calls
        ],
        files=[FileOut.model_validate(link.file) for link in message.file_links],
        skill=(
            {
                "id": message.skill_snapshot.skill_id,
                "name": message.skill_snapshot.name,
                "description": message.skill_snapshot.description,
            }
            if message.skill_snapshot
            else None
        ),
        run_id=message.run_id,
    )


@router.get("/conversations/{conversation_id}/messages", response_model=list[MessageOut])
async def list_messages(conversation_id: UUID, session: SessionDep) -> list[MessageOut]:
    conversation = await session.get(Conversation, conversation_id)
    if conversation is None:
        raise HTTPException(404, "会话不存在")
    if conversation.mode != "chat":
        return []
    return [_message_out(message) for message in await _message_query(session, conversation_id)]


@router.post("/conversations/{conversation_id}/messages")
async def post_message(
    conversation_id: UUID,
    payload: MessageRequest,
    session: SessionDep,
    settings: SettingsDep,
) -> StreamingResponse:
    conversation = await session.get(Conversation, conversation_id)
    if conversation is None:
        raise HTTPException(404, "会话不存在")
    if conversation.mode != payload.mode:
        raise HTTPException(409, "Chat 和 Work 不能共用同一个会话")
    if payload.mode == "work":
        run_payload = AgentRunRequest(
            conversation_id=conversation_id,
            agent_type=payload.agent_type,
            input=payload.content,
            file_ids=payload.file_ids,
            skill_id=payload.skill_id,
        )
        try:
            run = await create_run(session, run_payload, settings)
        except (LookupError, ValueError, FileValidationError) as exc:
            raise HTTPException(400, str(exc)) from exc
        return sse_response(stream_run(session, run, settings))
    try:
        prepared = await prepare_message(session, conversation_id, payload, settings)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except (ValueError, FileValidationError) as exc:
        raise HTTPException(400, str(exc)) from exc
    return sse_response(stream_prepared_message(session, prepared, settings))


@router.post("/messages/{message_id}/stop", response_model=MessageOut)
async def stop_message(message_id: UUID, session: SessionDep) -> MessageOut:
    try:
        await cancel_message(session, message_id)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    message = next(
        (
            item
            for item in await _message_query(
                session, (await session.get(Message, message_id)).conversation_id
            )
            if item.id == message_id
        ),
        None,
    )
    if message is None:
        raise HTTPException(404, "消息不存在")
    return _message_out(message)


@router.post("/messages/{message_id}/regenerate")
async def regenerate_message(
    message_id: UUID, session: SessionDep, settings: SettingsDep
) -> StreamingResponse:
    try:
        prepared = await prepare_regeneration(session, message_id, settings)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except (ValueError, FileValidationError) as exc:
        raise HTTPException(400, str(exc)) from exc
    return sse_response(stream_prepared_message(session, prepared, settings))


@router.get("/skills", response_model=list[SkillOut])
async def list_skills(session: SessionDep) -> list[Skill]:
    return list((await session.scalars(select(Skill).order_by(Skill.updated_at.desc()))).all())


@router.post("/skills", response_model=SkillOut, status_code=status.HTTP_201_CREATED)
async def create_skill(payload: SkillCreate, session: SessionDep) -> Skill:
    skill = Skill(
        name=payload.name.strip(),
        normalized_name=normalize_skill_name(payload.name),
        description=payload.description.strip(),
        instructions=payload.instructions.strip(),
        enabled=payload.enabled,
    )
    session.add(skill)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(409, "Skill 名称已存在") from exc
    await session.refresh(skill)
    return skill


@router.patch("/skills/{skill_id}", response_model=SkillOut)
async def patch_skill(skill_id: UUID, payload: SkillPatch, session: SessionDep) -> Skill:
    skill = await session.get(Skill, skill_id)
    if skill is None:
        raise HTTPException(404, "Skill 不存在")
    values = payload.model_dump(exclude_unset=True)
    if "name" in values:
        values["name"] = values["name"].strip()
        skill.normalized_name = normalize_skill_name(values["name"])
    for key, value in values.items():
        setattr(skill, key, value.strip() if isinstance(value, str) else value)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(409, "Skill 名称已存在") from exc
    await session.refresh(skill)
    return skill


@router.delete("/skills/{skill_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_skill(skill_id: UUID, session: SessionDep) -> None:
    skill = await session.get(Skill, skill_id)
    if skill is None:
        raise HTTPException(404, "Skill 不存在")
    await session.delete(skill)
    await session.commit()


@router.get("/memory-summary", response_model=MemorySummaryOut)
async def read_memory_summary(session: SessionDep) -> MemorySummary:
    summary = await get_memory_summary_record(session)
    await session.commit()
    await session.refresh(summary)
    return summary


@router.put("/memory-summary", response_model=MemorySummaryOut)
async def update_memory_summary(
    payload: MemorySummaryUpdate, session: SessionDep
) -> MemorySummary:
    app_settings = await get_app_settings(session)
    if not app_settings.memory_enabled:
        raise HTTPException(409, "Memory 已关闭")
    content = payload.content.strip()
    if content and contains_sensitive_memory(content):
        raise HTTPException(400, "不能保存密码、密钥、支付信息等敏感内容")
    summary = await get_memory_summary_record(session)
    summary.content = content
    summary.source = "manual"
    summary.source_conversation_id = None
    await session.commit()
    await session.refresh(summary)
    return summary


@router.delete("/memory-summary", status_code=status.HTTP_204_NO_CONTENT)
async def clear_memory_summary(session: SessionDep) -> None:
    summary = await get_memory_summary_record(session)
    summary.content = ""
    summary.source = "manual"
    summary.source_conversation_id = None
    await session.commit()


@router.post("/maintenance/memory-summary/refine")
async def refine_memory_summary(session: SessionDep) -> dict[str, int]:
    return {"added_facts": await refine_idle_memory_summary(session)}


@router.get("/settings", response_model=AppSettingsOut)
async def read_settings(session: SessionDep, settings: SettingsDep) -> AppSettingsOut:
    stored = await get_app_settings(session)
    return AppSettingsOut(
        memory_enabled=stored.memory_enabled,
        web_search_enabled=stored.web_search_enabled,
        appearance=stored.appearance,
        model_ready=settings.model_ready,
        tavily_ready=settings.tavily_ready,
        storage_backend=settings.storage_backend,
    )


@router.patch("/settings", response_model=AppSettingsOut)
async def patch_settings(
    payload: AppSettingsPatch, session: SessionDep, settings: SettingsDep
) -> AppSettingsOut:
    stored = await get_app_settings(session)
    for key, value in payload.model_dump(exclude_none=True).items():
        setattr(stored, key, value)
    await session.commit()
    return await read_settings(session, settings)


@router.patch("/settings/memory", response_model=AppSettingsOut)
async def patch_memory_setting(
    payload: AppSettingsPatch, session: SessionDep, settings: SettingsDep
) -> AppSettingsOut:
    if payload.memory_enabled is None:
        raise HTTPException(422, "必须提供 memory_enabled")
    return await patch_settings(
        AppSettingsPatch(memory_enabled=payload.memory_enabled), session, settings
    )


@router.post("/files", response_model=FileOut, status_code=status.HTTP_201_CREATED)
async def upload_file(
    session: SessionDep,
    settings: SettingsDep,
    conversation_id: Annotated[UUID, Form()],
    upload: Annotated[UploadFile, File()],
) -> StoredFile:
    if await session.get(Conversation, conversation_id) is None:
        raise HTTPException(404, "会话不存在")
    data = await upload.read(settings.max_upload_bytes + 1)
    try:
        return await create_file(
            session,
            settings,
            conversation_id,
            upload.filename or "upload",
            upload.content_type or "application/octet-stream",
            data,
        )
    except FileValidationError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(500, "文件处理失败，请重试。") from exc


@router.get("/conversations/{conversation_id}/files", response_model=list[FileOut])
async def list_files(conversation_id: UUID, session: SessionDep) -> list[StoredFile]:
    return list(
        (
            await session.scalars(
                select(StoredFile)
                .where(StoredFile.conversation_id == conversation_id)
                .order_by(StoredFile.created_at.desc())
            )
        ).all()
    )


@router.get("/files/{file_id}", response_model=FileOut)
async def get_file(file_id: UUID, session: SessionDep) -> StoredFile:
    stored = await session.get(StoredFile, file_id)
    if stored is None:
        raise HTTPException(404, "文件不存在")
    return stored


@router.delete("/files/{file_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_file(file_id: UUID, session: SessionDep, settings: SettingsDep) -> None:
    stored = await session.get(StoredFile, file_id)
    if stored is None:
        raise HTTPException(404, "文件不存在")
    key = stored.storage_key
    await session.delete(stored)
    await session.commit()
    await get_storage(settings).delete(key)


@router.get("/agents", response_model=list[AgentInfo])
async def list_agents() -> list[AgentInfo]:
    return [
        AgentInfo(
            type="image",
            name="图片 Agent",
            description="把描述和参考图转成可下载图片",
            accepts_images=True,
            output_type="image",
        ),
        AgentInfo(
            type="slides",
            name="演示 Agent",
            description="生成、修改并恢复带确认节点的演示文稿",
            accepts_images=False,
            output_type="pptx",
        ),
        AgentInfo(
            type="research",
            name="研究 Agent",
            description="在共享预算内完成带引用的深度研究",
            accepts_images=False,
            output_type="markdown",
        ),
    ]


@router.post("/agent-runs")
async def start_agent_run(
    payload: AgentRunRequest, session: SessionDep, settings: SettingsDep
) -> StreamingResponse:
    try:
        run = await create_run(session, payload, settings)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except (ValueError, FileValidationError) as exc:
        raise HTTPException(400, str(exc)) from exc
    action = "resume" if payload.intent == "RESUME" else None
    return sse_response(stream_run(session, run, settings, action=action))


def _run_out(run: AgentRun) -> AgentRunOut:
    return AgentRunOut(
        id=run.id,
        conversation_id=run.conversation_id,
        agent_type=run.agent_type,
        intent=run.intent,
        source_run_id=run.source_run_id,
        source_artifact_id=run.source_artifact_id,
        input=run.input,
        stage=run.stage,
        status=run.status,
        answer=run.answer,
        public_state=run.public_state,
        error=run.error,
        events=[
            {
                "seq": event.seq,
                "type": event.type,
                "payload": event.payload,
                "created_at": event.created_at,
            }
            for event in run.events
        ],
        artifacts=[artifact_payload(artifact) for artifact in run.artifacts],
        files=[FileOut.model_validate(link.file) for link in run.file_links],
        skill=(
            {
                "id": run.skill_snapshot.skill_id,
                "name": run.skill_snapshot.name,
                "description": run.skill_snapshot.description,
            }
            if run.skill_snapshot
            else None
        ),
        created_at=run.created_at,
        updated_at=run.updated_at,
    )


@router.get("/agent-runs/{run_id}", response_model=AgentRunOut)
async def get_agent_run(run_id: UUID, session: SessionDep) -> AgentRunOut:
    run = await load_run(session, run_id)
    if run is None:
        raise HTTPException(404, "运行不存在")
    return _run_out(run)


@router.get("/conversations/{conversation_id}/agent-runs", response_model=list[AgentRunOut])
async def list_agent_runs(conversation_id: UUID, session: SessionDep) -> list[AgentRunOut]:
    conversation = await session.get(Conversation, conversation_id)
    if conversation is None:
        raise HTTPException(404, "会话不存在")
    if conversation.mode != "work":
        return []
    ids = (
        await session.scalars(
            select(AgentRun.id)
            .where(AgentRun.conversation_id == conversation_id)
            .order_by(AgentRun.created_at)
        )
    ).all()
    runs = [await load_run(session, run_id) for run_id in ids]
    return [_run_out(run) for run in runs if run]


@router.post("/agent-runs/{run_id}/commands")
async def command_agent_run(
    run_id: UUID,
    payload: AgentRunCommand,
    session: SessionDep,
    settings: SettingsDep,
):
    run = await session.get(AgentRun, run_id)
    if run is None:
        raise HTTPException(404, "运行不存在")
    if payload.action == "cancel":
        await cancel_run(session, run_id)
        loaded = await load_run(session, run_id)
        return _run_out(loaded)
    if run.agent_type != "slides" and payload.action == "confirm":
        raise HTTPException(400, "只有演示 Agent 需要确认")
    if payload.action == "confirm" and run.status != "awaiting_confirmation":
        raise HTTPException(409, "演示运行当前不在等待确认阶段")
    if payload.action == "retry" and run.status not in {"failed", "cancelled"}:
        raise HTTPException(409, "只有失败或已取消的运行可以重试")
    if payload.input:
        run.input = payload.input.strip()
    if payload.action == "retry":
        run.error = None
        run.status = "running"
    await session.commit()
    return sse_response(stream_run(session, run, settings, action=payload.action))


@router.post("/agent-runs/{run_id}/resume")
async def resume_agent_run(
    run_id: UUID, session: SessionDep, settings: SettingsDep
) -> StreamingResponse:
    run = await session.get(AgentRun, run_id)
    if run is None:
        raise HTTPException(404, "运行不存在")
    if run.agent_type != "slides":
        raise HTTPException(400, "只有演示 Agent 支持恢复")
    if run.status not in {"failed", "cancelled", "completed"}:
        raise HTTPException(409, "演示运行当前不可恢复；等待确认时请使用确认操作")
    return sse_response(stream_run(session, run, settings, action="resume"))


@router.get("/artifacts/{artifact_id}/download")
async def download_artifact(artifact_id: UUID, session: SessionDep, settings: SettingsDep):
    artifact = await session.get(Artifact, artifact_id)
    if artifact is None:
        raise HTTPException(404, "产物不存在")
    storage = get_storage(settings)
    local_path = storage.local_path(artifact.storage_key)
    if local_path:
        return FileResponse(
            local_path,
            media_type=artifact.mime_type,
            filename=artifact.name,
        )
    data = await storage.read(artifact.storage_key)
    return StreamingResponse(
        BytesIO(data),
        media_type=artifact.mime_type,
        headers={"Content-Disposition": f'attachment; filename="{artifact.name}"'},
    )
