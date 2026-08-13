from __future__ import annotations

import json
import re
from collections.abc import Sequence
from urllib.parse import urlsplit

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from langsmith import schemas
from pydantic import BaseModel, Field

from app.core.config import Settings
from app.integrations.qwen import QwenAdapter


class FaithfulnessClaim(BaseModel):
    claim: str
    factual: bool
    supported: bool


class FaithfulnessGrade(BaseModel):
    claims: list[FaithfulnessClaim]
    explanation: str


class MCPSearchGrade(BaseModel):
    result_relevance_scores: list[float]
    covered_topic_ids: list[str]
    supported_citation_urls: list[str]
    explanation: str


class PresentationGrade(BaseModel):
    structure: int = Field(ge=1, le=5)
    content: int = Field(ge=1, le=5)
    layout: int = Field(ge=1, le=5)
    color: int = Field(ge=1, le=5)
    structure_reason: str
    content_reason: str
    layout_reason: str
    color_reason: str


class ResearchGrade(BaseModel):
    captured_requirement_ids: list[str]
    covered_topic_ids: list[str]
    redundant_section_pairs: list[list[str]]
    satisfied_checklist_ids: list[str]
    explanation: str


def _research_item_is_covered(text: str, sections: list[dict]) -> bool:
    """Conservative evidence-aware fallback for research coverage scoring."""

    evidence_sections = [section for section in sections if section.get("evidence_ids")]
    limitation_sections = [
        section
        for section in sections
        if re.search(r"局限|不确定|未解决", str(section.get("heading") or ""))
        and len(str(section.get("content") or "")) >= 20
    ]
    if re.search(r"证据", text) and re.search(r"局限|不确定", text):
        return bool(evidence_sections and limitation_sections)
    if re.search(r"(?:说明|明确|标明)?(?:局限|不确定)", text):
        return bool(limitation_sections)

    concept_text = re.sub(
        r"比较|说明|分析|给出|覆盖|讨论|区分|解释|研究|处理|明确|要求|分别|建议",
        " ",
        text,
    )
    expected_ascii = _ascii_terms(concept_text) - _GENERIC_ASCII_TERMS
    expected_bigrams = _chinese_bigrams(concept_text)
    requires_comparison = bool(re.search(r"比较|区分|差异|取舍", text))
    requires_action = bool(re.search(r"给出.*(?:建议|方案|步骤|检查单|门槛|流程|配置)", text))
    for section in sections:
        if not section.get("evidence_ids"):
            continue
        content = str(section.get("content") or "")
        body = content.split("\n", 1)[-1]
        if len(body) < 80 or re.search(r"(?:没有|缺少|不足|未找到).{0,12}(?:证据|资料|来源)", body):
            continue
        ascii_overlap = _score(
            len(expected_ascii & _ascii_terms(body)), len(expected_ascii)
        )
        body_bigrams = _chinese_bigrams(body)
        chinese_overlap = _score(
            len(expected_bigrams & body_bigrams), len(expected_bigrams)
        )
        lexical_match = (
            (bool(expected_ascii) and ascii_overlap >= 0.5)
            or (bool(expected_bigrams) and chinese_overlap >= 0.35)
        )
        if not lexical_match:
            continue
        if requires_comparison and not re.search(
            r"区别|不同|相比|相较|对比|而|优于|高于|低于|各自|分别|取舍|\bvs\.?\b|versus",
            body,
            re.I,
        ):
            continue
        if requires_action:
            action_hits = re.findall(
                r"建议|应当|应该|需要|需|可以|配置|检查|验证|步骤|行动|选择|使用|设置|先|再",
                body,
            )
            numbered_steps = re.findall(r"(?:^|\n)\s*(?:\d+[.、)]|[-*])", body)
            if len(action_hits) < 2 and len(numbered_steps) < 2:
                continue
        return True
    return False


