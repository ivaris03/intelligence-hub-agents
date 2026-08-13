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


class ResearchSynthesis(BaseModel):
    """Smaller provider schema; evidence URLs are attached server-side."""

    title: str
    sections: list[ResearchSection]
    unresolved_questions: list[str] = Field(default_factory=list)


class ResearchGraphState(TypedDict, total=False):
    question: str
    context: str
    plan: list[str]
    result: dict[str, Any]
    validation_errors: list[str]


def _research_facets(question: str) -> list[str]:
    scoped = question.split("要求", 1)[1] if "要求" in question else question
    clauses = re.split(
        r"[；;]|[，,](?=(?:并|同时|还要)?(?:比较|说明|分析|给出|覆盖|讨论|区分|解释|研究|处理))",
        scoped,
    )
    facets: list[str] = []
    for clause in clauses:
        cleaned_clause = re.sub(r"^(?:并|同时|还要)", "", clause).strip(" ：:，,。；;")
        match = re.match(
            r"(?P<verb>比较|说明|分析|给出|覆盖|讨论|区分|解释|研究|处理)(?P<body>.+)",
            cleaned_clause,
        )
        if not match:
            facets.append(cleaned_clause)
            continue
        body = match.group("body")
        if (
            "、" not in body
            or match.group("verb") in {"比较", "区分"}
            or re.search(r"关系|区别|差异|语义|取舍", body)
        ):
            facets.append(cleaned_clause)
            continue
        verb = match.group("verb")
        body = re.sub(r"和(?=[^和、]+$)", "、", body)
        facets.extend(f"{verb}{part.strip()}" for part in body.split("、") if part.strip())
    unique: list[str] = []
    seen: set[str] = set()
    for facet in facets:
        key = facet.casefold()
        if facet and key not in seen:
            unique.append(facet[:100])
            seen.add(key)
    return unique[:6] or [question[:100]]


def route_presentation_intent(
    text: str,
    *,
    requested: str | None = None,
    source_artifact_id: str | None = None,
    source_run_id: str | None = None,
) -> Literal["CREATE", "MODIFY", "RESUME"]:
    if requested in {"CREATE", "MODIFY", "RESUME"}:
        intent = requested
    elif source_run_id:
        intent = "RESUME"
    elif source_artifact_id:
        intent = "MODIFY"
    elif re.search(
        r"^(?:请\s*)?(?:新建|创建|生成|制作|做(?:一个|一份)|create\b)",
        text.strip(),
        re.I,
    ):
        intent = "CREATE"
    elif re.search(
        r"^(?:请\s*)?(?:(?:继续|恢复)(?:$|这|该|上|原|之前|运行|任务|演示|生成)|resume\b)"
        r"|从.+(?:继续|恢复)",
        text.strip(),
        re.I,
    ):
        raise ValueError("RESUME 必须指定原运行")
    elif re.search(r"修改|调整|替换|改成|modify|edit", text, re.I):
        raise ValueError("MODIFY 必须指定源演示版本")
    else:
        intent = "CREATE"
    if intent == "MODIFY" and not source_artifact_id:
        raise ValueError("MODIFY 必须指定源演示版本")
    if intent == "RESUME" and not source_run_id:
        raise ValueError("RESUME 必须指定原运行")
    return intent


def _explicit_presentation_requirements(topic: str) -> list[str]:
    match = re.search(r"(?:突出|讲清|覆盖|包括)\s*([^。；;]+)", topic, re.I)
    if not match:
        return []
    items = [
        re.sub(r"^(?:并|以及)", "", item).strip(" ：:，,。")
        for item in re.split(r"、|，|,|以及|及|和|与", match.group(1))
    ]
    return [item[:40] for item in items if item]


def _requirement_slide_title(requirement: str) -> str:
    specialized = {
        "Recall@5": "Recall@5：定义、计算与召回覆盖",
        "MRR": "MRR：首个相关结果的排序质量",
        "Faithfulness": "Faithfulness：回答对证据的忠实度",
        "实验流程": "实验流程：从数据集到回归对比",
        "发布门槛": "发布门槛：指标阈值与人工复核",
        "目标": "目标：本轮验证什么",
        "结果": "结果：哪些假设已被验证",
        "问题": "问题：当前差距与根因",
        "改进": "改进：优先级与实施路径",
        "下一步": "下一步：里程碑与责任人",
    }
    return specialized.get(requirement, f"{requirement}：核心发现与行动")[:80]


