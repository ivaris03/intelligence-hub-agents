from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.security import contains_sensitive_memory
from app.db.base import AppSettings, Conversation, Memory, Message


@dataclass(slots=True)
class MemoryCommandResult:
    action: str
    message: str
    changed: int


def normalize_memory(text: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", text).casefold().split())


def memory_key(text: str) -> str:
    return hashlib.sha256(normalize_memory(text).encode()).hexdigest()


async def get_app_settings(session: AsyncSession) -> AppSettings:
    settings = await session.get(AppSettings, 1)
    if settings is None:
        settings = AppSettings(id=1, memory_enabled=True, web_search_enabled=True)
        session.add(settings)
        await session.flush()
    return settings


def parse_memory_command(content: str) -> tuple[str, str] | None:
    stripped = content.strip()
    patterns = (
        ("remember", r"(?:^|[，,。；;])(?:请)?记住(?:一下)?[：:\s]*(.+)$"),
        ("forget", r"(?:^|[，,。；;])(?:请)?忘记(?:掉)?[：:\s]*(.+)$"),
        ("remember", r"(?i)^remember(?: that)?[：:\s]+(.+)$"),
        ("forget", r"(?i)^forget(?: that)?[：:\s]+(.+)$"),
    )
    for action, pattern in patterns:
        match = re.search(pattern, stripped, re.S)
        if match:
            return action, match.group(1).strip()
    return None


async def handle_memory_command(
    session: AsyncSession, conversation_id: UUID, content: str
) -> MemoryCommandResult | None:
    command = parse_memory_command(content)
    if command is None:
        return None
    app_settings = await get_app_settings(session)
    if not app_settings.memory_enabled:
        return MemoryCommandResult("disabled", "Memory 已关闭，本次没有写入或删除记忆。", 0)
    action, target = command
    if not target:
        return MemoryCommandResult(action, "请说明需要记住或忘记的具体内容。", 0)
    if action == "remember":
        if contains_sensitive_memory(target):
            return MemoryCommandResult(
                action, "这段内容可能包含密码、密钥或支付信息，已拒绝保存。", 0
            )
        key = memory_key(target)
        existing = await session.scalar(select(Memory).where(Memory.normalized_key == key))
        if existing:
            existing.content = target
            existing.source = "explicit"
            existing.source_conversation_id = conversation_id
            return MemoryCommandResult(action, f"已经记住：{target}", 1)
        session.add(
            Memory(
                content=target,
                normalized_key=key,
                source="explicit",
                source_conversation_id=conversation_id,
            )
        )
        return MemoryCommandResult(action, f"已经记住：{target}", 1)

    normalized_target = normalize_memory(target)
    memories = (await session.scalars(select(Memory))).all()
    matches = [
        memory
        for memory in memories
        if normalized_target in normalize_memory(memory.content)
        or normalize_memory(memory.content) in normalized_target
        or _relevance(target, memory.content) >= 0.5
    ]
    for memory in matches:
        await session.delete(memory)
    if not matches:
        return MemoryCommandResult(action, f"没有找到与“{target}”匹配的记忆。", 0)
    return MemoryCommandResult(action, f"已忘记 {len(matches)} 条相关记忆。", len(matches))


async def relevant_memories(session: AsyncSession, query: str, settings: Settings) -> list[Memory]:
    app_settings = await get_app_settings(session)
    if not app_settings.memory_enabled:
        return []
    memories = (await session.scalars(select(Memory).order_by(Memory.updated_at.desc()))).all()
    ranked = sorted(
        ((_relevance(query, memory.content), memory) for memory in memories),
        key=lambda pair: pair[0],
        reverse=True,
    )
    selected: list[Memory] = []
    chars = 0
    for score, memory in ranked:
        if score <= 0:
            continue
        if chars + len(memory.content) > settings.memory_context_chars:
            continue
        selected.append(memory)
        chars += len(memory.content)
        if len(selected) >= settings.memory_max_items:
            break
    return selected


def _terms(text: str) -> set[str]:
    normalized = normalize_memory(text)
    terms = set(re.findall(r"[a-z0-9_]{2,}|[\u4e00-\u9fff]", normalized))
    chinese = "".join(re.findall(r"[\u4e00-\u9fff]", normalized))
    terms.update(chinese[index : index + 2] for index in range(max(0, len(chinese) - 1)))
    return terms


def _relevance(query: str, memory: str) -> float:
    left, right = _terms(query), _terms(memory)
    return len(left & right) / max(1, min(len(left), len(right)))


def _extract_candidates(messages: list[Message]) -> list[str]:
    candidates: list[str] = []
    for message in messages:
        for sentence in re.split(r"[。！？!?\n]+", message.content):
            sentence = sentence.strip(" ，,;；")
            if not 4 <= len(sentence) <= 200:
                continue
            if re.search(r"可能|也许|或许|不确定|大概|maybe|perhaps", sentence, re.I):
                continue
            if re.match(r"^(?:我|我的|本人)(?:喜欢|偏好|习惯|常用|从事|居住|是)", sentence):
                candidates.append(sentence)
    return candidates


def _subject_signature(text: str) -> str:
    normalized = normalize_memory(text)
    normalized = re.sub(r"不|没有|并非|讨厌|不喜欢", "", normalized)
    return "".join(sorted(_terms(normalized)))[:120]


def _memory_slot(text: str) -> tuple[str, str] | None:
    """Return a conservative slot used to avoid automatic preference conflicts."""

    normalized = re.sub(r"[^a-z0-9\u4e00-\u9fff]", "", normalize_memory(text))
    match = re.match(r"^(?:我|我的|本人)(喜欢|偏好|习惯|常用|从事|居住|是)(.+)$", normalized)
    if not match:
        return None
    predicate, value = match.groups()
    chinese = "".join(re.findall(r"[\u4e00-\u9fff]", value))
    topic = chinese[-2:] if len(chinese) >= 2 else value[-12:]
    return predicate, topic


async def refine_idle_memories(
    session: AsyncSession, settings: Settings, now: datetime | None = None
) -> int:
    app_settings = await get_app_settings(session)
    if not app_settings.memory_enabled:
        return 0
    cutoff = (now or datetime.now(UTC)) - timedelta(minutes=30)
    conversations = (
        await session.scalars(
            select(Conversation).where(
                Conversation.last_activity_at <= cutoff,
                or_(
                    Conversation.memory_cursor.is_(None),
                    Conversation.memory_cursor < Conversation.last_activity_at,
                ),
            )
        )
    ).all()
    written = 0
    all_memories = (await session.scalars(select(Memory))).all()
    signatures = {_subject_signature(memory.content): memory for memory in all_memories}
    for conversation in conversations:
        query = select(Message).where(
            Message.conversation_id == conversation.id,
            Message.role == "user",
            Message.created_at <= conversation.last_activity_at,
        )
        if conversation.memory_cursor:
            query = query.where(Message.created_at > conversation.memory_cursor)
        messages = (await session.scalars(query.order_by(Message.created_at))).all()
        for candidate in _extract_candidates(messages):
            if contains_sensitive_memory(candidate):
                continue
            key = memory_key(candidate)
            if any(memory.normalized_key == key for memory in all_memories):
                continue
            signature = _subject_signature(candidate)
            candidate_slot = _memory_slot(candidate)
            conflicting = signatures.get(signature)
            slot_conflict = next(
                (
                    memory
                    for memory in all_memories
                    if candidate_slot is not None
                    and _memory_slot(memory.content) == candidate_slot
                    and normalize_memory(memory.content) != normalize_memory(candidate)
                ),
                None,
            )
            if (conflicting or slot_conflict) and not any(
                normalize_memory(memory.content) == normalize_memory(candidate)
                for memory in all_memories
            ):
                continue
            memory = Memory(
                content=candidate,
                normalized_key=key,
                source="automatic",
                source_conversation_id=conversation.id,
            )
            session.add(memory)
            all_memories.append(memory)
            signatures[signature] = memory
            written += 1
        conversation.memory_cursor = conversation.last_activity_at
    await session.commit()
    return written


async def clear_memories(session: AsyncSession) -> int:
    result = await session.execute(delete(Memory))
    return int(result.rowcount or 0)
