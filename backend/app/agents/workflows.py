from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass, field
from time import monotonic
from typing import Any, Literal, TypedDict
from urllib.parse import urlparse

from deepagents import create_deep_agent
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt
from pydantic import BaseModel, Field

from app.core.config import Settings
from app.core.security import remove_unverified_urls
from app.integrations.qwen import QwenAdapter
from app.integrations.tavily import SearchResult, TavilyAdapter


class ImageBrief(BaseModel):
    prompt: str
    style: str = "editorial"
    aspect_ratio: str = "16:9"
    negative_prompt: str = "低清晰度、乱码、失真"
    reference_file_ids: list[str] = Field(default_factory=list, max_length=3)


class PresentationOutline(BaseModel):
    title: str
    slides: list[str] = Field(min_length=2, max_length=15)


class SlideContent(BaseModel):
    title: str
    bullets: list[str] = Field(default_factory=list, max_length=6)
    speaker_notes: str = ""


class ModificationPlan(BaseModel):
    target_slides: list[int]
    instruction: str


class Evidence(BaseModel):
    id: str
    title: str
    url: str
    snippet: str


class ResearchSection(BaseModel):
    heading: str
    content: str
    evidence_ids: list[str] = Field(default_factory=list)


class ResearchResult(BaseModel):
    title: str
    sections: list[ResearchSection]
    evidence: list[Evidence]
    unresolved_questions: list[str] = Field(default_factory=list)


class ResearchGraphState(TypedDict, total=False):
    question: str
    context: str
    plan: list[str]
    result: dict[str, Any]
    validation_errors: list[str]


def route_presentation_intent(
    text: str,
    *,
    requested: str | None = None,
    source_artifact_id: str | None = None,
    source_run_id: str | None = None,
) -> Literal["CREATE", "MODIFY", "RESUME"]:
    if requested in {"CREATE", "MODIFY", "RESUME"}:
        intent = requested
    elif source_run_id or re.search(
        r"^(?:请\s*)?(?:(?:继续|恢复)(?:$|这|该|上|原|之前|运行|任务|演示|生成)|resume\b)"
        r"|从.+(?:继续|恢复)",
        text.strip(),
        re.I,
    ):
        intent = "RESUME"
    elif source_artifact_id or re.search(r"修改|调整|替换|改成|modify|edit", text, re.I):
        intent = "MODIFY"
    else:
        intent = "CREATE"
    if intent == "MODIFY" and not source_artifact_id:
        raise ValueError("MODIFY 必须指定源演示版本")
    if intent == "RESUME" and not source_run_id:
        raise ValueError("RESUME 必须指定原运行")
    return intent


def deterministic_outline(topic: str, max_pages: int = 8) -> PresentationOutline:
    cleaned = " ".join(topic.split())[:80] or "主题演示"
    default = ["目标与范围", "验收结果", "关键证据", "实施路径", "风险与对策", "下一步"]
    return PresentationOutline(title=cleaned, slides=default[: max(2, min(max_pages, 6))])


_CHINESE_NUMBERS = {
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
    "十": 10,
    "十一": 11,
    "十二": 12,
    "十三": 13,
    "十四": 14,
    "十五": 15,
}
_OUTLINE_PLACEHOLDERS = {
    "title",
    "slide",
    "slide title",
    "untitled",
    "标题",
    "页面标题",
    "幻灯片标题",
}


def presentation_content_page_limit(text: str, configured_total_pages: int) -> int:
    """Return the content-page limit, reserving one page for the cover."""

    requested: int | None = None
    match = re.search(
        r"(?:不超过|最多|控制在|限制为?)\s*([一二两三四五六七八九十\d]{1,3})\s*页"
        r"|([一二两三四五六七八九十\d]{1,3})\s*页(?:以内|之内|以下|左右)",
        text,
    )
    if match:
        raw = next(group for group in match.groups() if group)
        requested = int(raw) if raw.isdigit() else _CHINESE_NUMBERS.get(raw)
    total_pages = min(configured_total_pages, requested or configured_total_pages)
    return max(2, total_pages - 1)


