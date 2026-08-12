from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import Skill, SkillSnapshot


def normalize_skill_name(name: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", name).casefold().split())


@dataclass(slots=True)
class SkillSelection:
    skill: Skill | None
    cleaned_content: str
    reason: str | None = None


async def select_skill(
    session: AsyncSession, content: str, explicit_skill_id: UUID | None = None
) -> SkillSelection:
    if explicit_skill_id:
        skill = await session.scalar(
            select(Skill).where(Skill.id == explicit_skill_id, Skill.enabled.is_(True))
        )
        if skill is None:
            raise ValueError("所选 Skill 不存在或已停用")
        return SkillSelection(skill, _remove_explicit_mention(content, skill.name), "explicit")

    summaries = (
        await session.execute(
            select(Skill.id, Skill.name, Skill.description).where(Skill.enabled.is_(True))
        )
    ).all()
    if not summaries:
        return SkillSelection(None, content)

    normalized_content = unicodedata.normalize("NFKC", content)
    explicit: tuple[UUID, str] | None = None
    for skill_id, name, _ in sorted(summaries, key=lambda row: len(row.name), reverse=True):
        if re.search(
            rf"(?<!\w)@{re.escape(name)}(?=\s|$|[，,。.!！?？:：])", normalized_content, re.I
        ):
            explicit = (skill_id, name)
            break
    if explicit:
        skill = await session.get(Skill, explicit[0])
        return SkillSelection(skill, _remove_explicit_mention(content, explicit[1]), "explicit")

    content_terms = _terms(content)
    ranked: list[tuple[float, UUID]] = []
    for skill_id, name, description in summaries:
        name_terms = _terms(name)
        description_terms = _terms(description)
        score = len(content_terms & name_terms) * 3 + len(content_terms & description_terms)
        if normalize_skill_name(name) in normalize_skill_name(content):
            score += 5
        if score > 0:
            ranked.append((float(score), skill_id))
    if not ranked:
        return SkillSelection(None, content)
    ranked.sort(key=lambda pair: pair[0], reverse=True)
    skill = await session.get(Skill, ranked[0][1])
    return SkillSelection(skill, content, "automatic")


def _terms(text: str) -> set[str]:
    lower = normalize_skill_name(text)
    return set(re.findall(r"[a-z0-9_]{2,}|[\u4e00-\u9fff]{2,}", lower))


def _remove_explicit_mention(content: str, name: str) -> str:
    cleaned = re.sub(
        rf"(?<!\w)@{re.escape(name)}(?=\s|$|[，,。.!！?？:：])", "", content, count=1, flags=re.I
    )
    return cleaned.strip() or content.strip()


async def snapshot_skill(session: AsyncSession, skill: Skill | None) -> SkillSnapshot | None:
    if skill is None:
        return None
    digest = hashlib.sha256(
        f"{skill.name}\0{skill.description}\0{skill.instructions}".encode()
    ).hexdigest()
    snapshot = SkillSnapshot(
        skill_id=skill.id,
        name=skill.name,
        description=skill.description,
        instructions=skill.instructions,
        content_hash=digest,
    )
    session.add(snapshot)
    await session.flush()
    return snapshot