def _fallback_research_grade(
    requirements: list[dict], topics: list[dict], checklist: list[dict], result: dict
) -> ResearchGrade:
    sections = result.get("sections") or []
    captured = [
        item["id"]
        for item in requirements
        if _research_item_is_covered(str(item["text"]), sections)
    ]
    covered = [
        item["id"]
        for item in topics
        if _research_item_is_covered(str(item["text"]), sections)
    ]
    evidence_sections = [
        section
        for section in sections
        if section.get("evidence_ids")
        and not re.search(r"方法|来源范围", str(section.get("heading") or ""))
    ]
    redundant: list[list[str]] = []
    for left_index, left in enumerate(evidence_sections):
        left_terms = _terms(str(left.get("content") or ""))
        for right in evidence_sections[left_index + 1 :]:
            right_terms = _terms(str(right.get("content") or ""))
            union = left_terms | right_terms
            similarity = len(left_terms & right_terms) / len(union) if union else 0.0
            if similarity >= 0.72:
                redundant.append(
                    [str(left.get("heading") or ""), str(right.get("heading") or "")]
                )
    headings = " ".join(str(section.get("heading") or "") for section in sections)
    evidence = result.get("evidence") or []
    satisfied: list[str] = []
    for item in checklist:
        text = str(item["text"])
        if "执行摘要" in text and "执行摘要" in headings:
            satisfied.append(item["id"])
        elif ("研究方法" in text or "来源范围" in text) and re.search(
            r"方法|来源范围", headings
        ):
            satisfied.append(item["id"])
        elif "分主题" in text and len(evidence_sections) >= 2:
            satisfied.append(item["id"])
        elif re.search(r"建议|局限|未解决", text) and re.search(
            r"建议|局限|未解决", headings
        ):
            satisfied.append(item["id"])
        elif "可核验来源" in text and any(item.get("url") for item in evidence):
            satisfied.append(item["id"])
    return ResearchGrade(
        captured_requirement_ids=captured,
        covered_topic_ids=covered,
        redundant_section_pairs=redundant,
        satisfied_checklist_ids=satisfied,
        explanation=(
            "Qwen judge 不可用；使用证据 ID、正文词项覆盖、章节结构和内容相似度的"
            "保守确定性评分。"
        ),
    )


def _score(found: int, total: int) -> float:
    return found / total if total else 1.0


def _terms(text: str) -> set[str]:
    lower = text.casefold()
    terms = set(re.findall(r"[a-z0-9_@.-]{2,}|[\u4e00-\u9fff]", lower))
    chinese = "".join(re.findall(r"[\u4e00-\u9fff]", lower))
    terms.update(chinese[index : index + 2] for index in range(max(0, len(chinese) - 1)))
    return terms


_GENERIC_ASCII_TERMS = {
    "api",
    "client",
    "docs",
    "documentation",
    "official",
    "python",
    "sdk",
}


def _ascii_terms(text: str) -> set[str]:
    terms: set[str] = set()
    for token in re.findall(r"[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)*", text.casefold()):
        terms.add(token)
        terms.update(part for part in token.split(".") if len(part) >= 3)
    return terms


def _chinese_bigrams(text: str) -> set[str]:
    chinese = "".join(re.findall(r"[\u4e00-\u9fff]", text))
    return {chinese[index : index + 2] for index in range(max(0, len(chinese) - 1))}


def _topic_is_covered(topic_text: str, corpus: str) -> bool:
    topic_ascii = _ascii_terms(topic_text) - _GENERIC_ASCII_TERMS
    corpus_ascii = _ascii_terms(corpus)
    if topic_ascii & corpus_ascii:
        return True
    topic_bigrams = _chinese_bigrams(topic_text)
    corpus_bigrams = _chinese_bigrams(corpus)
    return bool(topic_bigrams) and _score(
        len(topic_bigrams & corpus_bigrams), len(topic_bigrams)
    ) >= 0.25


def _fallback_search_relevance(query: str, result: dict, topics: list[dict]) -> float:
    result_text = f"{result.get('title', '')} {result.get('snippet', '')}"
    query_ascii = _ascii_terms(query) - _GENERIC_ASCII_TERMS
    result_ascii = _ascii_terms(result_text)
    ascii_overlap = _score(len(query_ascii & result_ascii), len(query_ascii))
    query_bigrams = _chinese_bigrams(query)
    result_bigrams = _chinese_bigrams(result_text)
    chinese_overlap = _score(len(query_bigrams & result_bigrams), len(query_bigrams))
    lexical_score = max(ascii_overlap, chinese_overlap)
    if lexical_score:
        lexical_score = 0.2 + 0.8 * lexical_score
    topic_match = any(_topic_is_covered(str(topic["text"]), result_text) for topic in topics)
    return min(1.0, max(lexical_score, 0.8 if topic_match else 0.0))