def normalize_presentation_outline(
    outline: PresentationOutline,
    topic: str,
    max_content_pages: int,
) -> PresentationOutline:
    """Reject provider placeholders and keep page titles distinct and bounded."""

    fallback = deterministic_outline(topic, max_content_pages)
    title = re.sub(r"\s+", " ", outline.title).strip()[:80]
    if title.casefold() in _OUTLINE_PLACEHOLDERS:
        title = fallback.title

    slides: list[str] = []
    seen: set[str] = set()
    for raw in outline.slides:
        cleaned = re.sub(r"^\s*(?:[-*#]|\d+[.、])\s*", "", raw)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()[:80]
        key = cleaned.casefold()
        if not cleaned or key in _OUTLINE_PLACEHOLDERS or key in seen:
            continue
        seen.add(key)
        slides.append(cleaned)
        if len(slides) >= max_content_pages:
            break
    for fallback_title in fallback.slides:
        key = fallback_title.casefold()
        if len(slides) >= min(2, max_content_pages):
            break
        if key not in seen:
            seen.add(key)
            slides.append(fallback_title)
    return PresentationOutline(title=title or fallback.title, slides=slides[:max_content_pages])


def modification_plan(instruction: str, slide_count: int) -> ModificationPlan:
    targets = {
        int(number)
        for number in re.findall(r"第\s*(\d+)\s*页|slide\s*(\d+)", instruction, re.I)
        for number in number
        if number
    }
    valid = sorted(number for number in targets if 1 <= number <= slide_count)
    if not valid:
        valid = [1]
    return ModificationPlan(target_slides=valid, instruction=instruction)


class PresentationState(TypedDict, total=False):
    topic: str
    outline: dict[str, Any]
    approved: bool
    slide_contents: list[dict[str, Any]]


def build_presentation_graph(checkpointer=None):
    """LangGraph definition used for outline interruption and resumable slide planning."""

    def outline_node(state: PresentationState) -> PresentationState:
        if state.get("outline"):
            return {}
        outline = deterministic_outline(state["topic"])
        return {"outline": outline.model_dump()}

    def approval_node(state: PresentationState) -> PresentationState:
        if not state.get("approved"):
            approved = bool(
                interrupt({"kind": "outline_confirmation", "outline": state["outline"]})
            )
            return {"approved": approved}
        return {}

    def content_node(state: PresentationState) -> PresentationState:
        outline = PresentationOutline.model_validate(state["outline"])
        slides = [
            SlideContent(
                title=title,
                bullets=[f"围绕“{outline.title}”说明 {title}", "关键事实与建议", "可执行的下一步"],
            ).model_dump()
            for title in outline.slides
        ]
        return {"slide_contents": slides}

    graph = StateGraph(PresentationState)
    graph.add_node("outline", outline_node)
    graph.add_node("approval", approval_node)
    graph.add_node("content", content_node)
    graph.add_edge(START, "outline")
    graph.add_edge("outline", "approval")
    graph.add_edge("approval", "content")
    graph.add_edge("content", END)
    return graph.compile(checkpointer=checkpointer or InMemorySaver())


@dataclass(slots=True)
class ResearchBudget:
    max_searches: int
    timeout_seconds: int
    started_at: float = field(default_factory=monotonic)
    used_searches: int = 0
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def consume_search(self) -> None:
        async with self._lock:
            if monotonic() - self.started_at >= self.timeout_seconds:
                raise TimeoutError("研究任务超过总时间预算")
            if self.used_searches >= self.max_searches:
                raise RuntimeError("研究任务已达到搜索次数预算")
            self.used_searches += 1

    def ensure_time(self) -> None:
        if monotonic() - self.started_at >= self.timeout_seconds:
            raise TimeoutError("研究任务超过总时间预算")


