from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from functools import lru_cache
from typing import Any

import langsmith as ls
from langsmith import Client
from langsmith.run_trees import RunTree

from app.core.config import Settings


@lru_cache(maxsize=4)
def _client(endpoint: str, api_key: str) -> Client:
    return Client(api_url=endpoint, api_key=api_key)


def langsmith_client(settings: Settings) -> Client:
    """Return the configured LangSmith client without leaking credentials to traces."""

    if not settings.langsmith_api_key:
        raise RuntimeError("LangSmith API Key 未配置")
    return _client(settings.langsmith_endpoint, settings.langsmith_api_key)


@contextmanager
def trace_operation(
    settings: Settings,
    name: str,
    *,
    inputs: Mapping[str, Any],
    run_type: str = "chain",
    tags: list[str] | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> Iterator[RunTree | None]:
    """Create an explicit root/child span while preserving a no-op local mode."""

    if not settings.langsmith_ready:
        yield None
        return

    client = langsmith_client(settings)
    trace_metadata = {
        "app": "intelligence-hub",
        "app_env": settings.app_env,
        **dict(metadata or {}),
    }
    with ls.tracing_context(
        enabled=True,
        client=client,
        project_name=settings.langsmith_project,
        tags=tags,
        metadata=trace_metadata,
    ):
        with ls.trace(
            name,
            run_type=run_type,
            inputs=dict(inputs),
            client=client,
            project_name=settings.langsmith_project,
            tags=tags,
            metadata=trace_metadata,
        ) as run:
            yield run


def finish_trace(run: RunTree | None, outputs: Mapping[str, Any]) -> None:
    if run is not None:
        run.end(outputs=dict(outputs))
