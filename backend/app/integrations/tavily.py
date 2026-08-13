from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from langchain_core.messages import HumanMessage
from langchain_mcp_adapters.client import MultiServerMCPClient
from pydantic import BaseModel, Field

from app.core.config import Settings
from app.integrations.qwen import QwenAdapter
from app.observability.langsmith import finish_trace, trace_operation


@dataclass(slots=True)
class SearchResult:
    title: str
    url: str
    snippet: str

    def as_dict(self) -> dict[str, str]:
        return {"title": self.title, "url": self.url, "snippet": self.snippet}


class SearchSelection(BaseModel):
    selected_indices: list[int] = Field(default_factory=list, max_length=5)


def _search_terms(text: str) -> set[str]:
    lower = text.casefold()
    terms = set(re.findall(r"[a-z0-9_@.-]{2,}|[\u4e00-\u9fff]", lower))
    chinese = "".join(re.findall(r"[\u4e00-\u9fff]", lower))
    terms.update(chinese[index : index + 2] for index in range(max(0, len(chinese) - 1)))
    return terms


def search_query_variants(query: str, *, limit: int = 3) -> list[str]:
    """Create bounded facet queries for enumerated search requests."""

    variants = [query.strip()]
    match = re.search(
        r"(?:说明|比较|整理|覆盖|创建)\s*(?P<body>[^。！？!?]+)", query, re.I
    )
    if not match:
        return variants
    prefix = query[: match.start()].strip(" ，,:：")
    body = match.group("body")
    parts = [
        part.strip(" ，,:：")
        for part in re.split(
            r"、|；|;|以及|及|与|和|并(?=(?:运行|创建|写入|调用|说明))",
            body,
        )
        if part.strip(" ，,:：")
    ]
    if len(parts) < 2:
        return variants
    parts_to_use = parts if len(parts) <= limit - 1 else parts[-(limit - 1) :]
    for part in parts_to_use:
        candidate = f"{prefix} {part}".strip()
        if candidate not in variants:
            variants.append(candidate)
        if len(variants) >= limit:
            break
    return variants


async def rerank_search_results(
    query: str,
    results: list[SearchResult],
    settings: Settings,
    *,
    limit: int = 5,
) -> list[SearchResult]:
    """Select a relevant, collectively comprehensive result set from MCP output."""

    if len(results) <= limit:
        return results
    selected_indices: list[int] = []
    if settings.model_ready:
        try:
            selector = (
                QwenAdapter(settings).chat_model(work=True).with_structured_output(SearchSelection)
            )
            selection = SearchSelection.model_validate(
                await selector.ainvoke(
                    [
                        HumanMessage(
                            content=(
                                "从候选搜索结果中选择最多 5 条。目标按顺序是："
                                "完整覆盖查询的不同方面、"
                                "与查询直接相关、优先官方或一手来源、避免重复页面。"
                                "selected_indices 使用下面数组的 0-based 索引，"
                                "不得输出范围外索引。\n"
                                f"查询：{query}\n候选："
                                + json.dumps(
                                    [
                                        {
                                            "index": index,
                                            "title": item.title,
                                            "url": item.url,
                                            "snippet": item.snippet[:600],
                                        }
                                        for index, item in enumerate(results)
                                    ],
                                    ensure_ascii=False,
                                )
                            )
                        )
                    ],
                    config={"run_name": "search.rerank", "tags": ["search", "rerank"]},
                )
            )
            selected_indices = list(
                dict.fromkeys(
                    index for index in selection.selected_indices if 0 <= index < len(results)
                )
            )[:limit]
        except Exception:
            selected_indices = []

    query_terms = _search_terms(query)

    def relevance(index: int) -> tuple[float, int]:
        item = results[index]
        title_terms = _search_terms(item.title)
        all_terms = title_terms | _search_terms(item.snippet)
        overlap = len(query_terms & all_terms) / max(1, len(query_terms))
        title_overlap = len(query_terms & title_terms) / max(1, len(query_terms))
        return overlap + title_overlap * 0.5, -index

    for index in sorted(range(len(results)), key=relevance, reverse=True):
        if len(selected_indices) >= limit:
            break
        if index not in selected_indices:
            selected_indices.append(index)
    return [results[index] for index in selected_indices]


def normalize_search_citations(answer: str, results: list[SearchResult]) -> str:
    """Turn provider numeric citations into adjacent Markdown links with verified URLs."""

    def replace(match: re.Match[str]) -> str:
        index = int(match.group(1)) - 1
        if not 0 <= index < len(results):
            return match.group(0)
        result = results[index]
        return f"[{result.title}]({result.url})"

    # A numeric index may be paired with a copied, shortened, or malformed URL.
    # Replace the whole Markdown link first; the index refers to our exact result list.
    normalized = re.sub(r"\[(\d{1,2})\]\([^\n)]*\)", replace, answer)
    return re.sub(r"\[(\d{1,2})\](?!\()", replace, normalized)


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
        with trace_operation(
            self.settings,
            "tavily.mcp.search",
            inputs={"query": query, "max_results": max_results},
            run_type="tool",
            tags=["mcp", "search", "tavily"],
            metadata={"tool": "tavily-search", "transport": "streamable_http"},
        ) as trace:
            results = await self._search(query, max_results=max_results)
            finish_trace(trace, {"results": [item.as_dict() for item in results]})
            return results

    async def _search(self, query: str, *, max_results: int = 5) -> list[SearchResult]:
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
        payload = {
            "query": query,
            "max_results": max(1, min(max_results, 8)),
            # Detailed technical questions benefit from several directly extracted
            # chunks per result instead of a generic one-line summary.
            "search_depth": "advanced",
        }
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


async def comprehensive_search(
    query: str,
    settings: Settings,
    *,
    max_queries: int = 3,
    results_per_query: int = 5,
) -> list[SearchResult]:
    """Search the original request and its most important explicit facets."""

    adapter = TavilyAdapter(settings)
    batches = await asyncio.gather(
        *(
            adapter.search(variant, max_results=results_per_query)
            for variant in search_query_variants(query, limit=max_queries)
        ),
        return_exceptions=True,
    )
    merged: list[SearchResult] = []
    seen: set[str] = set()
    for batch in batches:
        if isinstance(batch, BaseException):
            continue
        for item in batch:
            canonical = item.url.rstrip("/")
            if canonical in seen:
                continue
            seen.add(canonical)
            merged.append(item)
    return merged