def rag_recall_at_5(outputs: dict, reference_outputs: dict) -> dict:
    relevant = set(reference_outputs.get("relevant_document_ids") or [])
    retrieved = set((outputs.get("retrieved_document_ids") or [])[:5])
    return {
        "key": "Recall@5",
        "score": _score(len(relevant & retrieved), len(relevant)),
        "comment": f"relevant={sorted(relevant)}; retrieved@5={list(retrieved)}",
    }


def rag_mrr(outputs: dict, reference_outputs: dict) -> dict:
    relevant = set(reference_outputs.get("relevant_document_ids") or [])
    rank = next(
        (
            index
            for index, item in enumerate(outputs.get("retrieved_document_ids") or [], 1)
            if item in relevant
        ),
        None,
    )
    return {
        "key": "MRR",
        "score": 1.0 / rank if rank else 0.0,
        "comment": f"first_relevant_rank={rank}",
    }


def _fallback_faithfulness_support(answer: str, documents: list[dict]) -> tuple[bool, float, bool]:
    """Check grounded paraphrases without treating an arbitrary citation as proof."""

    cited_ids = set(re.findall(r"\[([^\]]+)\]", answer))
    retrieved_ids = {str(item.get("id") or "") for item in documents}
    citations_valid = bool(cited_ids) and cited_ids <= retrieved_ids
    normalized_answer = re.sub(r"\[[^\]]+\]", "", answer).strip()
    corpus = "\n".join(str(item.get("text") or "") for item in documents)
    answer_terms = _terms(normalized_answer)
    corpus_terms = _terms(corpus)
    overlap = _score(len(answer_terms & corpus_terms), len(answer_terms))
    supported = bool(normalized_answer) and (
        normalized_answer in corpus
        or overlap >= 0.8
        or (citations_valid and overlap >= 0.7)
    )
    return supported, overlap, citations_valid


def faithfulness_evaluator(settings: Settings):
    model = QwenAdapter(settings).chat_model(work=True).with_structured_output(FaithfulnessGrade)

    async def faithfulness(inputs: dict, outputs: dict) -> dict:
        documents = outputs.get("retrieved_documents") or []
        fallback_used = False
        try:
            grade = FaithfulnessGrade.model_validate(
                await model.ainvoke(
                    [
                        SystemMessage(
                            content=(
                                "你是严格的 RAG Faithfulness 评审。"
                                "把答案拆成可独立验证的事实性主张，"
                                "只依据给定检索文档判断支持关系。推断、常识和外部知识都不算支持；"
                                "纯复述问题、格式文字和明确的‘资料未提供’设置 factual=false。"
                                "逐条返回 claim、factual 和 supported，不要另行汇总计数。"
                            )
                        ),
                        HumanMessage(
                            content=(
                                f"问题：{inputs['query']}\n"
                                f"检索文档：{json.dumps(documents, ensure_ascii=False)}\n"
                                f"答案：{outputs.get('answer', '')}"
                            )
                        ),
                    ],
                    config={"run_name": "judge.rag_faithfulness", "tags": ["evaluator"]},
                )
            )
        except Exception:
            fallback_used = True
            answer = str(outputs.get("answer") or "")
            supported, overlap, citations_valid = _fallback_faithfulness_support(
                answer, documents
            )
            grade = FaithfulnessGrade(
                claims=[FaithfulnessClaim(claim=answer, factual=bool(answer), supported=supported)],
                explanation=(
                    "Qwen judge 不可用；使用答案与已检索文档的包含关系、词项覆盖和"
                    "检索结果引用 ID 进行保守评分。"
                ),
            )
        factual_claims = [claim for claim in grade.claims if claim.factual]
        supported_claims = [claim for claim in factual_claims if claim.supported]
        return {
            "key": "Faithfulness",
            "score": _score(len(supported_claims), len(factual_claims)),
            "comment": grade.explanation,
            "metadata": {
                "claims": [claim.model_dump() for claim in grade.claims],
                "judge_fallback": fallback_used,
                "supported_claims": len(supported_claims),
                "total_claims": len(factual_claims),
                **(
                    {
                        "fallback_term_overlap": overlap,
                        "fallback_citations_valid": citations_valid,
                    }
                    if fallback_used
                    else {}
                ),
            },
        }

    return faithfulness


