from types import SimpleNamespace

from app.agents.service import _normalize_slide_bullets, _render_presentation
from app.agents.workflows import (
    PresentationOutline,
    SlideContent,
    _research_facets,
    deterministic_outline,
    normalize_presentation_outline,
    route_presentation_intent,
)
from app.chat.service import search_query_from_request
from app.core.config import Settings
from app.evaluation.datasets import DATASETS, build_large_attachment
from app.evaluation.evaluators import (
    _fallback_faithfulness_support,
    _fallback_research_grade,
    _fallback_search_relevance,
    _topic_is_covered,
    intent_macro_f1,
    rag_mrr,
    rag_recall_at_5,
)
from app.evaluation.targets import (
    _extractive_search_answer,
    clean_search_query,
    presentation_manifest,
)
from app.files.service import document_chunks_for_upload, validate_upload
from app.integrations.tavily import (
    SearchResult,
    normalize_search_citations,
    search_query_variants,
)


def test_rag_ranking_metrics_use_reference_document_ids() -> None:
    outputs = {"retrieved_document_ids": ["noise", "relevant-b", "relevant-a"]}
    reference = {"relevant_document_ids": ["relevant-a", "relevant-b"]}
    assert rag_recall_at_5(outputs, reference)["score"] == 1.0
    assert rag_mrr(outputs, reference)["score"] == 0.5


def test_faithfulness_fallback_accepts_grounded_cited_paraphrase() -> None:
    documents = [
        {
            "id": "research-evidence",
            "text": "研究报告必须保留可核验 URL，将证据映射到主题，并明确局限与尚未解决的问题。",
        },
        {
            "id": "research-fallback",
            "text": (
                "安全降级报告只能整理已经获得的真实搜索证据，"
                "不得编造 URL 或把未证实内容写成事实。"
            ),
        },
    ]
    answer = (
        "来源要求：必须保留可核验的URL[research-evidence]；安全降级报告仅限整理已获取的真实"
        "搜索证据，不得编造URL或将未证实内容写成事实[research-fallback]。不确定性要求：需将"
        "证据映射到具体主题，并明确说明局限与尚未解决的问题[research-evidence]。"
    )
    supported, overlap, citations_valid = _fallback_faithfulness_support(answer, documents)
    assert supported
    assert overlap >= 0.7
    assert citations_valid


def test_faithfulness_fallback_rejects_unsupported_low_overlap_claim() -> None:
    documents = [{"id": "source", "text": "生产环境只能使用 PostgreSQL。"}]
    supported, _, citations_valid = _fallback_faithfulness_support(
        "所有用户都享有无限免费额度，并且数据永不删除[source]。", documents
    )
    assert not supported
    assert citations_valid


def test_scaled_dataset_sizes_and_large_rag_attachments() -> None:
    assert {name: len(spec.examples) for name, spec in DATASETS.items()} == {
        "rag": 100,
        "mcp": 20,
        "slides": 25,
        "research": 25,
    }
    rag_case_ids = [example["inputs"]["case_id"] for example in DATASETS["rag"].examples]
    rag_queries = [example["inputs"]["query"] for example in DATASETS["rag"].examples]
    assert len(set(rag_case_ids)) == 100
    assert len(set(rag_queries)) == 100
    fixtures = [
        example["attachment_fixture"]
        for example in DATASETS["rag"].examples
        if example.get("attachment_fixture")
    ]
    assert len(fixtures) == 4
    assert {fixture["filename"].rsplit(".", 1)[-1] for fixture in fixtures} == {
        "docx",
        "pdf",
        "md",
    }
    for fixture in fixtures:
        data = build_large_attachment(fixture)
        assert 14 * 1024 * 1024 < len(data) < 16 * 1024 * 1024
        validated = validate_upload(
            fixture["filename"], fixture["mime_type"], data, Settings()
        )
        chunks = document_chunks_for_upload(validated, Settings())
        assert validated.kind == "document"
        assert fixture["text"].replace("\n", "") in validated.text.replace("\n", "")
        assert chunks


