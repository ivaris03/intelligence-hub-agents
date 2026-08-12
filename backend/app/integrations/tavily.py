from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from langchain_mcp_adapters.client import MultiServerMCPClient

from app.core.config import Settings


@dataclass(slots=True)
class SearchResult:
    title: str
    url: str
    snippet: str

    def as_dict(self) -> dict[str, str]:
        return {"title": self.title, "url": self.url, "snippet": self.snippet}


class TavilyAdapter:
    """Restricted Tavily MCP client that exposes normalized, citation-safe results."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def _url(self) -> str:
        if not self.settings.tavily_api_key:
            raise RuntimeError("Tavily MCP 未配置")
        parts = urlsplit(self.settings.tavily_mcp_url)
        query = dict(parse_qsl(parts.query, keep_blank_values=True))
        query["tavilyApiKey"] = self.settings.tavily_api_key
        return urlunsplit(
            (parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment)
        )

    async def search(self, query: str, *, max_results: int = 5) -> list[SearchResult]:
        if not query.strip():
            return []
        client = MultiServerMCPClient(
            {
                "tavily": {
                    "transport": "streamable_http",
                    "url": self._url(),
                }
            }
        )
        tools = await client.get_tools()
        tool = next((candidate for candidate in tools if "search" in candidate.name.lower()), None)
        if tool is None:
            raise RuntimeError("Tavily MCP 未提供搜索工具")
        payload = {"query": query, "max_results": max(1, min(max_results, 8))}
        try:
            raw = await tool.ainvoke(payload)
        except Exception:
            raw = await tool.ainvoke({"query": query})
        return self._normalize(raw)[:max_results]

    @classmethod
    def _normalize(cls, raw: Any) -> list[SearchResult]:
        results: list[SearchResult] = []
        seen: set[str] = set()
        for item in cls._candidate_dicts(raw):
            url = str(item.get("url") or item.get("link") or "").strip()
            if not url.startswith(("https://", "http://")) or url in seen:
                continue
            seen.add(url)
            results.append(
                SearchResult(
                    title=str(item.get("title") or url)[:300],
                    url=url,
                    snippet=str(
                        item.get("content") or item.get("snippet") or item.get("description") or ""
                    )[:1500],
                )
            )
        return results

    @classmethod
    def _candidate_dicts(cls, raw: Any) -> list[dict[str, Any]]:
        value = cls._unwrap(raw)
        if isinstance(value, list):
            return [candidate for item in value for candidate in cls._candidate_dicts(item)]
        if not isinstance(value, dict):
            return []
        if value.get("url") or value.get("link"):
            return [value]
        candidates: list[dict[str, Any]] = []
        for key in ("results", "sources", "data", "content", "text"):
            if key in value:
                candidates.extend(cls._candidate_dicts(value[key]))
        return candidates

    @classmethod
    def _unwrap(cls, raw: Any) -> Any:
        if hasattr(raw, "model_dump"):
            return cls._unwrap(raw.model_dump())
        if isinstance(raw, (dict, list)):
            return raw
        if isinstance(raw, str):
            text = raw.strip()
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                start, end = text.find("{"), text.rfind("}")
                if start >= 0 and end > start:
                    try:
                        return json.loads(text[start : end + 1])
                    except json.JSONDecodeError:
                        return []
                return []
        if hasattr(raw, "content"):
            return cls._unwrap(raw.content)
        return []
