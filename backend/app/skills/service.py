from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.security import current_user_id
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
    skills = await select_skills(
        session,
        [explicit_skill_id] if explicit_skill_id else [],
        content,
    )
    return SkillSelection(
        skills[0] if skills else None,
        content,
        "explicit" if explicit_skill_id else ("automatic" if skills else None),
    )


async def select_skills(
    session: AsyncSession,
    skill_ids: list[UUID],
    content: str | None = None,
) -> list[Skill]:
    owner_id = current_user_id()
    if skill_ids:
        skills = (
            await session.scalars(
                select(Skill).where(
                    Skill.id.in_(skill_ids),
                    Skill.user_id == owner_id,
                    Skill.enabled.is_(True),
                )
            )
        ).all()
        by_id = {skill.id: skill for skill in skills}
        if any(skill_id not in by_id for skill_id in skill_ids):
            raise ValueError("所选 Skill 不存在或已停用")
        return [by_id[skill_id] for skill_id in skill_ids]
    if not content:
        return []

    enabled = (
        await session.scalars(
            select(Skill).where(
                Skill.user_id == owner_id, Skill.enabled.is_(True)
            )
        )
    ).all()
    ranked: list[tuple[float, Skill]] = []
    for skill in enabled:
        candidate = _remove_at_mention(content, skill.name)
        content_terms = _terms(candidate)
        score = len(content_terms & _terms(skill.name)) * 3
        score += len(content_terms & _terms(skill.description))
        if normalize_skill_name(skill.name) in normalize_skill_name(candidate):
            score += 5
        if score > 0:
            ranked.append((float(score), skill))
    ranked.sort(key=lambda pair: pair[0], reverse=True)
    return [ranked[0][1]] if ranked else []


def _terms(text: str) -> set[str]:
    lower = normalize_skill_name(text)
    return set(re.findall(r"[a-z0-9_]{2,}|[\u4e00-\u9fff]{2,}", lower))


def _remove_at_mention(content: str, name: str) -> str:
    return re.sub(
        rf"(?<!\w)@{re.escape(name)}(?=\s|$|[，,。.!！?？:：])",
        "",
        content,
        flags=re.I,
    )


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


async def snapshot_skills(session: AsyncSession, skills: list[Skill]) -> list[SkillSnapshot]:
    snapshots: list[SkillSnapshot] = []
    for skill in skills:
        snapshot = await snapshot_skill(session, skill)
        if snapshot is not None:
            snapshots.append(snapshot)
    return snapshots
