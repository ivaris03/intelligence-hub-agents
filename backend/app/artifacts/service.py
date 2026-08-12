from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.db.base import Artifact
from app.files.storage import get_storage, make_storage_key

EXTENSION_BY_TYPE = {"image": ".png", "pptx": ".pptx", "markdown": ".md"}
MIME_BY_TYPE = {
    "image": "image/png",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "markdown": "text/markdown; charset=utf-8",
}


async def create_artifact(
    session: AsyncSession,
    settings: Settings,
    *,
    run_id: UUID,
    artifact_type: str,
    name: str,
    data: bytes,
    parent_artifact: Artifact | None = None,
    metadata: dict[str, Any] | None = None,
) -> Artifact:
    if artifact_type not in EXTENSION_BY_TYPE:
        raise ValueError("不支持的产物类型")
    version = parent_artifact.version + 1 if parent_artifact else 1
    existing = await session.scalar(
        select(Artifact).where(
            Artifact.run_id == run_id,
            Artifact.type == artifact_type,
            Artifact.version == version,
        )
    )
    if existing:
        return existing
    key = make_storage_key("artifacts", EXTENSION_BY_TYPE[artifact_type])
    safe_name = Path(name).name[:255]
    if not safe_name.lower().endswith(EXTENSION_BY_TYPE[artifact_type]):
        safe_name += EXTENSION_BY_TYPE[artifact_type]
    await get_storage(settings).save(key, data, MIME_BY_TYPE[artifact_type])
    artifact = Artifact(
        run_id=run_id,
        parent_artifact_id=parent_artifact.id if parent_artifact else None,
        version=version,
        type=artifact_type,
        name=safe_name,
        storage_key=key,
        mime_type=MIME_BY_TYPE[artifact_type],
        size=len(data),
        artifact_metadata=metadata or {},
    )
    session.add(artifact)
    await session.flush()
    return artifact


def artifact_payload(artifact: Artifact) -> dict[str, Any]:
    return {
        "id": str(artifact.id),
        "run_id": str(artifact.run_id),
        "parent_artifact_id": (
            str(artifact.parent_artifact_id) if artifact.parent_artifact_id else None
        ),
        "version": artifact.version,
        "type": artifact.type,
        "name": artifact.name,
        "mime_type": artifact.mime_type,
        "size": artifact.size,
        "metadata": artifact.artifact_metadata,
        "download_url": f"/api/artifacts/{artifact.id}/download",
        "created_at": artifact.created_at.isoformat() if artifact.created_at else None,
    }


async def next_version(session: AsyncSession, parent_artifact_id: UUID | None) -> int:
    if not parent_artifact_id:
        return 1
    parent = await session.get(Artifact, parent_artifact_id)
    if not parent:
        raise LookupError("源产物不存在")
    latest = await session.scalar(
        select(func.max(Artifact.version)).where(
            (Artifact.id == parent.id) | (Artifact.parent_artifact_id == parent.id)
        )
    )
    return int(latest or parent.version) + 1