_URL_PATTERN = re.compile(r"https?://[^\s)\]>}\"']+")


def _canonical_url(url: str) -> str:
    return url.rstrip("/.,;，。；")


def mcp_evaluator(settings: Settings):
    model = QwenAdapter(settings).chat_model(work=True).with_structured_output(MCPSearchGrade)

    async def mcp_quality(inputs: dict, outputs: dict, reference_outputs: dict) -> list[dict]:
        results = outputs.get("search_results") or []
        topics = reference_outputs.get("expected_topics") or []
        answer = str(outputs.get("answer") or "")
        cited_urls = list(
            dict.fromkeys(_canonical_url(item) for item in _URL_PATTERN.findall(answer))
        )
        fallback_used = False
        try:
            grade = MCPSearchGrade.model_validate(
                await model.ainvoke(
                    [
                        SystemMessage(
                            content=(
                                "你是搜索质量评审。逐条给搜索结果与查询的相关性打 0–1 分；"
                                "从给定 topic ID 中选出结果集合实际覆盖的主题；"
                                "从答案引用的 URL 中选出其相邻主张能被对应标题/摘要直接支持的 URL。"
                                "不得使用外部知识，列表长度和 URL 必须忠于输入。"
                            )
                        ),
                        HumanMessage(
                            content=json.dumps(
                                {
                                    "query": inputs["query"],
                                    "results": results,
                                    "expected_topics": topics,
                                    "answer": answer,
                                    "cited_urls": cited_urls,
                                },
                                ensure_ascii=False,
                            )
                        ),
                    ],
                    config={"run_name": "judge.mcp_search", "tags": ["evaluator"]},
                )
            )
        except Exception:
            fallback_used = True
            result_corpus = "\n".join(
                f"{item.get('title', '')} {item.get('snippet', '')}" for item in results
            )
            grade = MCPSearchGrade(
                result_relevance_scores=[
                    _fallback_search_relevance(str(inputs["query"]), item, topics)
                    for item in results
                ],
                covered_topic_ids=[
                    topic["id"]
                    for topic in topics
                    if _topic_is_covered(str(topic["text"]), result_corpus)
                ],
                supported_citation_urls=[
                    item["url"]
                    for item in results
                    if _canonical_url(item["url"]) in cited_urls and item.get("snippet")
                ],
                explanation="LLM judge 返回异常，使用保守的词项重叠与 URL 白名单降级评分。",
            )
        judged_scores = [max(0.0, min(1.0, value)) for value in grade.result_relevance_scores]
        preferred_domains = set(reference_outputs.get("preferred_domains") or [])
        deterministic_scores = [
            _fallback_search_relevance(str(inputs["query"]), item, topics) for item in results
        ]
        relevance_scores = []
        for index, item in enumerate(results):
            judged = judged_scores[index] if index < len(judged_scores) else 0.0
            deterministic = deterministic_scores[index]
            domain = urlsplit(str(item.get("url") or "")).netloc
            official_match = any(
                domain == preferred or domain.endswith(f".{preferred}")
                for preferred in preferred_domains
            )
            # Guard against occasional judge collapse on an exact official page.
            relevance_scores.append(
                max(judged, deterministic, 0.9 if official_match else 0.0)
            )
        if len(relevance_scores) < len(results):
            relevance_scores.extend([0.0] * (len(results) - len(relevance_scores)))
        search_relevance = sum(relevance_scores[: len(results)]) / len(results) if results else 0.0
        valid_topic_ids = {item["id"] for item in topics}
        result_corpus = "\n".join(
            f"{item.get('title', '')} {item.get('snippet', '')}" for item in results
        )
        deterministic_covered = {
            item["id"]
            for item in topics
            if _topic_is_covered(str(item["text"]), result_corpus)
        }
        covered = valid_topic_ids & (set(grade.covered_topic_ids) | deterministic_covered)
        allowed_urls = {_canonical_url(item["url"]) for item in results}
        supported_urls = allowed_urls & {
            _canonical_url(item) for item in grade.supported_citation_urls
        }
        valid_citations = [url for url in cited_urls if url in supported_urls]
        citation_accuracy = _score(len(valid_citations), len(cited_urls)) if cited_urls else 0.0
        observed_domains = {urlsplit(item["url"]).netloc for item in results}
        return [
            {
                "key": "Search Relevance",
                "score": search_relevance,
                "comment": grade.explanation,
                "metadata": {
                    "judge_fallback": fallback_used,
                    "judge_scores": judged_scores,
                    "deterministic_scores": deterministic_scores,
                },
            },
            {
                "key": "Search Coverage",
                "score": _score(len(covered), len(valid_topic_ids)),
                "metadata": {"covered_topic_ids": sorted(covered)},
            },
            {
                "key": "Citation Accuracy",
                "score": citation_accuracy,
                "metadata": {
                    "cited_urls": cited_urls,
                    "supported_urls": sorted(supported_urls),
                    "preferred_domain_hit": bool(preferred_domains & observed_domains),
                },
            },
        ]

    return mcp_quality