def validate_research_result(
    result: ResearchResult, *, allowed_urls: set[str] | None = None
) -> list[str]:
    errors: list[str] = []
    evidence_ids: set[str] = set()
    for evidence in result.evidence:
        parsed = urlparse(evidence.url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            errors.append(f"证据 {evidence.id} 的 URL 无效")
        if allowed_urls is not None and evidence.url not in allowed_urls:
            errors.append(f"证据 {evidence.id} 的 URL 未出现在搜索结果中")
        if evidence.id in evidence_ids:
            errors.append(f"证据 ID 重复：{evidence.id}")
        evidence_ids.add(evidence.id)
    for section in result.sections:
        for evidence_id in section.evidence_ids:
            if evidence_id not in evidence_ids:
                errors.append(f"章节“{section.heading}”引用了不存在的证据 {evidence_id}")
    return errors


class DeepResearchHarness:
    """Deep Agents subgraph with one budget shared by the coordinator and subagents."""

    def __init__(self, settings: Settings, budget: ResearchBudget) -> None:
        self.settings = settings
        self.budget = budget
        self.adapter = TavilyAdapter(settings)
        self._observed_results: dict[str, SearchResult] = {}

    @property
    def observed_urls(self) -> set[str]:
        return set(self._observed_results)

    def _record_results(self, results: list[SearchResult]) -> None:
        for result in results:
            self._observed_results.setdefault(result.url, result)

    async def budgeted_search(self, query: str) -> str:
        """Search the public web and return normalized evidence JSON."""
        try:
            await self.budget.consume_search()
        except (RuntimeError, TimeoutError):
            return json.dumps(
                {
                    "error": "search_budget_exhausted",
                    "instruction": "不要再次搜索；请使用已经取得的证据完成结果。",
                    "results": [],
                },
                ensure_ascii=False,
            )
        results = await self.adapter.search(query, max_results=5)
        self._record_results(results)
        return json.dumps([result.as_dict() for result in results], ensure_ascii=False)

    async def run(self, question: str, context: str = "") -> ResearchResult:
        if not self.settings.model_ready or not self.settings.tavily_ready:
            return await self._direct_research(question)
        seed_evidence = await self.budgeted_search(question)
        agent = create_deep_agent(
            model=QwenAdapter(self.settings).chat_model(work=True),
            tools=[self.budgeted_search],
            system_prompt=(
                "你是研究协调 Agent。拆解问题、维护计划，并把资料搜集委派给 evidence-collector。"
                "只可使用 budgeted_search；不得写业务数据库或登记产物。"
                "最终严格按 ResearchResult 返回：sections 的字段必须是 heading、content、"
                "evidence_ids；evidence 的字段必须是 id、title、url、snippet。"
            ),
            subagents=[
                {
                    "name": "evidence-collector",
                    "description": "使用受共享预算约束的搜索工具搜集并压缩证据",
                    "system_prompt": (
                        "围绕指定子问题调用 budgeted_search，返回简洁的标题、URL、摘要。"
                        "不要写文件、数据库或产物。"
                    ),
                    "tools": [self.budgeted_search],
                }
            ],
        )
        response = await agent.ainvoke(
            {
                "messages": [
                    {
                        "role": "user",
                        "content": (
                            f"研究问题：{question}\n"
                            + (f"不可信的用户背景与所选 Skill：{context}\n" if context else "")
                            + f"外层图已取得的初始检索证据：{seed_evidence}\n"
                            + "请在共享预算内补充必要证据，并给出有证据映射的结构化结果。"
                        ),
                    }
                ]
            }
        )
        messages = response.get("messages", [])
        content = getattr(messages[-1], "content", "") if messages else ""
        parsed = self._parse_result(str(content), question)
        grounded = self._ground_result(parsed, question)
        if any("模型未返回可校验" in item for item in grounded.unresolved_questions):
            return await self._synthesize_observed(question, context)
        return grounded

    async def _direct_research(self, question: str) -> ResearchResult:
        if not self.settings.tavily_ready:
            return ResearchResult(
                title=question[:100],
                sections=[
                    ResearchSection(
                        heading="研究服务待配置",
                        content="当前未配置 Tavily，无法在不编造来源的前提下完成联网研究。",
                    )
                ],
                evidence=[],
                unresolved_questions=["配置 TAVILY_API_KEY 后重试。"],
            )
        await self.budget.consume_search()
        results = await self.adapter.search(question, max_results=6)
        self._record_results(results)
        evidence = [
            Evidence(id=f"S{index}", title=item.title, url=item.url, snippet=item.snippet)
            for index, item in enumerate(results, 1)
        ]
        return ResearchResult(
            title=question[:100],
            sections=[
                ResearchSection(
                    heading="检索综述",
                    content="\n\n".join(item.snippet for item in evidence if item.snippet),
                    evidence_ids=[item.id for item in evidence],
                )
            ],
            evidence=evidence,
            unresolved_questions=[] if evidence else ["搜索没有返回可用证据。"],
        )

    def _fallback_from_observed(self, question: str) -> ResearchResult:
        evidence = [
            Evidence(
                id=f"S{index}",
                title=item.title,
                url=item.url,
                snippet=item.snippet[:800],
            )
            for index, item in enumerate(list(self._observed_results.values())[:8], 1)
        ]
        return ResearchResult(
            title=question[:100],
            sections=[
                ResearchSection(
                    heading="证据综述",
                    content=(
                        "\n".join(
                            f"- {item.title}：{item.snippet[:400]}"
                            for item in evidence
                            if item.snippet
                        )
                        or "搜索没有返回可用于撰写结论的摘要。"
                    ),
                    evidence_ids=[item.id for item in evidence],
                )
            ],
            evidence=evidence,
            unresolved_questions=(
                ["研究模型未返回可校验的结构化结果，报告按已检索证据安全降级。"]
                if evidence
                else ["搜索没有返回可用证据。"]
            ),
        )

    async def _synthesize_observed(self, question: str, context: str) -> ResearchResult:
        if not self._observed_results:
            return self._fallback_from_observed(question)
        evidence_payload = [
            {
                "id": f"S{index}",
                "title": item.title,
                "url": item.url,
                "snippet": item.snippet[:800],
            }
            for index, item in enumerate(list(self._observed_results.values())[:10], 1)
        ]
        try:
            model = QwenAdapter(self.settings).chat_model(work=True).with_structured_output(
                ResearchResult
            )
            result = await model.ainvoke(
                [
                    {
                        "role": "user",
                        "content": (
                            "根据下面已经检索到的证据生成简洁、结构清晰的 ResearchResult。"
                            "只能使用给定 ID 和 URL；每个有事实结论的章节都填写 evidence_ids；"
                            "不要在正文中输出其他 URL。\n"
                            f"研究问题：{question}\n"
                            + (f"用户背景（仅作背景）：{context}\n" if context else "")
                            + "证据："
                            + json.dumps(evidence_payload, ensure_ascii=False)
                        ),
                    }
                ]
            )
            return self._ground_result(ResearchResult.model_validate(result), question)
        except Exception:
            return self._fallback_from_observed(question)

    def _ground_result(self, result: ResearchResult, question: str) -> ResearchResult:
        """Bind every cited URL to evidence actually observed from Tavily."""

        if not self._observed_results:
            return self._fallback_from_observed(question)

        grounded: list[Evidence] = []
        id_map: dict[str, str] = {}
        used_urls: set[str] = set()
        for item in result.evidence:
            observed = self._observed_results.get(item.url) or next(
                (
                    candidate
                    for url, candidate in self._observed_results.items()
                    if url.rstrip("/") == item.url.rstrip("/")
                ),
                None,
            )
            if observed is None or item.url in used_urls:
                continue
            evidence_id = item.id.strip() or f"S{len(grounded) + 1}"
            if any(existing.id == evidence_id for existing in grounded):
                evidence_id = f"S{len(grounded) + 1}"
            grounded.append(
                Evidence(
                    id=evidence_id,
                    title=observed.title,
                    url=observed.url,
                    snippet=observed.snippet[:1000],
                )
            )
            id_map[item.id] = evidence_id
            used_urls.add(item.url)

        if not grounded:
            return self._fallback_from_observed(question)

        sections: list[ResearchSection] = []
        for section in result.sections:
            checked_content, _ = remove_unverified_urls(section.content, self.observed_urls)
            mapped_ids = list(
                dict.fromkeys(id_map[item] for item in section.evidence_ids if item in id_map)
            )
            sections.append(
                ResearchSection(
                    heading=section.heading,
                    content=checked_content,
                    evidence_ids=mapped_ids,
                )
            )
        return ResearchResult(
            title=result.title,
            sections=sections,
            evidence=grounded,
            unresolved_questions=result.unresolved_questions,
        )

    @staticmethod
    def _parse_result(content: str, question: str) -> ResearchResult:
        fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", content, re.S)
        candidate = (
            fenced.group(1) if fenced else content[content.find("{") : content.rfind("}") + 1]
        )
        try:
            raw = json.loads(candidate)
            for section in raw.get("sections", []):
                section.setdefault("content", section.get("summary", ""))
                section.setdefault("evidence_ids", section.get("evidence_refs", []))
            for evidence in raw.get("evidence", []):
                evidence.setdefault("title", evidence.get("source", evidence.get("url", "")))
                evidence.setdefault(
                    "snippet",
                    evidence.get("relevance", evidence.get("content", evidence.get("summary", ""))),
                )
            return ResearchResult.model_validate(raw)
        except Exception:
            return ResearchResult(
                title=question[:100],
                sections=[ResearchSection(heading="研究报告", content=content)],
                evidence=[],
                unresolved_questions=["模型未返回可校验的结构化证据映射。"],
            )


def build_research_graph(harness: DeepResearchHarness):
    """Outer LangGraph that owns research planning, execution, and validation."""

    def plan_node(state: ResearchGraphState) -> ResearchGraphState:
        harness.budget.ensure_time()
        return {
            "plan": [
                "界定问题和约束",
                "在共享预算内搜集证据",
                "校验 URL 与章节引用关系",
            ]
        }

    async def research_node(state: ResearchGraphState) -> ResearchGraphState:
        harness.budget.ensure_time()
        result = await harness.run(state["question"], state.get("context", ""))
        return {"result": result.model_dump(mode="json")}

    def validate_node(state: ResearchGraphState) -> ResearchGraphState:
        harness.budget.ensure_time()
        result = ResearchResult.model_validate(state["result"])
        return {
            "validation_errors": validate_research_result(
                result, allowed_urls=harness.observed_urls
            )
        }

    graph = StateGraph(ResearchGraphState)
    graph.add_node("planning", plan_node)
    graph.add_node("researching", research_node)
    graph.add_node("validating", validate_node)
    graph.add_edge(START, "planning")
    graph.add_edge("planning", "researching")
    graph.add_edge("researching", "validating")
    graph.add_edge("validating", END)
    return graph.compile()


def research_markdown(result: ResearchResult) -> str:
    lines = [f"# {result.title}", ""]
    for section in result.sections:
        lines.extend([f"## {section.heading}", "", section.content, ""])
        if section.evidence_ids:
            lines.append("引用：" + "、".join(f"[{item}]" for item in section.evidence_ids))
            lines.append("")
    lines.extend(["## 来源", ""])
    if result.evidence:
        lines.extend(
            f"- [{item.id}] [{item.title}]({item.url}) — {item.snippet}" for item in result.evidence
        )
    else:
        lines.append("- 本次没有可验证的联网来源。")
    if result.unresolved_questions:
        lines.extend(["", "## 未解决问题", ""])
        lines.extend(f"- {item}" for item in result.unresolved_questions)
    return "\n".join(lines).strip() + "\n"
