import asyncio
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import public_router, router
from app.auth.routes import router as auth_router
from app.core.config import get_settings
from app.db.session import AsyncSessionLocal
from app.memory.service import (
    process_due_memory_conversations,
    queue_idle_memory_conversations,
)

settings = get_settings()


async def _memory_refinement_loop() -> None:
    while True:
        try:
            async with AsyncSessionLocal() as session:
                await queue_idle_memory_conversations(
                    session,
                    idle_hours=settings.memory_idle_hours,
                    timezone_name=settings.memory_batch_timezone,
                )
                await process_due_memory_conversations(session)
        except asyncio.CancelledError:
            raise
        except Exception:
            # Database/model availability is surfaced by health/settings and explicit APIs.
            pass
        await asyncio.sleep(60)


@asynccontextmanager
async def lifespan(_: FastAPI):
    worker = asyncio.create_task(_memory_refinement_loop())
    try:
        yield
    finally:
        worker.cancel()
        with suppress(asyncio.CancelledError):
            await worker


app = FastAPI(title=settings.app_name, version="0.2.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.web_origin],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(router, prefix=settings.api_prefix)
app.include_router(auth_router, prefix=settings.api_prefix)
app.include_router(public_router, prefix=settings.api_prefix)


@app.get("/", include_in_schema=False)
async def root() -> dict[str, str]:
    return {"name": settings.app_name, "docs": "/docs"}