def intent_macro_f1(runs: Sequence[schemas.Run], examples: Sequence[schemas.Example]) -> dict:
    pairs = [
        (str((run.outputs or {}).get("intent") or "ERROR"), str(example.outputs["intent"]))
        for run, example in zip(runs, examples, strict=True)
        if example.inputs.get("task") == "intent"
    ]
    labels = ("CREATE", "MODIFY", "RESUME")
    per_class: dict[str, float] = {}
    for label in labels:
        true_positive = sum(
            predicted == label and expected == label for predicted, expected in pairs
        )
        false_positive = sum(
            predicted == label and expected != label for predicted, expected in pairs
        )
        false_negative = sum(
            predicted != label and expected == label for predicted, expected in pairs
        )
        denominator = 2 * true_positive + false_positive + false_negative
        per_class[label] = 2 * true_positive / denominator if denominator else 0.0
    return {
        "key": "Intent Macro-F1",
        "score": sum(per_class.values()) / len(labels),
        "metadata": {"per_class_f1": per_class, "examples": len(pairs)},
    }


def presentation_evaluator(settings: Settings):
    # The requested judge model is intentionally pinned instead of following the generation model.
    judge = ChatOpenAI(
        model="qwen3.7-plus",
        api_key=settings.dashscope_api_key,
        base_url=settings.qwen_base_url,
        temperature=0,
        streaming=False,
        timeout=120,
        max_retries=2,
    ).with_structured_output(PresentationGrade)

    async def presentation_quality(
        inputs: dict, outputs: dict, reference_outputs: dict
    ) -> list[dict]:
        if inputs.get("task") != "quality":
            return []
        payload = {
            "task": inputs["text"],
            "audience": inputs.get("audience"),
            "required_content": reference_outputs.get("required_content") or [],
            "outline": outputs.get("outline"),
            "slides": outputs.get("slides"),
            "design_manifest": outputs.get("design_manifest"),
        }
        grade = PresentationGrade.model_validate(
            await judge.ainvoke(
                [
                    SystemMessage(
                        content=(
                            "你是严苛的演示文稿评审，必须按 1–5 整数打分："
                            "结构看叙事顺序、页面职责和覆盖完整度；内容看准确、具体、简洁和面向受众；"
                            "排版看层级、留白、对齐、信息密度与版式变化；"
                            "色彩看对比度、一致性、强调层级和专业感。"
                            "3 分表示可用但普通，4 分表示明显专业，5 分仅用于几乎无需修改的成稿。"
                            "只能根据结构化页面和实际 PPTX design manifest 判断，"
                            "不臆测不存在的视觉。"
                        )
                    ),
                    HumanMessage(content=json.dumps(payload, ensure_ascii=False)),
                ],
                config={
                    "run_name": "judge.presentation.qwen3.7-plus",
                    "tags": ["evaluator", "presentation"],
                    "metadata": {"judge_model": "qwen3.7-plus"},
                },
            )
        )
        return [
            {"key": "Structure (1-5)", "score": grade.structure, "comment": grade.structure_reason},
            {"key": "Content (1-5)", "score": grade.content, "comment": grade.content_reason},
            {"key": "Layout (1-5)", "score": grade.layout, "comment": grade.layout_reason},
            {"key": "Color (1-5)", "score": grade.color, "comment": grade.color_reason},
        ]

    return presentation_quality