def test_intent_macro_f1_is_class_balanced() -> None:
    runs = [
        SimpleNamespace(outputs={"intent": "CREATE"}),
        SimpleNamespace(outputs={"intent": "MODIFY"}),
        SimpleNamespace(outputs={"intent": "CREATE"}),
    ]
    examples = [
        SimpleNamespace(inputs={"task": "intent"}, outputs={"intent": "CREATE"}),
        SimpleNamespace(inputs={"task": "intent"}, outputs={"intent": "MODIFY"}),
        SimpleNamespace(inputs={"task": "intent"}, outputs={"intent": "RESUME"}),
    ]
    result = intent_macro_f1(runs, examples)
    assert result["key"] == "Intent Macro-F1"
    assert round(result["score"], 4) == 0.5556


def test_search_trigger_language_is_removed_from_mcp_query() -> None:
    expected = "LangSmith dataset 官方文档"
    assert search_query_from_request("请联网搜索一下 LangSmith dataset 官方文档") == expected
    assert clean_search_query("请联网搜索一下 LangSmith dataset 官方文档") == expected


def test_numeric_search_citations_become_verified_markdown_links() -> None:
    results = [SearchResult("官方文档", "https://example.com/docs", "直接支持主张")]
    assert normalize_search_citations("结论[1]。", results) == (
        "结论[官方文档](https://example.com/docs)。"
    )
    assert normalize_search_citations("结论[1](https://wrong.example/path)。", results) == (
        "结论[官方文档](https://example.com/docs)。"
    )


def test_search_query_variants_target_enumerated_facets() -> None:
    variants = search_query_variants(
        "MDN Server-sent events 文档，说明 EventSource、事件格式和自动重连"
    )
    assert variants[0].endswith("自动重连")
    assert any("事件格式" in item for item in variants[1:])
    assert any("自动重连" in item for item in variants[1:])


def test_mcp_fallback_recognizes_code_identifiers_and_chinese_topics() -> None:
    corpus = (
        "LangSmith Client.create_dataset creates a dataset before evaluate runs. "
        "StreamingResponse 可以使用异步生成器逐块产出内容。"
    )
    assert _topic_is_covered("Client.create_dataset 创建数据集", corpus)
    assert _topic_is_covered("evaluate 或 aevaluate 运行实验", corpus)
    assert _topic_is_covered("可使用异步生成器逐块产出内容", corpus)
    assert not _topic_is_covered("Client.create_examples 写入样本", corpus)

    relevance = _fallback_search_relevance(
        "请联网搜索 LangSmith Python SDK 创建 dataset 并运行 evaluate 的官方方法",
        {
            "title": "LangSmith evaluation quickstart",
            "snippet": "Use Client.create_dataset, then evaluate your target function.",
        },
        [{"id": "create_dataset", "text": "Client.create_dataset 创建数据集"}],
    )
    assert relevance >= 0.8


def test_slide_routing_prioritizes_creation_command_without_source() -> None:
    assert route_presentation_intent("做一个关于如何调整库存策略的新演示") == "CREATE"
    assert route_presentation_intent("调整第 2 页", source_artifact_id="artifact") == "MODIFY"


def test_outline_normalization_rejects_structural_placeholder_variants() -> None:
    outline = normalize_presentation_outline(
        PresentationOutline(
            title="slide_titles",
            slides=["cover_slide", "content page", "关键结论", "next_steps"],
        ),
        "产品复盘",
        3,
    )
    assert outline.title == "产品复盘"
    assert outline.slides[0] == "关键结论"
    assert all("slide" not in title.casefold() for title in outline.slides)

    repaired = normalize_presentation_outline(
        PresentationOutline(
            title="复盘",
            slides=['{"page": 1, "title": "首个有效结论"}', ":"],
        ),
        "产品复盘",
        3,
    )
    assert repaired.slides[0] == "首个有效结论"
    assert len(repaired.slides) == 3


def test_deterministic_outline_uses_explicit_requirements_to_fill_target_pages() -> None:
    outline = deterministic_outline(
        "生成技术简报，讲清 Recall@5、MRR、Faithfulness、实验流程与发布门槛。", 5
    )
    assert len(outline.slides) == 5
    assert [title.split("：", 1)[0] for title in outline.slides] == [
        "Recall@5",
        "MRR",
        "Faithfulness",
        "实验流程",
        "发布门槛",
    ]