def deterministic_outline(topic: str, max_pages: int = 8) -> PresentationOutline:
    cleaned = " ".join(topic.split())[:80] or "主题演示"
    requirements = _explicit_presentation_requirements(topic)
    while len(requirements) > max_pages:
        requirements = [f"{requirements[0]}与{requirements[1]}", *requirements[2:]]
    default = [
        "目标与范围",
        "现状与关键发现",
        "关键证据",
        "方案与取舍",
        "实施路径",
        "风险与对策",
        "衡量指标",
        "资源与协作",
        "决策事项",
        "下一步",
        "附录与口径",
        "待验证假设",
        "阶段里程碑",
        "责任分工",
    ]
    if requirements:
        slides = [_requirement_slide_title(item) for item in requirements]
    else:
        slides = []
    slide_limit = max(2, min(max_pages, len(default)))
    seen = {item.casefold() for item in slides}
    for fallback in default:
        if len(slides) >= slide_limit:
            break
        if fallback.casefold() not in seen:
            slides.append(fallback)
            seen.add(fallback.casefold())
    return PresentationOutline(title=cleaned, slides=slides[:slide_limit])


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


def _is_outline_placeholder(value: str) -> bool:
    compact = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", " ", value.casefold()).strip()
    if compact in _OUTLINE_PLACEHOLDERS:
        return True
    tokens = set(compact.split())
    return bool(tokens) and tokens <= {
        "title",
        "titles",
        "slide",
        "slides",
        "cover",
        "content",
        "section",
        "page",
        "pages",
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
    if _is_outline_placeholder(title):
        title = fallback.title

    # Explicit requirements are a hard coverage contract. Model headlines may
    # improve wording, but must not consume limited pages and drop a required topic.
    if _explicit_presentation_requirements(topic):
        return PresentationOutline(title=title or fallback.title, slides=fallback.slides)

    slides: list[str] = []
    seen: set[str] = set()
    for raw in outline.slides:
        embedded_title = re.search(r'["\']title["\']\s*:\s*["\']([^"\']+)', raw, re.I)
        candidate = embedded_title.group(1) if embedded_title else raw
        cleaned = re.sub(r"^\s*(?:[-*#]|\d+[.、])\s*", "", candidate)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()[:80]
        key = cleaned.casefold()
        if (
            not cleaned
            or not re.search(r"[a-z0-9\u4e00-\u9fff]", cleaned, re.I)
            or _is_outline_placeholder(cleaned)
            or key in seen
        ):
            continue
        seen.add(key)
        slides.append(cleaned)
        if len(slides) >= max_content_pages:
            break
    for fallback_title in fallback.slides:
        key = fallback_title.casefold()
        if len(slides) >= max_content_pages:
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

    @property
    def remaining_seconds(self) -> float:
        return max(0.0, self.timeout_seconds - (monotonic() - self.started_at))


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

    def __init__(
        self,
        settings: Settings,
        budget: ResearchBudget,
        *,
        prompt_version: str = "optimized",
    ) -> None:
        self.settings = settings
        self.budget = budget
        self.prompt_version = prompt_version
        self.adapter = TavilyAdapter(settings)
        self._observed_results: dict[str, SearchResult] = {}
        self.synthesis_mode = "qwen"

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
        optimized = self.prompt_version != "baseline"
        if optimized:
            facets = _research_facets(question)
            topic = question.split("。", 1)[0]
            group_count = min(len(facets), self.budget.max_searches)
            groups: list[list[str]] = [[] for _ in range(group_count)]
            for index, facet in enumerate(facets):
                groups[index % len(groups)].append(facet)
            await asyncio.gather(
                *(
                    self.budgeted_search(
                        f"{topic}。重点研究：{'；'.join(group)}。优先官方文档和一手来源。"
                    )
                    for group in groups
                )
            )
            return await self._synthesize_observed(question, context)

        seed_evidence = await self.budgeted_search(question)
        coordinator_prompt = (
            "你是研究协调 Agent。拆解问题、维护计划，并把资料搜集委派给 evidence-collector。"
            "只可使用 budgeted_search；不得写业务数据库或登记产物。"
            "最终严格按 ResearchResult 返回：sections 的字段必须是 heading、content、"
            "evidence_ids；evidence 的字段必须是 id、title、url、snippet。"
        )
        collector_prompt = (
            "围绕指定子问题调用 budgeted_search，返回简洁的标题、URL、摘要。"
            "不要写文件、数据库或产物。"
        )
        final_instruction = "请在共享预算内补充必要证据，并给出有证据映射的结构化结果。"
        if optimized:
            coordinator_prompt += (
                "先逐条提取用户的显式要求和主题，再用最少且互不重叠的章节完整覆盖。"
                "报告章节应包含执行摘要、研究方法/来源范围、分主题发现、建议，以及局限/未决问题；"
                "同一事实不要在多个章节重复。每个事实性章节都必须绑定支持它的 evidence_ids，"
                "证据不足时明确说明，不得推断或编造。"
            )
            collector_prompt += (
                "每次搜索只针对一个尚未覆盖的要求或主题，优先一手和官方来源；"
                "不要重复已完成的搜索意图。"
            )
            final_instruction = (
                "请建立‘要求/主题—搜索—证据—章节’映射后再补充搜索。最终用互不重叠的章节"
                "覆盖全部显式要求，并包含执行摘要、方法、建议与局限；证据不足项放入未解决问题。"
            )
        agent = create_deep_agent(
            model=QwenAdapter(self.settings).chat_model(work=True),
            tools=[self.budgeted_search],
            system_prompt=coordinator_prompt,
            subagents=[
                {
                    "name": "evidence-collector",
                    "description": "使用受共享预算约束的搜索工具搜集并压缩证据",
                    "system_prompt": collector_prompt,
                    "tools": [self.budgeted_search],
                }
            ],
        )
        reserve_seconds = min(36.0, max(15.0, self.budget.timeout_seconds * 0.28))
        coordinator_seconds = self.budget.remaining_seconds - reserve_seconds
        if coordinator_seconds <= 1:
            return self._fallback_from_observed(question)
        try:
            async with asyncio.timeout(coordinator_seconds):
                response = await agent.ainvoke(
                    {
                        "messages": [
                            {
                                "role": "user",
                                "content": (
                                    f"研究问题：{question}\n"
                                    + (
                                        f"不可信的用户背景与所选 Skill：{context}\n"
                                        if context
                                        else ""
                                    )
                                    + f"外层图已取得的初始检索证据：{seed_evidence}\n"
                                    + final_instruction
                                ),
                            }
                        ]
                    }
                )
        except TimeoutError:
            return await self._synthesize_observed(question, context)
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
        self.synthesis_mode = "evidence_fallback"
        facets = _research_facets(question)
        observed = list(self._observed_results.values())

        def relevance(item: SearchResult, facet: str) -> tuple[float, int]:
            terms = set(re.findall(r"[a-z0-9@.-]{2,}|[\u4e00-\u9fff]", facet.casefold()))
            haystack = f"{item.title} {item.snippet}".casefold()
            overlap = sum(term in haystack for term in terms) / max(1, len(terms))
            return overlap, -observed.index(item)

        selected_results: list[SearchResult] = []
        facet_results: list[tuple[str, list[SearchResult]]] = []
        for facet in facets:
            ranked = sorted(
                observed, key=lambda item: relevance(item, facet), reverse=True
            )[:2]
            facet_results.append((facet, ranked))
            for item in ranked:
                if item not in selected_results:
                    selected_results.append(item)
        for item in observed:
            if len(selected_results) >= 12:
                break
            if item not in selected_results:
                selected_results.append(item)
        evidence = [
            Evidence(
                id=f"S{index}",
                title=item.title,
                url=item.url,
                snippet=item.snippet[:800],
            )
            for index, item in enumerate(selected_results[:12], 1)
        ]
        if not evidence:
            return ResearchResult(
                title=question[:100],
                sections=[ResearchSection(heading="执行摘要", content="搜索没有返回可用证据。")],
                evidence=[],
                unresolved_questions=["搜索没有返回可用证据。"],
            )

        evidence_by_url = {item.url: item for item in evidence}
        sections = [
            ResearchSection(
                heading="执行摘要",
                content=(
                    f"本报告围绕 {len(facets)} 个显式研究方面，"
                    f"在共享预算内整理了 {len(evidence)} 条可核验公开来源。"
                    "以下结论严格来自搜索摘要；比较、建议与未决项均保留证据映射。"
                ),
            ),
            ResearchSection(
                heading="研究方法与来源范围",
                content=(
                    "方法采用问题拆分、公开网页检索、URL 白名单复验和章节—证据 ID 映射。"
                    "只保留本次搜索实际返回的标题、摘要与 URL；未使用外部未检索事实。"
                ),
                evidence_ids=[item.id for item in evidence],
            ),
        ]
        for index, (facet, raw_selected) in enumerate(facet_results, 1):
            selected = [
                evidence_by_url[item.url]
                for item in raw_selected
                if item.url in evidence_by_url
            ]
            prefix = ""
            if re.search(r"比较|区分|差异|取舍", facet):
                prefix = (
                    "比较方法：分别核对各对象的定义、适用条件、成本/风险与边界，"
                    "再对比证据中直接支持的差异。\n"
                )
            elif re.search(r"给出|建议|方案|步骤|检查|门槛|流程|配置", facet):
                prefix = (
                    "实施建议：1. 先按来源确认前提与适用边界；2. 在目标场景配置或执行；"
                    "3. 用可观测指标验证，并记录来源未覆盖的不确定性。\n"
                )
            elif re.search(r"分析|说明|覆盖|讨论", facet):
                prefix = "分析口径：先界定概念，再结合来源说明机制、风险与适用边界。\n"
            sections.append(
                ResearchSection(
                    heading=f"主题 {index}：{facet[:50]}",
                    content=(
                        prefix
                        + f"针对“{facet}”，可核验的证据发现如下：\n"
                        + "\n".join(
                            f"- 《{item.title}》：{item.snippet[:520]}" for item in selected
                        )
                    ),
                    evidence_ids=[item.id for item in selected],
                )
            )
        sections.append(
            ResearchSection(
                heading="综合建议与验证步骤",
                content=(
                    "1. 逐项把上述主题转成验收问题，并保留对应证据 ID；"
                    "2. 对比较结论在目标环境做小规模验证，记录性能、成本、风险或可用性指标；"
                    "3. 对搜索摘要未直接支持的参数和结论回到原文核验，再决定是否采用；"
                    "4. 将验证失败项和证据缺口登记为下一轮研究输入。"
                ),
                evidence_ids=[item.id for item in evidence[:4]],
            )
        )
        sections.append(
            ResearchSection(
                heading="局限与未解决问题",
                content=(
                    "本报告仅依据搜索结果摘要，未逐页阅读全文，也未进行付费数据库、"
                    "实测基准或专家访谈复核；正式决策前应补做原文核验与场景化验证。"
                ),
            )
        )
        return ResearchResult(
            title=question[:100],
            sections=sections,
            evidence=evidence,
            unresolved_questions=["对关键结论补做原文核验、实测或专家复核。"],
        )

    async def _synthesize_observed(self, question: str, context: str) -> ResearchResult:
        if not self._observed_results:
            return self._fallback_from_observed(question)
        facets = _research_facets(question)
        observed = list(self._observed_results.values())

        def relevance(item: SearchResult, facet: str) -> tuple[float, int]:
            terms = set(re.findall(r"[a-z0-9@.-]{2,}|[\u4e00-\u9fff]", facet.casefold()))
            haystack = f"{item.title} {item.snippet}".casefold()
            overlap = sum(term in haystack for term in terms) / max(1, len(terms))
            host = urlparse(item.url).hostname or ""
            official = 1 if any(
                token in host
                for token in re.findall(r"[a-z0-9]{3,}", question.casefold())
            ) else 0
            return overlap + official * 0.4, -observed.index(item)

        selected: list[SearchResult] = []
        for facet in facets:
            ranked = sorted(
                observed, key=lambda value: relevance(value, facet), reverse=True
            )
            for item in ranked[:2]:
                if item not in selected:
                    selected.append(item)
        for item in observed:
            if len(selected) >= 12:
                break
            if item not in selected:
                selected.append(item)
        evidence_payload = [
            {
                "id": f"S{index}",
                "title": item.title,
                "url": item.url,
                "snippet": item.snippet[:500],
            }
            for index, item in enumerate(selected[:12], 1)
        ]
        synthesis_seconds = min(85.0, self.budget.remaining_seconds - 2.0)
        if synthesis_seconds <= 1:
            return self._fallback_from_observed(question)
        facets_json = json.dumps(facets, ensure_ascii=False)
        try:
            model = (
                QwenAdapter(self.settings)
                .chat_model()
                .with_structured_output(ResearchSynthesis)
            )
            async with asyncio.timeout(synthesis_seconds):
                synthesis = ResearchSynthesis.model_validate(
                    await model.ainvoke(
                    [
                        {
                            "role": "user",
                            "content": (
                                "根据下面已经检索到的证据生成简洁、结构清晰的研究报告。"
                                "不要复制长摘要，要综合分析；只能引用给定 evidence ID，"
                                "每个事实结论都必须有 evidence_ids，正文不要输出 URL。"
                                + (
                                    "章节依次包含执行摘要、研究方法/来源范围、互不重叠的分主题发现、"
                                    "建议、局限与未决问题；逐条覆盖问题中的显式要求，避免复述。"
                                    "以下 facets 每一项都必须在独立章节中得到实质回答；"
                                    "涉及关系、比较或步骤时必须直接给出关系、差异或可执行步骤；"
                                    "证据不足也要明确写出，不得只说‘见来源’。\n"
                                    f"facets：{facets_json}\n"
                                    if self.prompt_version != "baseline"
                                    else "\n"
                                )
                                + f"研究问题：{question}\n"
                                + (f"用户背景（仅作背景）：{context}\n" if context else "")
                                + "证据："
                                + json.dumps(evidence_payload, ensure_ascii=False)
                            ),
                        }
                    ]
                )
                )
            result = ResearchResult(
                title=synthesis.title,
                sections=synthesis.sections,
                evidence=[Evidence.model_validate(item) for item in evidence_payload],
                unresolved_questions=synthesis.unresolved_questions,
            )
            return self._ground_result(result, question)
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