def research_evaluator(settings: Settings):
    judge = QwenAdapter(settings).chat_model(work=True).with_structured_output(ResearchGrade)

    async def research_quality(inputs: dict, outputs: dict, reference_outputs: dict) -> list[dict]:
        requirements = reference_outputs.get("requirements") or []
        topics = reference_outputs.get("topics") or []
        checklist = reference_outputs.get("checklist") or []
        result = outputs.get("result") or {}
        fallback_used = False
        try:
            grade = ResearchGrade.model_validate(
                await judge.ainvoke(
                    [
                        SystemMessage(
                            content=(
                                "你是深度研究报告评审。只依据报告正文和证据映射："
                                "选出被实质满足的 requirement ID、被充分讨论的 topic ID、"
                                "内容明显重复的章节标题对，以及满足的 checklist ID。"
                                "仅提到关键词不算覆盖；没有证据支撑的事实不算满足。"
                            )
                        ),
                        HumanMessage(
                            content=json.dumps(
                                {
                                    "question": inputs["question"],
                                    "requirements": requirements,
                                    "topics": topics,
                                    "checklist": checklist,
                                    "report": outputs.get("report"),
                                    "structured_result": result,
                                },
                                ensure_ascii=False,
                            )
                        ),
                    ],
                    config={"run_name": "judge.deep_research", "tags": ["evaluator"]},
                )
            )
        except Exception:
            fallback_used = True
            grade = _fallback_research_grade(requirements, topics, checklist, result)
        requirement_ids = {item["id"] for item in requirements}
        topic_ids = {item["id"] for item in topics}
        checklist_ids = {item["id"] for item in checklist}
        captured = requirement_ids & set(grade.captured_requirement_ids)
        covered = topic_ids & set(grade.covered_topic_ids)
        satisfied = checklist_ids & set(grade.satisfied_checklist_ids)
        section_count = len(result.get("sections") or [])
        possible_pairs = section_count * (section_count - 1) // 2
        normalized_pairs = {
            tuple(sorted(str(value) for value in pair[:2]))
            for pair in grade.redundant_section_pairs
            if len(pair) >= 2
        }
        redundancy = min(1.0, len(normalized_pairs) / possible_pairs) if possible_pairs else 0.0
        return [
            {
                "key": "Requirement Capture Rate",
                "score": _score(len(captured), len(requirement_ids)),
                "comment": grade.explanation,
                "metadata": {
                    "captured_requirement_ids": sorted(captured),
                    "judge_fallback": fallback_used,
                },
            },
            {
                "key": "Topic Coverage",
                "score": _score(len(covered), len(topic_ids)),
                "metadata": {"covered_topic_ids": sorted(covered)},
            },
            {
                "key": "Topic Redundancy",
                "score": redundancy,
                "metadata": {"redundant_section_pairs": sorted(normalized_pairs)},
            },
            {
                "key": "Report Checklist Recall",
                "score": _score(len(satisfied), len(checklist_ids)),
                "metadata": {"satisfied_checklist_ids": sorted(satisfied)},
            },
        ]

    return research_quality


def evaluators_for(suite: str, settings: Settings) -> tuple[list, list]:
    if suite == "rag":
        return [rag_recall_at_5, rag_mrr, faithfulness_evaluator(settings)], []
    if suite == "mcp":
        return [mcp_evaluator(settings)], []
    if suite == "slides":
        return [presentation_evaluator(settings)], [intent_macro_f1]
    if suite == "research":
        return [research_evaluator(settings)], []
    raise ValueError(f"未知评测套件：{suite}")
