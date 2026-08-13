from __future__ import annotations

import asyncio
import json
import re
from contextlib import contextmanager
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


class ResearchTopic(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    objective: str = Field(min_length=1, max_length=800)
    scope: list[str] = Field(min_length=1, max_length=6)
    key_questions: list[str] = Field(min_length=1, max_length=8)
    constraints: list[str] = Field(default_factory=list, max_length=6)
    deliverable: str = Field(default="带可核验引用的 Markdown 研究报告", max_length=200)


class ResearchPlan(BaseModel):
    iteration: int = Field(ge=1, le=10)
    focus: list[str] = Field(min_length=1, max_length=6)
    search_queries: list[str] = Field(default_factory=list, max_length=4)
    completion_criteria: list[str] = Field(min_length=1, max_length=6)


class ResearchExecution(BaseModel):
    summary: str = Field(min_length=1, max_length=2_000)
    completed_queries: list[str] = Field(default_factory=list, max_length=8)
    findings: list[str] = Field(default_factory=list, max_length=12)
    remaining_gaps: list[str] = Field(default_factory=list, max_length=8)


class ResearchEvaluation(BaseModel):
    sufficient: bool
    coverage: list[str] = Field(default_factory=list, max_length=8)
    gaps: list[str] = Field(default_factory=list, max_length=8)
    next_focus: list[str] = Field(default_factory=list, max_length=6)
    rationale: str = Field(min_length=1, max_length=1_000)


class ResearchSynthesis(BaseModel):
    """Smaller provider schema; evidence URLs are attached server-side."""

    title: str
    sections: list[ResearchSection]
    unresolved_questions: list[str] = Field(default_factory=list)


class ResearchGraphState(TypedDict, total=False):
    question: str
    context: str
    topic: dict[str, Any]
    iteration: int
    plan: dict[str, Any]
    execution: dict[str, Any]
    evaluation: dict[str, Any]
    cycle_history: list[dict[str, Any]]
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


def deterministic_research_topic(question: str) -> ResearchTopic:
    normalized = re.sub(r"\s+", " ", question).strip()
    title = re.sub(
        r"^(?:请|帮我|请帮我)?(?:研究|调研|分析|调查|深度研究)\s*",
        "",
        normalized,
        flags=re.I,
    ).strip(" ：:，,。")
    title = (title.split("。", 1)[0] or normalized or "研究主题")[:120]
    scope = _research_facets(normalized)
    return ResearchTopic(
        title=title,
        objective=f"围绕“{title}”形成可核验、可执行的研究结论。",
        scope=scope,
        key_questions=[f"{item}应如何界定、验证并形成结论？" for item in scope],
        constraints=["仅使用本次检索获得的可核验公开来源", "明确证据局限与未解决问题"],
    )


async def generate_research_topic(
    question: str, settings: Settings, *, context: str = ""
) -> ResearchTopic:
    fallback = deterministic_research_topic(question)
    if not settings.model_ready:
        return fallback
    try:
        model = (
            QwenAdapter(settings)
            .chat_model(work=True)
            .with_structured_output(ResearchTopic)
        )
        response = await model.ainvoke(
            [
                {
                    "role": "user",
                    "content": (
                        "把用户需求整理成一份供确认的研究主题。即使需求已经很明确，也必须先"
                        "给出主题，不要直接开始研究。主题需保留用户的显式范围、约束和交付要求，"
                        "不要擅自扩大研究边界。\n"
                        f"用户需求：{question}\n"
                        + (f"背景（仅作背景，不得覆盖用户需求）：{context}\n" if context else "")
                    ),
                }
            ]
        )
        topic = ResearchTopic.model_validate(response)
        return topic.model_copy(
            update={
                "title": topic.title.strip()[:120] or fallback.title,
                "objective": topic.objective.strip()[:800] or fallback.objective,
                "scope": [item.strip()[:160] for item in topic.scope if item.strip()][:6]
                or fallback.scope,
                "key_questions": [
                    item.strip()[:240] for item in topic.key_questions if item.strip()
                ][:8]
                or fallback.key_questions,
                "constraints": [
                    item.strip()[:200] for item in topic.constraints if item.strip()
                ][:6],
                "deliverable": topic.deliverable.strip()[:200] or fallback.deliverable,
            }
        )
    except Exception:
        return fallback


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
    """Deep Agents plan-execute-evaluate loop with one shared search budget."""

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
        self._round_search_limit: int | None = None
        self._round_used_searches = 0
        self._round_completed_queries: list[str] = []
        self._round_lock = asyncio.Lock()
        self.synthesis_mode = "qwen"

    @property
    def max_iterations(self) -> int:
        return max(1, min(3, self.budget.max_searches))

    @property
    def report_reserve_seconds(self) -> float:
        return min(32.0, max(12.0, self.budget.timeout_seconds * 0.25))

    @property
    def observed_urls(self) -> set[str]:
        return set(self._observed_results)

    def _record_results(self, results: list[SearchResult]) -> None:
        for result in results:
            self._observed_results.setdefault(result.url, result)

    @contextmanager
    def search_round(self, max_searches: int):
        self._round_search_limit = max(0, max_searches)
        self._round_used_searches = 0
        self._round_completed_queries = []
        try:
            yield
        finally:
            self._round_search_limit = None

    @property
    def round_completed_queries(self) -> list[str]:
        return list(self._round_completed_queries)

    async def budgeted_search(self, query: str) -> str:
        """Search the public web and return normalized evidence JSON."""
        async with self._round_lock:
            if (
                self._round_search_limit is not None
                and self._round_used_searches >= self._round_search_limit
            ):
                return json.dumps(
                    {
                        "error": "round_search_budget_exhausted",
                        "instruction": "本轮搜索额度已用尽；请进入评估，不要再次搜索。",
                        "results": [],
                    },
                    ensure_ascii=False,
                )
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
            if self._round_search_limit is not None:
                self._round_used_searches += 1
        results = await self.adapter.search(query, max_results=5)
        self._record_results(results)
        if self._round_search_limit is not None:
            async with self._round_lock:
                self._round_completed_queries.append(query)
        return json.dumps([result.as_dict() for result in results], ensure_ascii=False)

    def should_continue(self, state: ResearchGraphState) -> bool:
        evaluation = ResearchEvaluation.model_validate(state["evaluation"])
        return (
            self.settings.tavily_ready
            and not evaluation.sufficient
            and int(state.get("iteration", 0)) < self.max_iterations
            and self.budget.used_searches < self.budget.max_searches
            and self.budget.remaining_seconds > self.report_reserve_seconds
        )

    async def plan(
        self,
        topic: ResearchTopic,
        *,
        iteration: int,
        context: str = "",
        previous_evaluation: ResearchEvaluation | None = None,
    ) -> ResearchPlan:
        remaining = self.budget.max_searches - self.budget.used_searches
        round_search_limit = min(2, max(0, remaining))
        focus = (
            previous_evaluation.next_focus
            if previous_evaluation and previous_evaluation.next_focus
            else topic.scope
        )
        focus = focus[:6]
        fallback = ResearchPlan(
            iteration=iteration,
            focus=focus,
            search_queries=[
                f"{topic.title} {item} 官方 文档 一手来源"
                for item in focus[:round_search_limit]
            ],
            completion_criteria=[
                "每个研究重点都有真实来源或被明确标记为证据不足",
                "结论可以映射到本次检索获得的证据",
            ],
        )
        if (
            not self.settings.model_ready
            or self.budget.remaining_seconds <= self.report_reserve_seconds
        ):
            return fallback
        evidence_index = [
            {"title": item.title, "url": item.url, "snippet": item.snippet[:240]}
            for item in self._observed_results.values()
        ]
        try:
            agent = create_deep_agent(
                model=QwenAdapter(self.settings).chat_model(work=True),
                tools=[],
                system_prompt=(
                    "你是研究循环的计划 Agent。根据已确认的研究主题、上一轮评估和已有证据，"
                    "制定本轮最小且不重复的研究计划。不得搜索、写业务数据库或登记产物。"
                    "搜索查询必须优先官方资料和一手来源，并受剩余搜索次数约束。"
                ),
                response_format=ResearchPlan,
            )
            async with asyncio.timeout(
                min(24.0, self.budget.remaining_seconds - self.report_reserve_seconds)
            ):
                response = await agent.ainvoke(
                    {
                        "messages": [
                            {
                                "role": "user",
                                "content": (
                                    f"本轮：{iteration}\n剩余搜索次数：{remaining}\n"
                                    f"本轮最多搜索次数：{round_search_limit}\n"
                                    f"确认主题：{topic.model_dump_json()}\n"
                                    + (
                                        "上一轮评估："
                                        f"{previous_evaluation.model_dump_json()}\n"
                                        if previous_evaluation
                                        else ""
                                    )
                                    + (f"背景（仅作背景）：{context}\n" if context else "")
                                    + "已有证据索引："
                                    + json.dumps(evidence_index, ensure_ascii=False)
                                ),
                            }
                        ]
                    }
                )
            plan = ResearchPlan.model_validate(response.get("structured_response"))
            search_queries = plan.search_queries[:round_search_limit] or fallback.search_queries
            return plan.model_copy(
                update={
                    "iteration": iteration,
                    "focus": plan.focus[:6] or fallback.focus,
                    "search_queries": search_queries,
                    "completion_criteria": plan.completion_criteria[:6]
                    or fallback.completion_criteria,
                }
            )
        except Exception:
            return fallback

    async def execute(
        self,
        topic: ResearchTopic,
        plan: ResearchPlan,
        *,
        context: str = "",
    ) -> ResearchExecution:
        if not self.settings.tavily_ready:
            return ResearchExecution(
                summary="当前未配置 Tavily，执行阶段无法取得联网证据。",
                remaining_gaps=plan.focus,
            )
        round_search_limit = min(
            2,
            len(plan.search_queries),
            self.budget.max_searches - self.budget.used_searches,
        )
        with self.search_round(round_search_limit):
            return await self._execute_round(topic, plan, context=context)

    async def _execute_round(
        self,
        topic: ResearchTopic,
        plan: ResearchPlan,
        *,
        context: str = "",
    ) -> ResearchExecution:
        before_urls = set(self._observed_results)
        fallback = ResearchExecution(
            summary=f"围绕 {len(plan.focus)} 个研究重点执行检索。",
            completed_queries=plan.search_queries,
            remaining_gaps=plan.focus,
        )
        if not self.settings.model_ready:
            await asyncio.gather(*(self.budgeted_search(query) for query in plan.search_queries))
            new_results = [
                item for url, item in self._observed_results.items() if url not in before_urls
            ]
            return fallback.model_copy(
                update={
                    "summary": (
                        f"完成 {len(plan.search_queries)} 个查询，"
                        f"取得 {len(new_results)} 条新证据。"
                    ),
                    "completed_queries": self.round_completed_queries,
                    "findings": [
                        f"{item.title}：{item.snippet[:300]}" for item in new_results[:12]
                    ],
                    "remaining_gaps": [] if new_results else plan.focus,
                }
            )
        collector_prompt = (
            "只围绕被委派的子问题调用 budgeted_search，优先官方文档和一手来源。"
            "返回简洁的来源发现与仍缺失的信息；不得写业务数据库或登记产物。"
        )
        try:
            agent = create_deep_agent(
                model=QwenAdapter(self.settings).chat_model(work=True),
                tools=[self.budgeted_search],
                system_prompt=(
                    "你是研究循环的执行 Agent。严格按本轮计划调用 budgeted_search，必要时将"
                    "互不重叠的子问题委派给 evidence-collector。所有主 Agent 和子 Agent 共享"
                    "同一搜索与总时长预算。只能总结实际取得的搜索结果，不得编造来源、写业务"
                    "数据库或登记产物。"
                ),
                subagents=[
                    {
                        "name": "evidence-collector",
                        "description": "在共享预算内检索一个明确子问题并压缩证据",
                        "system_prompt": collector_prompt,
                        "tools": [self.budgeted_search],
                    }
                ],
                response_format=ResearchExecution,
            )
            execution_seconds = min(
                45.0, self.budget.remaining_seconds - self.report_reserve_seconds
            )
            if execution_seconds <= 1:
                return fallback
            async with asyncio.timeout(execution_seconds):
                response = await agent.ainvoke(
                    {
                        "messages": [
                            {
                                "role": "user",
                                "content": (
                                    f"确认主题：{topic.model_dump_json()}\n"
                                    f"本轮计划：{plan.model_dump_json()}\n"
                                    + (f"背景（仅作背景）：{context}\n" if context else "")
                                    + "请执行计划，并返回本轮真实完成的查询、发现和剩余缺口。"
                                ),
                            }
                        ]
                    }
                )
            execution = ResearchExecution.model_validate(response.get("structured_response"))
        except Exception:
            execution = fallback
        if set(self._observed_results) == before_urls and plan.search_queries:
            remaining = self.budget.max_searches - self.budget.used_searches
            await asyncio.gather(
                *(self.budgeted_search(query) for query in plan.search_queries[:remaining])
            )
        new_results = [
            item for url, item in self._observed_results.items() if url not in before_urls
        ]
        return execution.model_copy(
            update={
                "completed_queries": self.round_completed_queries,
                "findings": execution.findings
                or [f"{item.title}：{item.snippet[:300]}" for item in new_results[:12]],
            }
        )

    async def evaluate(
        self,
        topic: ResearchTopic,
        plan: ResearchPlan,
        execution: ResearchExecution,
        *,
        iteration: int,
    ) -> ResearchEvaluation:
        budget_exhausted = self.budget.used_searches >= self.budget.max_searches
        time_exhausted = self.budget.remaining_seconds <= self.report_reserve_seconds
        if not self.settings.tavily_ready:
            rationale = "搜索服务不可用，本轮保留证据缺口并进入汇总报告。"
        elif budget_exhausted:
            rationale = "共享搜索预算已用尽，本轮保留证据缺口并进入汇总报告。"
        elif time_exhausted:
            rationale = "研究时间接近上限，本轮保留证据缺口并进入汇总报告。"
        elif iteration >= self.max_iterations:
            rationale = "已达到最大循环轮数，本轮保留证据缺口并进入汇总报告。"
        elif self._observed_results and not execution.remaining_gaps:
            rationale = "关键问题已有证据覆盖，可以进入汇总报告。"
        else:
            rationale = "仍有证据缺口；若预算允许则进入下一轮。"
        fallback = ResearchEvaluation(
            sufficient=bool(self._observed_results) and not execution.remaining_gaps,
            coverage=plan.focus if self._observed_results else [],
            gaps=execution.remaining_gaps,
            next_focus=execution.remaining_gaps[:6],
            rationale=rationale,
        )
        if (
            not self.settings.model_ready
            or not self.settings.tavily_ready
            or budget_exhausted
            or time_exhausted
        ):
            return fallback
        try:
            agent = create_deep_agent(
                model=QwenAdapter(self.settings).chat_model(work=True),
                tools=[],
                system_prompt=(
                    "你是研究循环的评估 Agent。依据已确认主题、本轮计划、执行摘要和真实证据"
                    "索引判断覆盖度。不得搜索。只有关键问题已被证据覆盖时 sufficient 才为 true；"
                    "否则给出不重复且可在下一轮执行的缺口。不得写业务数据库或登记产物。"
                ),
                response_format=ResearchEvaluation,
            )
            async with asyncio.timeout(
                min(20.0, self.budget.remaining_seconds - self.report_reserve_seconds)
            ):
                response = await agent.ainvoke(
                    {
                        "messages": [
                            {
                                "role": "user",
                                "content": (
                                    f"本轮：{iteration}\n确认主题：{topic.model_dump_json()}\n"
                                    f"计划：{plan.model_dump_json()}\n"
                                    f"执行：{execution.model_dump_json()}\n"
                                    "真实证据索引："
                                    + json.dumps(
                                        [
                                            {"title": item.title, "snippet": item.snippet[:300]}
                                            for item in self._observed_results.values()
                                        ],
                                        ensure_ascii=False,
                                    )
                                ),
                            }
                        ]
                    }
                )
            evaluation = ResearchEvaluation.model_validate(response.get("structured_response"))
            if evaluation.gaps:
                evaluation = evaluation.model_copy(update={"sufficient": False})
            return evaluation
        except Exception:
            return fallback

    async def summarize(
        self,
        topic: ResearchTopic,
        *,
        question: str,
        context: str = "",
    ) -> ResearchResult:
        report_question = (
            f"{question}\n已确认研究主题：{topic.title}\n研究目标：{topic.objective}\n"
            f"研究范围：{'；'.join(topic.scope)}\n关键问题：{'；'.join(topic.key_questions)}"
        )
        if not self._observed_results:
            return await self._direct_research_without_search(topic)
        result = (
            await self._synthesize_observed(report_question, context)
            if self.settings.model_ready
            else self._fallback_from_observed(report_question)
        )
        return result.model_copy(update={"title": topic.title})

    async def run(
        self,
        question: str,
        context: str = "",
        topic: ResearchTopic | None = None,
    ) -> ResearchResult:
        graph = build_research_graph(self)
        state = await graph.ainvoke(
            {
                "question": question,
                "context": context,
                "topic": (topic or deterministic_research_topic(question)).model_dump(),
            }
        )
        return ResearchResult.model_validate(state["result"])

    async def _direct_research_without_search(self, topic: ResearchTopic) -> ResearchResult:
        if not self.settings.tavily_ready:
            return ResearchResult(
                title=topic.title,
                sections=[
                    ResearchSection(
                        heading="研究服务待配置",
                        content="当前未配置 Tavily，无法在不编造来源的前提下完成联网研究。",
                    )
                ],
                evidence=[],
                unresolved_questions=["配置 TAVILY_API_KEY 后重试。"],
            )
        return ResearchResult(
            title=topic.title,
            sections=[ResearchSection(heading="执行摘要", content="研究循环没有取得可用证据。")],
            evidence=[],
            unresolved_questions=["本轮检索未返回可用证据，请调整研究范围后重试。"],
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

def build_research_graph(harness: DeepResearchHarness):
    """Outer LangGraph owns the Deep Agents cycle, report synthesis, and validation."""

    async def plan_node(state: ResearchGraphState) -> ResearchGraphState:
        harness.budget.ensure_time()
        iteration = int(state.get("iteration", 0)) + 1
        topic = ResearchTopic.model_validate(
            state.get("topic") or deterministic_research_topic(state["question"])
        )
        previous = (
            ResearchEvaluation.model_validate(state["evaluation"])
            if state.get("evaluation")
            else None
        )
        plan = await harness.plan(
            topic,
            iteration=iteration,
            context=state.get("context", ""),
            previous_evaluation=previous,
        )
        return {
            "topic": topic.model_dump(mode="json"),
            "iteration": iteration,
            "plan": plan.model_dump(mode="json"),
        }

    async def execute_node(state: ResearchGraphState) -> ResearchGraphState:
        harness.budget.ensure_time()
        execution = await harness.execute(
            ResearchTopic.model_validate(state["topic"]),
            ResearchPlan.model_validate(state["plan"]),
            context=state.get("context", ""),
        )
        return {"execution": execution.model_dump(mode="json")}

    async def evaluate_node(state: ResearchGraphState) -> ResearchGraphState:
        harness.budget.ensure_time()
        evaluation = await harness.evaluate(
            ResearchTopic.model_validate(state["topic"]),
            ResearchPlan.model_validate(state["plan"]),
            ResearchExecution.model_validate(state["execution"]),
            iteration=int(state["iteration"]),
        )
        history = list(state.get("cycle_history", []))
        history.append(
            {
                "iteration": int(state["iteration"]),
                "plan": state["plan"],
                "execution": state["execution"],
                "evaluation": evaluation.model_dump(mode="json"),
                "searches_used": harness.budget.used_searches,
            }
        )
        return {
            "evaluation": evaluation.model_dump(mode="json"),
            "cycle_history": history,
        }

    async def summarize_node(state: ResearchGraphState) -> ResearchGraphState:
        result = await harness.summarize(
            ResearchTopic.model_validate(state["topic"]),
            question=state["question"],
            context=state.get("context", ""),
        )
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
    graph.add_node("executing", execute_node)
    graph.add_node("evaluating", evaluate_node)
    graph.add_node("summarizing", summarize_node)
    graph.add_node("validating", validate_node)
    graph.add_edge(START, "planning")
    graph.add_edge("planning", "executing")
    graph.add_edge("executing", "evaluating")
    graph.add_conditional_edges(
        "evaluating",
        lambda state: "planning" if harness.should_continue(state) else "summarizing",
        {"planning": "planning", "summarizing": "summarizing"},
    )
    graph.add_edge("summarizing", "validating")
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
