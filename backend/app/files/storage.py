from __future__ import annotations

import asyncio
from io import BytesIO
from pathlib import Path, PurePosixPath
from uuid import uuid4

from minio import Minio

from app.core.config import Settings


class StorageError(RuntimeError):
    pass


def make_storage_key(namespace: str, suffix: str = "") -> str:
    safe_suffix = suffix.lower() if suffix.startswith(".") and len(suffix) <= 12 else ""
    return str(PurePosixPath(namespace) / f"{uuid4().hex}{safe_suffix}")


class LocalStorage:
    def __init__(self, root: Path) -> None:
        self.root = root.expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _resolve(self, key: str) -> Path:
        relative = Path(*PurePosixPath(key).parts)
        target = (self.root / relative).resolve()
        if target != self.root and self.root not in target.parents:
            raise StorageError("非法存储路径")
        return target

    async def save(self, key: str, data: bytes, content_type: str) -> None:
        del content_type
        target = self._resolve(key)
        target.parent.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(target.write_bytes, data)

    async def read(self, key: str) -> bytes:
        target = self._resolve(key)
        if not target.is_file():
            raise StorageError("文件不存在")
        return await asyncio.to_thread(target.read_bytes)

    async def delete(self, key: str) -> None:
        target = self._resolve(key)
        if target.is_file():
            await asyncio.to_thread(target.unlink)

    def local_path(self, key: str) -> Path | None:
        target = self._resolve(key)
        return target if target.is_file() else None


class MinioStorage:
    def __init__(self, settings: Settings) -> None:
        self.bucket = settings.minio_bucket
        self.client = Minio(
            settings.minio_endpoint,
            access_key=settings.minio_access_key,
            secret_key=settings.minio_secret_key,
            secure=settings.minio_secure,
        )

    async def _ensure_bucket(self) -> None:
        exists = await asyncio.to_thread(self.client.bucket_exists, self.bucket)
        if not exists:
            await asyncio.to_thread(self.client.make_bucket, self.bucket)

    async def save(self, key: str, data: bytes, content_type: str) -> None:
        await self._ensure_bucket()
        await asyncio.to_thread(
            self.client.put_object,
            self.bucket,
            key,
            BytesIO(data),
            len(data),
            content_type=content_type,
        )

    async def read(self, key: str) -> bytes:
        response = await asyncio.to_thread(self.client.get_object, self.bucket, key)
        try:
            return await asyncio.to_thread(response.read)
        finally:
            response.close()
            response.release_conn()

    async def delete(self, key: str) -> None:
        await asyncio.to_thread(self.client.remove_object, self.bucket, key)

    def local_path(self, key: str) -> None:
        del key
        return None


def get_storage(settings: Settings) -> LocalStorage | MinioStorage:
    if settings.storage_backend.lower() == "local":
        return LocalStorage(settings.storage_path)
    if settings.storage_backend.lower() == "minio":
        return MinioStorage(settings)
    raise StorageError("STORAGE_BACKEND 仅支持 local 或 minio")
