from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import contains_sensitive_memory
from app.db.base import AppSettings, Conversation, MemorySummary, Message

MEMORY_SUMMARY_ID = 1
MAX_MEMORY_SUMMARY_CHARS = 4_000


@dataclass(slots=True)
class MemoryCommandResult:
    action: str
    message: str
    changed: int


def normalize_memory(text: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", text).casefold().split())


async def get_app_settings(session: AsyncSession) -> AppSettings:
    settings = await session.get(AppSettings, 1)
    if settings is None:
        settings = AppSettings(id=1, memory_enabled=True, web_search_enabled=True)
        session.add(settings)
        await session.flush()
    return settings


async def get_memory_summary_record(session: AsyncSession) -> MemorySummary:
    summary = await session.get(MemorySummary, MEMORY_SUMMARY_ID)
    if summary is None:
        summary = MemorySummary(id=MEMORY_SUMMARY_ID, content="", source="manual")
        session.add(summary)
        await session.flush()
    return summary


async def memory_summary(session: AsyncSession) -> str:
    app_settings = await get_app_settings(session)
    if not app_settings.memory_enabled:
        return ""
    summary = await get_memory_summary_record(session)
    return summary.content.strip()


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


def _summary_facts(text: str) -> list[str]:
    facts: list[str] = []
    for part in re.split(r"[。！？!?；;\n]+", text):
        fact = re.sub(r"^\s*[-*•]\s*", "", part).strip(" ，,。；;\t")
        if fact and normalize_memory(fact) not in {normalize_memory(item) for item in facts}:
            facts.append(fact)
    return facts


def _compose_summary(facts: list[str]) -> str:
    cleaned = [fact.strip(" ，,。；;\t") for fact in facts if fact.strip(" ，,。；;\t")]
    if not cleaned:
        return ""
    return "；".join(cleaned) + "。"


def _append_fact(summary: str, fact: str) -> str | None:
    facts = _summary_facts(summary)
    normalized = normalize_memory(fact)
    if any(normalize_memory(item) == normalized for item in facts):
        return summary
    candidate = _compose_summary([*facts, fact])
    if len(candidate) > MAX_MEMORY_SUMMARY_CHARS:
        return None
    return candidate


async def handle_memory_command(
    session: AsyncSession, conversation_id: UUID, content: str
) -> MemoryCommandResult | None:
    command = parse_memory_command(content)
    if command is None:
        return None
    app_settings = await get_app_settings(session)
    if not app_settings.memory_enabled:
        return MemoryCommandResult("disabled", "Memory 已关闭，本次没有更新记忆摘要。", 0)
    action, target = command
    if not target:
        return MemoryCommandResult(action, "请说明需要记住或忘记的具体内容。", 0)

    summary = await get_memory_summary_record(session)
    if action == "remember":
        if contains_sensitive_memory(target):
            return MemoryCommandResult(
                action, "这段内容可能包含密码、密钥或支付信息，已拒绝保存。", 0
            )
        updated = _append_fact(summary.content, target)
        if updated is None:
            return MemoryCommandResult(action, "用户记忆摘要已达到长度上限，请先精简。", 0)
        changed = int(updated != summary.content)
        summary.content = updated
        summary.source = "explicit"
        summary.source_conversation_id = conversation_id
        return MemoryCommandResult(action, f"已更新用户记忆摘要：{target}", changed)

    facts = _summary_facts(summary.content)
    normalized_target = normalize_memory(target)
    matches = [
        fact
        for fact in facts
        if normalized_target in normalize_memory(fact)
        or normalize_memory(fact) in normalized_target
        or _relevance(target, fact) >= 0.5
    ]
    if not matches:
        return MemoryCommandResult(action, f"记忆摘要中没有找到与“{target}”匹配的内容。", 0)
    summary.content = _compose_summary([fact for fact in facts if fact not in matches])
    summary.source = "explicit"
    summary.source_conversation_id = conversation_id
    return MemoryCommandResult(action, "已从用户记忆摘要中移除相关内容。", len(matches))


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


async def refine_idle_memory_summary(
    session: AsyncSession, now: datetime | None = None
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
    summary = await get_memory_summary_record(session)
    facts = _summary_facts(summary.content)
    signatures = {_subject_signature(fact) for fact in facts}
    written = 0
    last_source_conversation_id: UUID | None = None

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
            normalized_candidate = normalize_memory(candidate)
            if any(normalize_memory(fact) == normalized_candidate for fact in facts):
                continue
            signature = _subject_signature(candidate)
            candidate_slot = _memory_slot(candidate)
            slot_conflict = any(
                candidate_slot is not None
                and _memory_slot(fact) == candidate_slot
                and normalize_memory(fact) != normalized_candidate
                for fact in facts
            )
            if signature in signatures or slot_conflict:
                continue
            updated = _append_fact(_compose_summary(facts), candidate)
            if updated is None:
                continue
            facts = _summary_facts(updated)
            signatures.add(signature)
            written += 1
            last_source_conversation_id = conversation.id
        conversation.memory_cursor = conversation.last_activity_at

    if written:
        summary.content = _compose_summary(facts)
        summary.source = "automatic"
        summary.source_conversation_id = last_source_conversation_id
    await session.commit()
    return written