def test_research_facets_expand_enumerated_requirements() -> None:
    facets = _research_facets(
        "研究仪表板。要求说明文本和非文本对比度、键盘操作、焦点可见性和动态图表替代信息，给出审计步骤。"
    )
    assert facets == [
        "说明文本和非文本对比度",
        "说明键盘操作",
        "说明焦点可见性",
        "说明动态图表替代信息",
        "给出审计步骤",
    ]
    assert _research_facets(
        "研究探针。要求比较 startup、readiness、liveness 的语义，区分代码指标和 LLM-as-judge。"
    ) == [
        "比较 startup、readiness、liveness 的语义",
        "区分代码指标和 LLM-as-judge",
    ]


def test_presentation_manifest_exposes_real_layout_and_color_data() -> None:
    outline = PresentationOutline(
        title="评估复盘", slides=["召回稳定，重点转向忠实度", "上线前收紧证据门槛"]
    )
    slides = [
        SlideContent(
            title=outline.slides[0],
            bullets=["Recall@5 已达到目标", "收紧回答的证据约束", "上线前复跑回归集"],
        ),
        SlideContent(title=outline.slides[1], bullets=["设定阈值", "观察回归", "保留审计记录"]),
    ]
    data, _ = _render_presentation(outline, slides)
    manifest = presentation_manifest(data)
    assert manifest["slide_count"] == 3
    assert manifest["aspect_ratio"] > 1.7
    assert manifest["slides"][0]["background"]
    assert any(shape["font_sizes_pt"] for slide in manifest["slides"] for shape in slide["shapes"])


def test_slide_bullet_normalization_repairs_partial_and_sparse_content() -> None:
    bullets = _normalize_slide_bullets(
        "季度里程碑：核心发现与行动",
        ["围绕“年度策略”说明季度里程碑", "结论：试点团队覆盖"],
        ["关键事实与建议", "可执行的下一步"],
    )
    assert len(bullets) == 3
    assert all(not bullet.endswith("覆盖") for bullet in bullets)
    assert any("负责人、时间点与验收条件" in bullet for bullet in bullets)


def test_extractive_search_answer_only_uses_observed_urls() -> None:
    answer = _extractive_search_answer(
        [
            SearchResult(
                title="Official guide",
                url="https://example.com/guide",
                snippet="The feature requires an explicit setting. More details follow.",
            )
        ]
    )
    assert "The feature requires an explicit setting." in answer
    assert "[Official guide](https://example.com/guide)" in answer


def test_research_fallback_grades_evidence_backed_sections_and_checklist() -> None:
    grade = _fallback_research_grade(
        [{"id": "r1", "text": "说明 startup probe 语义"}],
        [{"id": "t1", "text": "Startup Probe"}],
        [
            {"id": "c1", "text": "执行摘要"},
            {"id": "c2", "text": "研究方法或来源范围"},
            {"id": "c3", "text": "分主题发现与证据"},
            {"id": "c4", "text": "建议、局限或未解决问题"},
            {"id": "c5", "text": "可核验来源"},
        ],
        {
            "sections": [
                {"heading": "执行摘要", "content": "摘要", "evidence_ids": []},
                {"heading": "研究方法与来源范围", "content": "方法", "evidence_ids": []},
                {
                    "heading": "Startup Probe 语义",
                        "content": (
                            "Startup Probe 在成功前会保护慢启动容器，避免存活探针过早重启应用；"
                            "它与 Liveness Probe 不同，前者判断是否完成启动，后者决定是否重启。"
                        )
                        * 2,
                    "evidence_ids": ["S1"],
                },
                {
                    "heading": "验证步骤",
                    "content": "在测试环境模拟慢启动并观察探针状态、重启次数和就绪流量。" * 3,
                    "evidence_ids": ["S1"],
                },
                {"heading": "建议与局限", "content": "需场景化验证。", "evidence_ids": []},
            ],
            "evidence": [{"url": "https://kubernetes.io/docs/tasks/configure-pod-container/"}],
        },
    )
    assert grade.captured_requirement_ids == ["r1"]
    assert grade.covered_topic_ids == ["t1"]
    assert set(grade.satisfied_checklist_ids) == {"c1", "c2", "c3", "c4", "c5"}
