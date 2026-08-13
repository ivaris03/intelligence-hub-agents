# Dataset prompts are intentionally kept as single literals for exact display in LangSmith.
# ruff: noqa: E501

from __future__ import annotations

import zipfile
from dataclasses import dataclass
from io import BytesIO
from uuid import NAMESPACE_URL, uuid5

from docx import Document as WordDocument
from langsmith import Client
from pypdf import PdfWriter
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfgen import canvas


@dataclass(frozen=True, slots=True)
class DatasetSpec:
    name: str
    description: str
    examples: list[dict]


def _documents(*items: tuple[str, str]) -> list[dict[str, str]]:
    return [{"id": item_id, "text": text} for item_id, text in items]


RAG_EXAMPLES = [
    {
        "inputs": {
            "case_id": "rag-upload-limits",
            "query": "每条消息最多上传几个文件？单文件上限多大？",
            "documents": _documents(
                (
                    "upload-policy",
                    "文件上传限制：单文件不超过 20 MB，单条消息或 Work 任务最多 3 个文件。",
                ),
                ("image-policy", "图片格式支持 PNG、JPG、JPEG 和 WEBP，并校验图片像素。"),
                ("document-types", "文档支持 TXT、Markdown、PDF 和 DOCX，长文档会进行分块。"),
                ("storage", "产物可以保存在本地目录或 MinIO 对象存储中。"),
                ("database", "会话、消息和运行状态由 PostgreSQL 持久化。"),
                ("search", "联网请求通过 Tavily MCP 搜索，普通问答不会自动联网。"),
                (
                    "skills",
                    "Skill 可通过输入框下方的选择器显式调用，也可按任务自动匹配。",
                ),
                ("memory", "Memory 只注入少量与当前问题相关的长期信息。"),
            ),
        },
        "outputs": {
            "relevant_document_ids": ["upload-policy"],
            "reference_answer": "每条消息或 Work 任务最多上传 3 个文件，单文件不超过 20 MB。",
        },
    },
    {
        "inputs": {
            "case_id": "rag-follow-up",
            "query": "CHAT-07 对推荐问题的数量和点击行为有什么要求？",
            "documents": _documents(
                ("chat-01", "CHAT-01：会话可以新建、切换、重命名和删除，刷新后仍保留。"),
                ("chat-02", "CHAT-02：多轮对话支持 Markdown、代码块和流式输出。"),
                ("chat-03", "CHAT-03：消息支持停止生成、重新生成和复制回答。"),
                ("chat-05", "CHAT-05：消息中可折叠展示模型思考和工具调用详情。"),
                ("chat-06", "CHAT-06：首次回答完成后生成简短会话标题。"),
                (
                    "chat-07",
                    "CHAT-07：每条已完成回答末尾恰好显示一个上下文相关问题；点击只填入输入框，不自动发送。",
                ),
                ("chat-08", "CHAT-08：支持按标题和消息正文搜索历史会话。"),
                ("work-mode", "Work 模式必须选择一个 Agent，Chat 模式不能启动 Agent。"),
            ),
        },
        "outputs": {
            "relevant_document_ids": ["chat-07"],
            "reference_answer": (
                "每条完成回答末尾显示恰好一个相关问题，点击后只填入输入框而不自动发送。"
            ),
        },
    },
    {
        "inputs": {
            "case_id": "rag-slides-resume",
            "query": "演示 Agent 恢复运行时，怎样避免重复生成产物？",
            "documents": _documents(
                ("slides-create", "CREATE 会先生成大纲，用户确认后才生成 PPTX。"),
                ("slides-modify", "MODIFY 基于指定演示版本做定向修改，并保留原版本。"),
                (
                    "slides-resume",
                    "RESUME 在每个主要阶段保存检查点，从最近检查点继续；"
                    "已完成阶段和已登记产物不得重复生成。",
                ),
                ("image-agent", "图片 Agent 把描述和参考图转成可下载图片。"),
                ("research-agent", "研究 Agent 在搜索次数和总时长预算内生成 Markdown 报告。"),
                ("artifact-store", "所有 Agent 产物都与会话和运行绑定。"),
                ("retry", "失败运行可重试，错误信息不得暴露供应商载荷。"),
                ("preview", "前端为图片、PPTX 和 Markdown 提供相应预览或下载入口。"),
            ),
        },
        "outputs": {
            "relevant_document_ids": ["slides-resume", "artifact-store"],
            "reference_answer": (
                "主要阶段完成后保存检查点，恢复时从最近检查点继续，并复用已登记产物，避免重复生成。"
            ),
        },
    },
    {
        "inputs": {
            "case_id": "rag-memory-safety",
            "query": "Memory 会不会自动保存密码？关闭以后还会提炼或注入吗？",
            "documents": _documents(
                ("memory-summary", "Memory 只保存一份用户记忆摘要，支持查看、编辑和清空。"),
                ("memory-toggle", "Memory 默认开启；关闭后不提炼、不写入，也不向模型注入记忆。"),
                ("memory-sensitive", "系统不自动保存密码、密钥、支付信息或其他高敏感内容。"),
                (
                    "memory-idle",
                    "会话闲置 6 小时后进入待处理队列，并在用户本地午夜统一提炼稳定、低风险的偏好。",
                ),
                ("skill-snapshot", "Skill 调用时保存不可变快照，之后编辑不会改变历史消息。"),
                ("security-log", "工具日志会脱敏，不展示认证头和完整内部状态。"),
                ("settings", "设置页展示模型与搜索服务状态。"),
                ("single-user", "MVP 是单用户本地工作区，不设计团队权限。"),
            ),
        },
        "outputs": {
            "relevant_document_ids": ["memory-toggle", "memory-sensitive"],
            "reference_answer": "不会自动保存密码等高敏感内容；Memory 关闭后不再提炼、写入或注入。",
        },
    },
    {
        "inputs": {
            "case_id": "rag-research-budget",
            "query": "深度研究的搜索次数和总时间由什么配置控制？默认值是多少？",
            "documents": _documents(
                (
                    "research-budget",
                    "RESEARCH_MAX_SEARCHES 控制共享搜索预算，默认 4 次；"
                    "RESEARCH_TIMEOUT_SECONDS 控制外层总时长，默认 120 秒。",
                ),
                ("upload-bytes", "MAX_UPLOAD_BYTES 的默认值是 20971520。"),
                ("image-pixels", "MAX_IMAGE_PIXELS 默认限制为 24000000 像素。"),
                ("recent-messages", "RECENT_MESSAGE_LIMIT 默认取最近 12 条消息。"),
                ("memory-summary", "每轮对话将整份用户记忆摘要注入 System Prompt。"),
                ("slides-pages", "SLIDES_MAX_PAGES 默认最多 15 页。"),
                (
                    "thinking",
                    "QWEN_THINKING_EFFORT 默认是 medium，可选 none、low、medium、high。",
                ),
                ("chunks", "DOCUMENT_CHUNK_CHARS 默认是 1200，重叠 150 字符。"),
            ),
        },
        "outputs": {
            "relevant_document_ids": ["research-budget"],
            "reference_answer": (
                "由 RESEARCH_MAX_SEARCHES 和 RESEARCH_TIMEOUT_SECONDS 控制，"
                "默认分别为 4 次和 120 秒。"
            ),
        },
    },
]


_RAG_FACTS = [
    (
        "file-count-limits",
        "上传文件时，单次最多可以关联几个文件，单文件限制是多少？",
        "上传策略规定单次请求最多关联 3 个文件，每个文件不能超过 20 MB。",
        "单次最多 3 个，单文件不能超过 20 MB。",
        False,
    ),
    (
        "document-formats",
        "系统当前支持上传哪些文档格式？",
        "可解析的文档扩展名是 TXT、Markdown、PDF 与 DOCX。",
        "支持 TXT、Markdown、PDF 和 DOCX。",
        False,
    ),
    (
        "image-formats",
        "参考图片允许使用哪些文件格式？",
        "图片上传支持 PNG、JPG、JPEG 和 WEBP，不接受 SVG。",
        "支持 PNG、JPG、JPEG 和 WEBP。",
        False,
    ),
    (
        "image-pixels",
        "图片默认最多允许多少像素？",
        "MAX_IMAGE_PIXELS 默认值为 24000000，即最多二千四百万像素。",
        "默认最多 24,000,000 像素。",
        False,
    ),
    (
        "storage-backends",
        "文件和产物可以落到哪两种存储后端？",
        "STORAGE_BACKEND 可以选择 local 本地目录或 minio 对象存储。",
        "可以使用 local 或 MinIO。",
        False,
    ),
    (
        "chat-web-trigger",
        "普通 Chat 会自动联网吗？什么情况下才搜索？",
        "普通问答不会自动联网，只有明确出现联网搜索、上网查找或 search the web 等意图才调用 Tavily。",
        "不会自动联网；只有显式提出联网搜索意图时才调用 Tavily。",
        False,
    ),
    (
        "chat-recommendation",
        "回答后的推荐问题显示几个，点击后会发生什么？",
        "每条完成回答末尾恰好显示一个相关问题，点击只填入输入框而不会自动发送。",
        "显示一个；点击只填入输入框，不自动发送。",
        False,
    ),
    (
        "chat-auto-title",
        "会话标题在什么时候自动生成，手动标题会被覆盖吗？",
        "首次回答完成后可以生成简短自动标题；用户设置手动标题后，自动标题不得覆盖它。",
        "首次回答后生成；手动标题不会被自动标题覆盖。",
        False,
    ),
    (
        "chat-stop-regenerate",
        "停止生成后重新生成，是否应该重复写入用户消息？",
        "停止与重新生成复用原用户消息，不能重复插入同一条用户消息。",
        "不应该；重新生成必须复用原用户消息。",
        False,
    ),
    (
        "chat-history-search",
        "历史会话搜索会检查哪些文本？",
        "会话搜索同时匹配会话标题和消息正文。",
        "同时搜索标题和消息正文。",
        False,
    ),
    (
        "memory-disable",
        "关闭 Memory 后还会写入、提炼或注入吗？",
        "Memory 关闭后不提炼、不写入，也不向模型注入长期记忆。",
        "三者都不会继续。",
        False,
    ),
    (
        "memory-sensitive",
        "Memory 是否会自动保存密码、密钥或支付信息？",
        "系统禁止自动保存密码、API 密钥、支付信息等高敏感内容。",
        "不会自动保存这些高敏感内容。",
        False,
    ),
    (
        "memory-idle",
        "会话闲置多久后可以触发安全记忆提炼？",
        "会话闲置 6 小时后进入待处理队列，并在用户本地午夜通过游标式任务统一提炼稳定且低风险的偏好。",
        "闲置 6 小时后入队，在用户本地午夜统一处理。",
        False,
    ),
    (
        "memory-budget",
        "Memory 在每轮对话中如何注入？",
        "系统每轮将唯一的用户记忆摘要完整注入 System Prompt。",
        "整份用户记忆摘要会在每轮注入 System Prompt。",
        False,
    ),
    (
        "skill-snapshot",
        "编辑 Skill 后，历史消息里的调用配置会改变吗？",
        "Skill 调用时保存不可变快照，之后编辑 Skill 不会改变历史调用记录。",
        "不会，历史调用使用不可变快照。",
        False,
    ),
    (
        "image-agent-output",
        "图片 Agent 的输入和产物分别是什么？",
        "图片 Agent 接收文字描述与可选参考图，输出可预览、下载和重试的图片产物。",
        "输入是描述和可选参考图，输出是可预览下载的图片。",
        False,
    ),
    (
        "slides-confirmation",
        "演示 CREATE 为什么不会立刻生成 PPTX？",
        "演示 CREATE 先生成大纲并进入确认中断，只有用户确认后才生成 PPTX。",
        "因为必须先确认大纲，确认后才生成 PPTX。",
        False,
    ),
    (
        "slides-versioning",
        "修改演示时会覆盖原 PPTX 吗？",
        "演示 MODIFY 基于指定源版本定向修改，生成新版本并保留原版本。",
        "不会，会生成新版本并保留原版本。",
        False,
    ),
    (
        "slides-checkpoint-large",
        "演示恢复运行如何避免重复生成已登记产物？",
        "RESUME 从最近检查点继续，跳过已完成阶段，并复用已经登记的 Artifact，禁止重复创建。",
        "从最近检查点继续并复用已登记 Artifact。",
        True,
    ),
    (
        "research-budget-detail",
        "深度研究默认共享搜索预算和总超时分别是多少？",
        "RESEARCH_MAX_SEARCHES 默认 4 次，RESEARCH_TIMEOUT_SECONDS 默认 120 秒。",
        "默认最多搜索 4 次，总超时 120 秒。",
        False,
    ),
    (
        "model-routing",
        "默认 Chat 模型和 Work Agent 模型分别是什么？",
        "QWEN_CHAT_MODEL 默认 qwen3.7-flash，QWEN_AGENT_MODEL 默认 qwen3.7-plus。",
        "Chat 使用 qwen3.7-flash，Work 使用 qwen3.7-plus。",
        False,
    ),
    (
        "embedding-config",
        "默认向量模型和维度是什么？",
        "QWEN_EMBEDDING_MODEL 默认 qwen3.7-text-embedding，向量维度默认 1024。",
        "默认是 qwen3.7-text-embedding，1024 维。",
        False,
    ),
    (
        "thinking-effort",
        "Chat 和 Work 默认使用什么思考强度？有哪些选项？",
        "QWEN_THINKING_EFFORT 默认配置为 medium，可选 none、low、medium、high。",
        "默认 medium，可选 none、low、medium、high。",
        False,
    ),
    (
        "slides-page-limit",
        "演示生成默认最多允许多少页？",
        "SLIDES_MAX_PAGES 默认值为 15，页面限制包含封面。",
        "默认最多 15 页，包含封面。",
        False,
    ),
    (
        "recent-message-limit",
        "Chat 默认取多少条最近消息作为上下文？",
        "RECENT_MESSAGE_LIMIT 默认值为 12 条消息。",
        "默认取最近 12 条。",
        False,
    ),
    (
        "frontend-stack",
        "前端采用什么主要技术栈？",
        "前端位于 frontend 目录，使用 Vue 3、TypeScript、Vite 与 Pinia。",
        "Vue 3、TypeScript、Vite 和 Pinia。",
        False,
    ),
    (
        "backend-stack",
        "后端 API 和 Agent 编排分别使用什么框架？",
        "后端 API 使用 FastAPI，Agent 工作流主要使用 LangChain、LangGraph 与 Deep Agents。",
        "API 使用 FastAPI，编排使用 LangChain、LangGraph 和 Deep Agents。",
        False,
    ),
    (
        "database-stack",
        "系统使用什么数据库，向量检索依赖什么扩展？",
        "持久化数据库是 PostgreSQL，向量字段和相似度检索使用 pgvector 扩展。",
        "使用 PostgreSQL 和 pgvector。",
        False,
    ),
    (
        "stream-protocol",
        "Chat 与 Agent 的增量事件通过什么协议返回？",
        "服务端使用 Server-Sent Events（SSE）向前端流式发送回答和阶段事件。",
        "通过 SSE 返回。",
        False,
    ),
    (
        "artifact-binding",
        "Agent 产物会绑定到哪些实体？",
        "所有 Artifact 都绑定会话与 agent_run，并记录类型、版本、存储键和元数据。",
        "绑定会话和 agent_run。",
        False,
    ),
    (
        "mime-validation",
        "上传校验是否只看扩展名？",
        "上传校验同时检查扩展名、声明 MIME 和文件魔数或真实解码结果，不只看扩展名。",
        "不是，会同时校验 MIME 和文件真实内容。",
        False,
    ),
    (
        "url-sanitization",
        "联网回答中的任意 URL 都会保留吗？",
        "联网回答只保留当前搜索结果白名单中的 URL，未验证链接会被移除。",
        "不会，只保留当前搜索结果中的已验证 URL。",
        False,
    ),
    (
        "secret-boundary-large",
        "服务端密钥是否会由设置 API 返回给前端？",
        "DASHSCOPE_API_KEY、TAVILY_API_KEY 与 LANGSMITH_API_KEY 只从服务端环境读取，API 不返回密钥值。",
        "不会，密钥只在服务端环境中读取。",
        True,
    ),
    (
        "error-redaction",
        "Agent 失败时可以把供应商原始载荷直接展示给用户吗？",
        "失败事件只返回安全错误摘要，不得暴露供应商载荷、认证头或内部完整状态。",
        "不可以，只能展示脱敏后的安全摘要。",
        False,
    ),
    (
        "file-ownership",
        "请求引用一个其他会话的文件 ID 时会怎样？",
        "文件加载要求文件属于当前 conversation 且状态为 ready，否则按不存在或未就绪拒绝。",
        "会被拒绝，因为文件必须属于当前会话且已就绪。",
        False,
    ),
    (
        "rag-metrics",
        "RAG 离线评估使用哪三个核心指标？",
        "RAG 评估使用 Recall@5、MRR 和 Faithfulness。",
        "Recall@5、MRR 和 Faithfulness。",
        False,
    ),
    (
        "mcp-metrics-large",
        "MCP 搜索质量用哪三项指标衡量？",
        "MCP 搜索评估包含 Search Relevance、Search Coverage 和 Citation Accuracy。",
        "搜索相关性、搜索覆盖率和引用准确率。",
        True,
    ),
    (
        "slides-metrics",
        "演示 Agent 的意图和成稿质量分别怎么评？",
        "演示意图使用 Intent Macro-F1；成稿由 qwen3.7-plus 对结构、内容、排版和色彩按 1 到 5 分评审。",
        "意图用 Macro-F1，成稿按结构、内容、排版、色彩四维 1–5 分。",
        False,
    ),
    (
        "research-metrics",
        "深度研究评估包含哪些指标，哪个是越低越好？",
        "研究指标是 Requirement Capture Rate、Topic Coverage、Topic Redundancy 与 Report Checklist Recall，其中 Topic Redundancy 越低越好。",
        "四项如述，其中 Topic Redundancy 越低越好。",
        False,
    ),
    (
        "tracing-roots",
        "LangSmith 中 Chat 和三个 Agent 的根运行名是什么？",
        "根运行名分别是 intelligence_hub.chat、intelligence_hub.agent.image、intelligence_hub.agent.slides 和 intelligence_hub.agent.research。",
        "分别是 intelligence_hub.chat 以及 image、slides、research 三个 agent 根运行。",
        False,
    ),
    (
        "research-evidence",
        "深度研究报告对来源和不确定性有什么要求？",
        "研究报告必须保留可核验 URL，将证据映射到主题，并明确局限与尚未解决的问题。",
        "要提供可核验来源、证据映射，并说明局限和未解决问题。",
        False,
    ),
    (
        "research-fallback",
        "研究综合阶段超时后，安全降级报告能否编造来源？",
        "安全降级报告只能整理已经获得的真实搜索证据，不得编造 URL 或把未证实内容写成事实。",
        "不能，只能使用已经取得的真实证据。",
        False,
    ),
    (
        "alembic-policy",
        "数据库结构日常升级的唯一入口是什么？",
        "Alembic 是数据库结构的唯一日常升级入口，schema.sql 只作为空数据库参考。",
        "使用 Alembic；schema.sql 仅作参考。",
        False,
    ),
    (
        "health-endpoint",
        "本地 API 的健康检查地址是什么？",
        "本地开发时健康检查端点是 http://127.0.0.1:8000/api/health。",
        "http://127.0.0.1:8000/api/health。",
        False,
    ),
    (
        "ops-runbook-large",
        "后端与前端的核心验证命令分别是什么？",
        "后端运行 uv run ruff check . 和 uv run pytest -q；前端运行 npm run build 与 npm test -- --run。",
        "后端执行 Ruff 和 pytest，前端执行 build 和 Vitest。",
        True,
    ),
]


def _expanded_rag_examples() -> list[dict]:
    examples: list[dict] = []
    offsets = (1, 2, 4, 7, 11, 17, 26, 34)
    large_number = 0
    for index, (item_id, query, text, answer, is_large) in enumerate(_RAG_FACTS):
        distractors = [
            {
                "id": _RAG_FACTS[(index + offset) % len(_RAG_FACTS)][0],
                "text": _RAG_FACTS[(index + offset) % len(_RAG_FACTS)][2],
            }
            for offset in offsets
        ]
        inputs: dict = {
            "case_id": f"rag-expanded-{item_id}",
            "query": query,
            "documents": distractors,
        }
        relevant_id = item_id
        fixture = None
        if is_large:
            large_number += 1
            extension, mime_type = (
                ("docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
                ("pdf", "application/pdf"),
                ("md", "text/markdown"),
                ("docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
            )[large_number - 1]
            filename = f"rag-large-{large_number}.{extension}"
            relevant_id = f"attachment:{filename}:0"
            inputs["attachment_files"] = [
                {"key": filename, "filename": filename, "document_id": relevant_id}
            ]
            fixture = {
                "key": filename,
                "filename": filename,
                "mime_type": mime_type,
                "target_bytes": 15 * 1024 * 1024 + (large_number - 2) * 128 * 1024,
                "text": text,
            }
        else:
            inputs["documents"].insert(
                index % (len(distractors) + 1), {"id": item_id, "text": text}
            )
        example = {
            "inputs": inputs,
            "outputs": {
                "relevant_document_ids": [relevant_id],
                "reference_answer": answer,
            },
        }
        if fixture:
            example["attachment_fixture"] = fixture
        examples.append(example)
    return examples


RAG_EXAMPLES.extend(_expanded_rag_examples())


def _rag_stress_examples() -> list[dict]:
    """Add 50 query variants with independent candidate order and stable gold IDs."""

    variants = (
        "请只依据资料回答：{query}",
        "根据给出的项目文档，{query}",
        "我需要核对一个配置事实：{query}",
        "不要使用外部知识，直接说明：{query}",
        "请给出简短且可核验的回答：{query}",
        "从候选文档中找到依据后回答：{query}",
        "这是一次文档检索测试，请回答：{query}",
        "请先定位相关片段，再简洁说明：{query}",
        "以项目资料为唯一依据核实：{query}",
        "请回答下面的内部文档问题：{query}",
    )
    examples: list[dict] = []
    for index in range(50):
        fact_index = (index * 7 + 3) % len(_RAG_FACTS)
        item_id, query, text, answer, _ = _RAG_FACTS[fact_index]
        offsets = (2, 5, 9, 14, 21, 29, 37, 43)
        distractors = [
            {
                "id": _RAG_FACTS[(fact_index + offset + index) % len(_RAG_FACTS)][0],
                "text": _RAG_FACTS[(fact_index + offset + index) % len(_RAG_FACTS)][2],
            }
            for offset in offsets
            if _RAG_FACTS[(fact_index + offset + index) % len(_RAG_FACTS)][0] != item_id
        ][:8]
        insert_at = (index * 3) % (len(distractors) + 1)
        distractors.insert(insert_at, {"id": item_id, "text": text})
        examples.append(
            {
                "inputs": {
                    "case_id": f"rag-stress-{index + 1:03d}-{item_id}",
                    "query": variants[index % len(variants)].format(query=query),
                    "documents": distractors,
                },
                "outputs": {
                    "relevant_document_ids": [item_id],
                    "reference_answer": answer,
                },
            }
        )
    return examples


RAG_EXAMPLES.extend(_rag_stress_examples())


MCP_EXAMPLES = [
    {
        "inputs": {
            "case_id": "mcp-langsmith-evaluation",
            "query": "请联网搜索 LangSmith Python SDK 创建 dataset 并运行 evaluate 的官方方法",
        },
        "outputs": {
            "expected_topics": [
                {"id": "create_dataset", "text": "Client.create_dataset 创建数据集"},
                {"id": "create_examples", "text": "Client.create_examples 写入样本"},
                {"id": "evaluate", "text": "evaluate 或 aevaluate 运行实验"},
            ],
            "preferred_domains": ["docs.langchain.com"],
        },
    },
    {
        "inputs": {
            "case_id": "mcp-fastapi-streaming",
            "query": "请联网搜索 FastAPI StreamingResponse 官方文档，说明异步流式响应要点",
        },
        "outputs": {
            "expected_topics": [
                {"id": "streaming_response", "text": "StreamingResponse 用于流式响应"},
                {"id": "async_generator", "text": "可使用异步生成器逐块产出内容"},
                {"id": "media_type", "text": "需要设置合适的 media_type 或响应头"},
            ],
            "preferred_domains": ["fastapi.tiangolo.com", "www.starlette.io"],
        },
    },
    {
        "inputs": {
            "case_id": "mcp-pgvector-index",
            "query": "请联网搜索 pgvector 官方文档，比较 HNSW 和 IVFFlat 的索引取舍",
        },
        "outputs": {
            "expected_topics": [
                {"id": "hnsw", "text": "HNSW 的查询性能、构建速度与内存取舍"},
                {"id": "ivfflat", "text": "IVFFlat 的训练、构建和查询取舍"},
                {"id": "cosine", "text": "余弦距离运算符或对应 operator class"},
            ],
            "preferred_domains": ["github.com"],
        },
    },
]


MCP_EXAMPLES.extend(
    [
        {
            "inputs": {
                "case_id": "mcp-python-taskgroup",
                "query": "搜索 Python 官方文档，说明 asyncio.TaskGroup 的异常传播和取消语义",
            },
            "outputs": {
                "expected_topics": [
                    {"id": "group_wait", "text": "退出上下文时等待组内任务完成"},
                    {"id": "cancel_siblings", "text": "首个非取消异常会取消其余任务"},
                    {"id": "exception_group", "text": "异常最终组合为 ExceptionGroup"},
                ],
                "preferred_domains": ["docs.python.org"],
            },
        },
        {
            "inputs": {
                "case_id": "mcp-pydantic-validator",
                "query": "搜索 Pydantic v2 官方文档，比较 field_validator 和 model_validator",
            },
            "outputs": {
                "expected_topics": [
                    {"id": "field", "text": "field_validator 验证单个字段"},
                    {"id": "model", "text": "model_validator 验证整个模型数据"},
                    {"id": "modes", "text": "before after wrap 等验证模式"},
                ],
                "preferred_domains": ["docs.pydantic.dev"],
            },
        },
        {
            "inputs": {
                "case_id": "mcp-postgres-explain",
                "query": "搜索 PostgreSQL 官方文档，说明 EXPLAIN ANALYZE 与 BUFFERS 的用途和风险",
            },
            "outputs": {
                "expected_topics": [
                    {"id": "execute", "text": "ANALYZE 会实际执行查询"},
                    {"id": "timing", "text": "输出实际运行时间和行数"},
                    {"id": "buffers", "text": "BUFFERS 展示缓冲区命中和读写"},
                ],
                "preferred_domains": ["www.postgresql.org"],
            },
        },
        {
            "inputs": {
                "case_id": "mcp-redis-eviction",
                "query": "搜索 Redis 官方文档，比较 allkeys-lru、volatile-lru 和 noeviction",
            },
            "outputs": {
                "expected_topics": [
                    {"id": "allkeys", "text": "allkeys-lru 可从所有键中淘汰"},
                    {"id": "volatile", "text": "volatile-lru 只从设置过期时间的键中淘汰"},
                    {"id": "noeviction", "text": "noeviction 在达到上限后拒绝新增写入"},
                ],
                "preferred_domains": ["redis.io"],
            },
        },
        {
            "inputs": {
                "case_id": "mcp-compose-health",
                "query": "搜索 Docker Compose 官方文档，说明 healthcheck 与 depends_on condition service_healthy",
            },
            "outputs": {
                "expected_topics": [
                    {"id": "healthcheck", "text": "healthcheck 定义容器健康检查"},
                    {"id": "service_healthy", "text": "service_healthy 等待依赖通过健康检查"},
                    {"id": "startup_order", "text": "depends_on 控制服务创建和启动顺序"},
                ],
                "preferred_domains": ["docs.docker.com"],
            },
        },
        {
            "inputs": {
                "case_id": "mcp-kubernetes-probes",
                "query": "搜索 Kubernetes 官方文档，比较 startup、readiness 和 liveness probe",
            },
            "outputs": {
                "expected_topics": [
                    {"id": "startup", "text": "startup probe 保护慢启动容器"},
                    {"id": "readiness", "text": "readiness 失败会从服务端点移除 Pod"},
                    {"id": "liveness", "text": "liveness 失败会触发容器重启"},
                ],
                "preferred_domains": ["kubernetes.io"],
            },
        },
        {
            "inputs": {
                "case_id": "mcp-github-actions-cache",
                "query": "搜索 GitHub Actions 官方文档，说明 dependency caching 的 key、restore-keys 和命中行为",
            },
            "outputs": {
                "expected_topics": [
                    {"id": "key", "text": "key 用于缓存精确匹配"},
                    {"id": "restore", "text": "restore-keys 支持前缀部分匹配"},
                    {"id": "save", "text": "未命中时作业成功后创建新缓存"},
                ],
                "preferred_domains": ["docs.github.com"],
            },
        },
        {
            "inputs": {
                "case_id": "mcp-vue-lifecycle",
                "query": "搜索 Vue 3 官方文档，说明 onMounted、onUpdated 和 onUnmounted 的使用边界",
            },
            "outputs": {
                "expected_topics": [
                    {"id": "mounted", "text": "onMounted 在组件 DOM 创建后运行"},
                    {"id": "updated", "text": "onUpdated 在 DOM 更新后运行且应避免更新状态循环"},
                    {"id": "unmounted", "text": "onUnmounted 用于清理定时器或事件监听"},
                ],
                "preferred_domains": ["vuejs.org"],
            },
        },
        {
            "inputs": {
                "case_id": "mcp-vite-env",
                "query": "搜索 Vite 官方文档，说明 import.meta.env、VITE_ 前缀和敏感变量风险",
            },
            "outputs": {
                "expected_topics": [
                    {"id": "meta", "text": "import.meta.env 暴露环境常量"},
                    {"id": "prefix", "text": "只有 VITE_ 前缀变量默认暴露给客户端"},
                    {"id": "secret", "text": "VITE_ 变量会进入客户端包因而不能放密钥"},
                ],
                "preferred_domains": ["vite.dev"],
            },
        },
        {
            "inputs": {
                "case_id": "mcp-sqlalchemy-async",
                "query": "搜索 SQLAlchemy 2.0 官方文档，说明 AsyncSession 并发任务使用和 expire_on_commit",
            },
            "outputs": {
                "expected_topics": [
                    {"id": "session_per_task", "text": "每个并发任务使用独立 AsyncSession"},
                    {"id": "mutable", "text": "AsyncSession 是有状态事务对象不应跨任务共享"},
                    {"id": "expire", "text": "异步场景常设置 expire_on_commit False"},
                ],
                "preferred_domains": ["docs.sqlalchemy.org"],
            },
        },
        {
            "inputs": {
                "case_id": "mcp-alembic-autogenerate",
                "query": "搜索 Alembic 官方文档，说明 autogenerate 能检测什么以及为什么要人工审查",
            },
            "outputs": {
                "expected_topics": [
                    {"id": "compare", "text": "autogenerate 比较数据库结构与模型 metadata"},
                    {"id": "candidate", "text": "生成的是候选迁移脚本"},
                    {"id": "manual_review", "text": "必须人工审查和修正遗漏或误判"},
                ],
                "preferred_domains": ["alembic.sqlalchemy.org"],
            },
        },
        {
            "inputs": {
                "case_id": "mcp-minio-presigned",
                "query": "搜索 MinIO Python SDK 官方文档，说明 presigned_get_object 的过期时间和用途",
            },
            "outputs": {
                "expected_topics": [
                    {"id": "temporary", "text": "生成临时授权的 GET URL"},
                    {"id": "expiry", "text": "expires 参数控制 URL 有效期"},
                    {"id": "credentials", "text": "使用者无需直接获得存储凭据"},
                ],
                "preferred_domains": ["min.io", "docs.min.io"],
            },
        },
        {
            "inputs": {
                "case_id": "mcp-owasp-upload",
                "query": "搜索 OWASP File Upload Cheat Sheet，整理扩展名、内容类型、文件名和存储位置建议",
            },
            "outputs": {
                "expected_topics": [
                    {"id": "allowlist", "text": "使用允许列表校验扩展名并验证文件类型"},
                    {"id": "filename", "text": "重命名文件而非信任用户文件名"},
                    {"id": "storage", "text": "文件存放在 Webroot 之外或独立主机"},
                ],
                "preferred_domains": ["cheatsheetseries.owasp.org"],
            },
        },
        {
            "inputs": {
                "case_id": "mcp-wcag-contrast",
                "query": "搜索 W3C WCAG 2.2 官方材料，说明普通文本与大文本的最低对比度",
            },
            "outputs": {
                "expected_topics": [
                    {"id": "normal", "text": "普通文本最低对比度为 4.5 比 1"},
                    {"id": "large", "text": "大文本最低对比度为 3 比 1"},
                    {"id": "definition", "text": "大文本字号和粗体阈值定义"},
                ],
                "preferred_domains": ["www.w3.org"],
            },
        },
        {
            "inputs": {
                "case_id": "mcp-mdn-sse",
                "query": "搜索 MDN Server-sent events 文档，说明 EventSource、事件格式和自动重连",
            },
            "outputs": {
                "expected_topics": [
                    {"id": "eventsource", "text": "EventSource 建立单向服务器事件连接"},
                    {"id": "format", "text": "text/event-stream 使用 data event id retry 字段"},
                    {"id": "reconnect", "text": "连接关闭时客户端默认会自动重连"},
                ],
                "preferred_domains": ["developer.mozilla.org"],
            },
        },
        {
            "inputs": {
                "case_id": "mcp-langchain-structured",
                "query": "搜索 LangChain Python 官方文档，比较 provider-native 和 tool-calling structured output",
            },
            "outputs": {
                "expected_topics": [
                    {"id": "provider", "text": "ProviderStrategy 使用模型供应商原生结构化输出"},
                    {"id": "tool", "text": "ToolStrategy 通过工具调用获得结构化结果"},
                    {"id": "validation", "text": "结构化响应按 schema 验证"},
                ],
                "preferred_domains": ["docs.langchain.com"],
            },
        },
        {
            "inputs": {
                "case_id": "mcp-dashscope-streaming",
                "query": "搜索阿里云百炼 OpenAI 兼容接口官方文档，说明流式输出和 thinking_content 的读取方式",
            },
            "outputs": {
                "expected_topics": [
                    {"id": "stream", "text": "设置 stream true 获取增量响应"},
                    {"id": "content", "text": "从 choices delta content 读取回答内容"},
                    {
                        "id": "thinking",
                        "text": "深度思考模型可返回 reasoning_content 或 thinking_content",
                    },
                ],
                "preferred_domains": ["help.aliyun.com"],
            },
        },
    ]
)


SLIDES_EXAMPLES = [
    *[
        {
            "inputs": {"task": "intent", "case_id": case_id, "text": text, **flags},
            "outputs": {"intent": intent},
        }
        for case_id, text, flags, intent in [
            ("intent-create-basic", "为董事会制作一份年度复盘演示", {}, "CREATE"),
            ("intent-create-adjust", "做一个关于如何调整库存策略的新演示", {}, "CREATE"),
            ("intent-create-continue-theme", "以‘继续增长’为主题生成一份演示", {}, "CREATE"),
            (
                "intent-create-explicit",
                "修改行业格局是本演示的主题",
                {"requested": "CREATE"},
                "CREATE",
            ),
            ("intent-create-en", "Create a presentation about retrieval evaluation", {}, "CREATE"),
            (
                "intent-modify-slide",
                "把第 3 页改成新的路线图",
                {"has_source_artifact": True},
                "MODIFY",
            ),
            (
                "intent-modify-existing",
                "调整这份现有演示的结论页",
                {"has_source_artifact": True},
                "MODIFY",
            ),
            (
                "intent-modify-explicit",
                "优化排版",
                {"requested": "MODIFY", "has_source_artifact": True},
                "MODIFY",
            ),
            (
                "intent-modify-en",
                "Edit slide 2 and shorten the copy",
                {"has_source_artifact": True},
                "MODIFY",
            ),
            ("intent-modify-cover", "替换封面标题", {"has_source_artifact": True}, "MODIFY"),
            ("intent-resume-basic", "继续之前的演示生成", {"has_source_run": True}, "RESUME"),
            ("intent-resume-failure", "从失败处恢复", {"has_source_run": True}, "RESUME"),
            (
                "intent-resume-explicit",
                "继续",
                {"requested": "RESUME", "has_source_run": True},
                "RESUME",
            ),
            (
                "intent-resume-en",
                "Resume the interrupted presentation run",
                {"has_source_run": True},
                "RESUME",
            ),
            ("intent-resume-run", "恢复该运行", {"has_source_run": True}, "RESUME"),
        ]
    ],
    {
        "inputs": {
            "task": "quality",
            "case_id": "slides-product-review",
            "text": (
                "为产品负责人制作一份 5 页以内的 Intelligence Hub MVP 复盘演示，"
                "突出目标、结果、问题、改进和下一步。"
            ),
            "audience": "产品与工程负责人",
            "max_total_pages": 5,
        },
        "outputs": {
            "required_content": ["目标", "结果", "问题", "改进", "下一步"],
        },
    },
    {
        "inputs": {
            "task": "quality",
            "case_id": "slides-technical-briefing",
            "text": (
                "生成一份 6 页以内的 RAG 评估技术简报，面向工程团队，"
                "讲清 Recall@5、MRR、Faithfulness、实验流程与发布门槛。"
            ),
            "audience": "AI 工程团队",
            "max_total_pages": 6,
        },
        "outputs": {
            "required_content": ["Recall@5", "MRR", "Faithfulness", "实验流程", "发布门槛"],
        },
    },
]


SLIDES_EXAMPLES.extend(
    [
        {
            "inputs": {
                "task": "intent",
                "case_id": "intent-create-hard-modify-word",
                "text": "请新建一份关于如何修改客户流失策略的演示",
            },
            "outputs": {"intent": "CREATE"},
        },
        {
            "inputs": {
                "task": "intent",
                "case_id": "intent-modify-continue-word",
                "text": "继续优化第 4 页的图表层级",
                "has_source_artifact": True,
            },
            "outputs": {"intent": "MODIFY"},
        },
        {
            "inputs": {
                "task": "intent",
                "case_id": "intent-resume-colloquial",
                "text": "接着上次中断的 PPT 任务往下跑",
                "has_source_run": True,
            },
            "outputs": {"intent": "RESUME"},
        },
        {
            "inputs": {
                "task": "quality",
                "case_id": "slides-executive-strategy",
                "text": "制作一份 7 页以内的 AI 产品年度策略演示，突出市场判断、用户问题、战略选择、资源投入、风险和季度里程碑。",
                "audience": "公司管理层",
                "max_total_pages": 7,
            },
            "outputs": {
                "required_content": [
                    "市场判断",
                    "用户问题",
                    "战略选择",
                    "资源投入",
                    "风险",
                    "季度里程碑",
                ]
            },
        },
        {
            "inputs": {
                "task": "quality",
                "case_id": "slides-incident-review",
                "text": "生成一份 6 页以内的生产事故复盘，覆盖影响范围、时间线、根因、处置过程、长期修复和责任人。不得编造损失数字。",
                "audience": "工程与业务负责人",
                "max_total_pages": 6,
            },
            "outputs": {
                "required_content": [
                    "影响范围",
                    "时间线",
                    "根因",
                    "处置过程",
                    "长期修复",
                    "责任人",
                ]
            },
        },
        {
            "inputs": {
                "task": "quality",
                "case_id": "slides-sales-proposal",
                "text": "为潜在企业客户制作 7 页以内的 Intelligence Hub 方案演示，讲清客户挑战、解决方案、核心能力、部署方式、安全边界、试点计划和成功指标。",
                "audience": "客户 CIO 与采购团队",
                "max_total_pages": 7,
            },
            "outputs": {
                "required_content": [
                    "客户挑战",
                    "解决方案",
                    "核心能力",
                    "部署方式",
                    "安全边界",
                    "试点计划",
                    "成功指标",
                ]
            },
        },
        {
            "inputs": {
                "task": "quality",
                "case_id": "slides-team-training",
                "text": "生成 6 页以内的团队培训演示，覆盖 RAG 基础、检索指标、生成指标、失败案例、调试流程和上线检查。",
                "audience": "刚接触 LLM 应用的工程师",
                "max_total_pages": 6,
            },
            "outputs": {
                "required_content": [
                    "RAG 基础",
                    "检索指标",
                    "生成指标",
                    "失败案例",
                    "调试流程",
                    "上线检查",
                ]
            },
        },
        {
            "inputs": {
                "task": "quality",
                "case_id": "slides-architecture-decision",
                "text": "制作 7 页以内的技术选型评审演示，比较 SSE 与 WebSocket，覆盖需求约束、方案原理、可靠性、扩展性、运维成本、安全风险和推荐结论。",
                "audience": "架构评审委员会",
                "max_total_pages": 7,
            },
            "outputs": {
                "required_content": [
                    "需求约束",
                    "方案原理",
                    "可靠性",
                    "扩展性",
                    "运维成本",
                    "安全风险",
                    "推荐结论",
                ]
            },
        },
    ]
)


RESEARCH_EXAMPLES = [
    {
        "inputs": {
            "case_id": "research-langsmith-offline-eval",
            "question": (
                "研究 LangSmith 离线评估的完整流程。要求说明 dataset、target、evaluator、"
                "experiment 的关系，区分代码指标和 LLM-as-judge，给出适合 RAG 的实施建议，"
                "并明确局限。"
            ),
        },
        "outputs": {
            "requirements": [
                {"id": "r1", "text": "说明 dataset、target、evaluator、experiment 的关系"},
                {"id": "r2", "text": "区分代码指标与 LLM-as-judge"},
                {"id": "r3", "text": "给出 RAG 实施建议"},
                {"id": "r4", "text": "明确局限"},
            ],
            "topics": [
                {"id": "t1", "text": "数据集与样本设计"},
                {"id": "t2", "text": "目标函数与实验"},
                {"id": "t3", "text": "检索和生成评估指标"},
                {"id": "t4", "text": "结果分析与迭代"},
            ],
            "checklist": [
                {"id": "c1", "text": "执行摘要"},
                {"id": "c2", "text": "研究方法或来源范围"},
                {"id": "c3", "text": "分主题发现"},
                {"id": "c4", "text": "局限或未解决问题"},
                {"id": "c5", "text": "可核验来源"},
            ],
        },
    },
    {
        "inputs": {
            "case_id": "research-pgvector-index",
            "question": (
                "研究 pgvector 中 HNSW 与 IVFFlat 的选型。要求比较查询性能、构建成本、内存、"
                "召回率和过滤查询，给出小规模与百万级数据的建议，并标明证据和不确定性。"
            ),
        },
        "outputs": {
            "requirements": [
                {"id": "r1", "text": "比较查询性能、构建成本与内存"},
                {"id": "r2", "text": "比较召回率和过滤查询"},
                {"id": "r3", "text": "分别给出小规模和百万级数据建议"},
                {"id": "r4", "text": "标明证据和不确定性"},
            ],
            "topics": [
                {"id": "t1", "text": "HNSW 工作特性"},
                {"id": "t2", "text": "IVFFlat 工作特性"},
                {"id": "t3", "text": "数据规模和资源取舍"},
                {"id": "t4", "text": "过滤查询与调参"},
            ],
            "checklist": [
                {"id": "c1", "text": "执行摘要"},
                {"id": "c2", "text": "比较方法或资料范围"},
                {"id": "c3", "text": "分主题比较"},
                {"id": "c4", "text": "选型建议"},
                {"id": "c5", "text": "局限与可核验来源"},
            ],
        },
    },
]


def _research_case(case_id: str, question: str, requirements: list[str], topics: list[str]) -> dict:
    return {
        "inputs": {"case_id": case_id, "question": question},
        "outputs": {
            "requirements": [
                {"id": f"r{index}", "text": text} for index, text in enumerate(requirements, 1)
            ],
            "topics": [{"id": f"t{index}", "text": text} for index, text in enumerate(topics, 1)],
            "checklist": [
                {"id": "c1", "text": "执行摘要"},
                {"id": "c2", "text": "研究方法或来源范围"},
                {"id": "c3", "text": "分主题发现与证据"},
                {"id": "c4", "text": "建议、局限或未解决问题"},
                {"id": "c5", "text": "可核验来源"},
            ],
        },
    }


RESEARCH_EXAMPLES.extend(
    [
        _research_case(
            "research-fastapi-streaming",
            "研究 FastAPI 生产级流式响应。要求比较 StreamingResponse 与 SSE，说明断连取消、反向代理缓冲和错误处理，并给出部署检查单。",
            [
                "比较 StreamingResponse 与 SSE",
                "说明断连与取消",
                "分析代理缓冲和错误处理",
                "给出部署检查单",
            ],
            ["FastAPI 流式机制", "SSE 事件协议", "取消与异常", "代理和生产部署"],
        ),
        _research_case(
            "research-kubernetes-probes",
            "研究 Kubernetes 三类健康探针。要求比较 startup、readiness、liveness 的语义，分析错误配置风险，给出慢启动 API 的参数建议并说明局限。",
            ["比较三类探针语义", "分析错误配置风险", "给出慢启动 API 参数建议", "说明局限"],
            ["Startup Probe", "Readiness Probe", "Liveness Probe", "阈值与故障场景"],
        ),
        _research_case(
            "research-postgres-indexes",
            "研究 PostgreSQL B-tree、GIN 与 BRIN 索引选型。要求比较适用查询、写入成本和空间，讨论组合索引顺序，给出日志与 JSONB 场景建议。",
            ["比较适用查询", "比较写入和空间成本", "讨论组合索引顺序", "给出日志与 JSONB 建议"],
            ["B-tree", "GIN", "BRIN", "组合索引与执行计划"],
        ),
        _research_case(
            "research-redis-eviction",
            "研究 Redis 内存淘汰策略。要求比较 LRU、LFU、TTL 与 noeviction，说明近似算法和 maxmemory，给出缓存与持久数据混用风险建议。",
            ["比较主要淘汰策略", "说明近似算法", "解释 maxmemory 行为", "给出数据混用风险建议"],
            ["LRU 与 LFU", "TTL 策略", "内存上限", "缓存架构风险"],
        ),
        _research_case(
            "research-rag-chunking",
            "研究 RAG 文档分块策略。要求比较固定长度、递归和语义分块，分析 chunk size 与 overlap 对召回和成本的影响，给出中文长文档实验方案。",
            ["比较三类分块方法", "分析尺寸与重叠影响", "兼顾召回和成本", "给出中文文档实验方案"],
            ["固定与递归分块", "语义分块", "召回和上下文成本", "实验与评估"],
        ),
        _research_case(
            "research-sse-websocket",
            "研究 SSE 与 WebSocket 的实时通信选型。要求比较方向性、重连、代理兼容和扩展成本，讨论鉴权与背压，并给出 LLM 流式输出建议。",
            ["比较协议能力", "比较重连和代理兼容", "讨论鉴权与背压", "给出 LLM 流式输出建议"],
            ["SSE 协议", "WebSocket 协议", "可靠性与扩展", "安全与应用选型"],
        ),
        _research_case(
            "research-owasp-upload",
            "研究 Web 文件上传安全。要求覆盖扩展名和 MIME 验证、文件名与路径、恶意内容扫描、存储隔离，并给出 20MB 上传服务的检查清单。",
            ["覆盖类型验证", "覆盖文件名与路径安全", "说明扫描和存储隔离", "给出上传服务检查清单"],
            ["允许列表与魔数", "文件名和路径", "恶意内容防护", "隔离存储与权限"],
        ),
        _research_case(
            "research-wcag-dashboard",
            "研究 WCAG 2.2 在数据仪表板中的应用。要求说明文本和非文本对比度、键盘操作、焦点可见性和动态图表替代信息，给出审计步骤。",
            ["说明对比度要求", "说明键盘与焦点要求", "覆盖动态图表替代信息", "给出审计步骤"],
            ["颜色与对比度", "键盘可访问性", "焦点与状态", "图表语义和测试"],
        ),
        _research_case(
            "research-docker-startup",
            "研究 Docker Compose 多服务启动依赖。要求区分启动顺序与就绪，说明 healthcheck、depends_on 和重启策略，给出 API 加数据库的可靠配置建议。",
            [
                "区分启动与就绪",
                "说明 healthcheck",
                "说明 depends_on 与重启",
                "给出 API 与数据库建议",
            ],
            ["Compose 依赖", "容器健康检查", "失败与重启", "应用启动韧性"],
        ),
        _research_case(
            "research-github-cache",
            "研究 GitHub Actions 依赖缓存。要求解释 key 与 restore-keys、缓存作用域和淘汰，比较 setup-* 内置缓存与 actions/cache，并给出 Python/Node 矩阵建议。",
            ["解释匹配逻辑", "说明作用域与淘汰", "比较两种缓存方式", "给出矩阵构建建议"],
            ["缓存键设计", "缓存生命周期", "官方 setup action", "矩阵与供应链风险"],
        ),
        _research_case(
            "research-python-concurrency",
            "研究 Python asyncio 结构化并发。要求比较 TaskGroup 与 gather 的错误传播、取消和结果收集，讨论超时嵌套，并给出 Agent 并行搜索建议。",
            ["比较错误传播", "比较取消语义", "讨论超时嵌套", "给出 Agent 并行建议"],
            ["TaskGroup", "gather", "取消与 ExceptionGroup", "timeout 和工程模式"],
        ),
        _research_case(
            "research-pydantic-validation",
            "研究 Pydantic v2 结构化输出验证。要求比较 field/model validator 和 before/after/wrap，说明严格模式与错误处理，给出 LLM 输出修复策略。",
            ["比较验证器范围", "比较验证模式", "说明严格模式和错误", "给出 LLM 输出修复策略"],
            ["字段验证", "模型验证", "严格性与错误模型", "结构化输出恢复"],
        ),
        _research_case(
            "research-sqlalchemy-async",
            "研究 SQLAlchemy 2.0 异步会话管理。要求说明 session-per-task、事务边界、expire_on_commit 和惰性加载风险，给出 FastAPI 生命周期建议。",
            ["说明并发会话规则", "说明事务边界", "解释提交后过期和惰性加载", "给出 FastAPI 建议"],
            ["AsyncSession 生命周期", "事务管理", "对象加载策略", "FastAPI 集成"],
        ),
        _research_case(
            "research-alembic-migrations",
            "研究 Alembic 生产迁移流程。要求说明 autogenerate 局限、升级与回滚、零停机兼容步骤和数据迁移，给出发布门禁建议。",
            ["说明自动生成局限", "覆盖升级和回滚", "说明零停机兼容", "给出发布门禁"],
            ["Schema 差异检测", "版本与回滚", "Expand-contract", "数据迁移和验证"],
        ),
        _research_case(
            "research-minio-storage",
            "研究 MinIO/S3 兼容对象存储的应用集成。要求说明预签名 URL、分片上传、版本与生命周期、服务端加密，并给出本地到生产迁移建议。",
            ["说明预签名 URL", "说明分片上传", "覆盖版本生命周期与加密", "给出迁移建议"],
            ["对象访问授权", "大文件上传", "数据治理", "部署和兼容性"],
        ),
        _research_case(
            "research-vue-performance",
            "研究 Vue 3 长列表与流式 Markdown 页面的性能优化。要求覆盖响应式开销、虚拟列表、批量更新和测量工具，给出渐进优化方案。",
            ["分析响应式开销", "覆盖虚拟列表", "说明流式批量更新", "给出测量与优化方案"],
            ["Vue 响应式", "列表虚拟化", "渲染调度", "性能测量"],
        ),
        _research_case(
            "research-vite-security",
            "研究 Vite 前端环境变量安全。要求说明 VITE_ 暴露规则、构建时替换、source map 风险和服务端密钥边界，给出检查方案。",
            ["说明暴露规则", "解释构建时替换", "分析 source map 风险", "给出密钥检查方案"],
            ["环境变量加载", "客户端 bundle", "Source map", "密钥治理"],
        ),
        _research_case(
            "research-llm-judge-bias",
            "研究 LLM-as-a-judge 的可靠性。要求分析位置、长度和自偏好偏差，比较点式与成对评审，说明校准方法，并给出人工复核门槛。",
            ["分析主要偏差", "比较评审范式", "说明校准方法", "给出人工复核门槛"],
            ["评审偏差", "Pointwise 与 pairwise", "一致性和校准", "人机联合评估"],
        ),
        _research_case(
            "research-hybrid-retrieval",
            "研究 RAG 混合检索与重排。要求比较稀疏和稠密召回、融合算法与 cross-encoder 重排，分析延迟成本，并给出离线实验设计。",
            ["比较两类召回", "说明融合与重排", "分析延迟成本", "给出离线实验设计"],
            ["BM25 稀疏检索", "向量检索", "融合与 reranker", "Recall/MRR 实验"],
        ),
        _research_case(
            "research-agent-checkpoint",
            "研究长任务 Agent 的 checkpoint 与恢复。要求说明状态持久化、幂等副作用、人工中断和版本兼容，给出产物去重方案。",
            ["说明状态持久化", "处理幂等副作用", "覆盖中断和版本兼容", "给出产物去重方案"],
            ["检查点模型", "幂等性", "Human-in-the-loop", "恢复与产物登记"],
        ),
        _research_case(
            "research-mcp-security",
            "研究远程 MCP 服务安全。要求分析认证授权、工具参数验证、提示注入、数据外泄和审计，给出搜索 MCP 的最小权限建议。",
            ["分析认证授权", "覆盖参数验证和注入", "分析数据外泄与审计", "给出最小权限建议"],
            ["MCP 信任边界", "工具输入安全", "数据保护", "日志和权限"],
        ),
        _research_case(
            "research-citation-verification",
            "研究 AI 报告引用验证。要求区分来源存在、主张支持和来源质量，说明 URL 归一化与重复引用，给出自动加人工的审核流程。",
            ["区分三层引用质量", "说明 URL 归一化", "处理重复和错配引用", "给出审核流程"],
            ["链接有效性", "Entailment 支持", "来源权威性", "自动与人工审计"],
        ),
        _research_case(
            "research-deep-workflow",
            "研究深度研究 Agent 的工作流设计。要求覆盖需求拆解、并行搜索、证据去重、综合写作和预算控制，给出失败降级与评估方案。",
            ["覆盖需求拆解与搜索", "说明证据去重", "说明综合与预算控制", "给出降级和评估方案"],
            ["规划与主题分解", "搜索和证据管理", "报告综合", "预算、降级与指标"],
        ),
    ]
)


DATASETS = {
    "rag": DatasetSpec(
        "intelligence-hub-rag-v3",
        "100 document retrieval and faithfulness cases with 15 MiB PDF, Markdown, and Word files.",
        RAG_EXAMPLES,
    ),
    "mcp": DatasetSpec(
        "intelligence-hub-mcp-search-v2",
        "20 Tavily MCP search relevance, coverage, and citation accuracy cases.",
        MCP_EXAMPLES,
    ),
    "slides": DatasetSpec(
        "intelligence-hub-slides-v2",
        "25 presentation intent routing and Qwen-scored generation quality cases.",
        SLIDES_EXAMPLES,
    ),
    "research": DatasetSpec(
        "intelligence-hub-research-v2",
        "25 Deep Research requirement capture, coverage, redundancy, and checklist cases.",
        RESEARCH_EXAMPLES,
    ),
}


def build_large_docx_attachment(text: str, target_bytes: int) -> bytes:
    """Build a valid DOCX near the requested size without inflating extracted text."""

    document = WordDocument()
    document.add_paragraph(text)
    output = BytesIO()
    document.save(output)
    base = output.getvalue()
    padding_size = max(1, target_bytes - len(base) - 256)
    padded = BytesIO(base)
    with zipfile.ZipFile(padded, "a", compression=zipfile.ZIP_STORED) as archive:
        archive.writestr(
            "word/media/evaluation-padding.bin",
            b"IH-EVAL-PADDING\x00" * (padding_size // 16) + b"0" * (padding_size % 16),
            compress_type=zipfile.ZIP_STORED,
        )
    return padded.getvalue()


def build_large_markdown_attachment(text: str, target_bytes: int) -> bytes:
    """Build a valid large UTF-8 Markdown file with one relevant opening fact."""

    header = f"# Intelligence Hub evaluation fixture\n\n{text}\n\n<!--\n".encode()
    footer = b"\n-->\n"
    padding = (b"evaluation-padding-0123456789abcdef\n" * 4096)
    repeats, remainder = divmod(max(0, target_bytes - len(header) - len(footer)), len(padding))
    return header + padding * repeats + padding[:remainder] + footer


def build_large_pdf_attachment(text: str, target_bytes: int) -> bytes:
    """Build a valid one-page PDF with extractable text and an uncompressed attachment."""

    base = BytesIO()
    pdf = canvas.Canvas(base, pagesize=(612, 792), pageCompression=0)
    font_name = "STSong-Light"
    pdfmetrics.registerFont(UnicodeCIDFont(font_name))
    pdf.setFont(font_name, 11)
    cursor_y = 740
    current = ""
    for character in text:
        candidate = current + character
        if pdf.stringWidth(candidate, font_name, 11) > 500:
            pdf.drawString(50, cursor_y, current)
            cursor_y -= 18
            current = character
        else:
            current = candidate
    if current:
        pdf.drawString(50, cursor_y, current)
    pdf.save()
    reader_data = base.getvalue()
    writer = PdfWriter()
    writer.append(BytesIO(reader_data))
    preliminary = BytesIO()
    writer.write(preliminary)
    padding_size = max(1, target_bytes - len(preliminary.getvalue()) - 512)
    writer.add_attachment("evaluation-padding.bin", b"P" * padding_size)
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def build_large_attachment(fixture: dict) -> bytes:
    filename = str(fixture["filename"])
    text = str(fixture["text"])
    target_bytes = int(fixture["target_bytes"])
    if filename.endswith(".docx"):
        return build_large_docx_attachment(text, target_bytes)
    if filename.endswith(".pdf"):
        return build_large_pdf_attachment(text, target_bytes)
    if filename.endswith(".md"):
        return build_large_markdown_attachment(text, target_bytes)
    raise ValueError(f"不支持的评估附件类型：{filename}")


def sync_datasets(client: Client) -> list[tuple[str, int]]:
    """Create or idempotently upsert all versioned LangSmith datasets."""

    synced: list[tuple[str, int]] = []
    for spec in DATASETS.values():
        dataset = (
            client.read_dataset(dataset_name=spec.name)
            if client.has_dataset(dataset_name=spec.name)
            else client.create_dataset(dataset_name=spec.name, description=spec.description)
        )
        examples = []
        attachment_examples = []
        existing_ids = {
            str(example.id) for example in client.list_examples(dataset_id=dataset.id)
        }
        dataset_version = spec.name.rsplit("-", 1)[-1]
        for raw in spec.examples:
            case_id = raw["inputs"]["case_id"]
            fixture = raw.get("attachment_fixture")
            example = {
                "id": uuid5(NAMESPACE_URL, f"{spec.name}/{case_id}"),
                "inputs": raw["inputs"],
                "outputs": raw["outputs"],
                "metadata": {
                    "case_id": case_id,
                    "dataset_version": dataset_version,
                    "large_attachment": bool(fixture),
                },
            }
            if fixture:
                data = build_large_attachment(fixture)
                example["attachments"] = {
                    fixture["key"]: {
                        "mime_type": fixture["mime_type"],
                        "data": data,
                    }
                }
                example["metadata"]["attachment_size_bytes"] = len(data)
                target_collection = attachment_examples
            else:
                target_collection = examples
            if str(example["id"]) in existing_ids:
                client.update_example(
                    example["id"],
                    inputs=example["inputs"],
                    outputs=example["outputs"],
                    metadata=example["metadata"],
                    attachments=example.get("attachments"),
                )
            else:
                target_collection.append(example)
        if examples:
            client.create_examples(dataset_id=dataset.id, examples=examples, max_concurrency=1)
        for example in attachment_examples:
            client.create_examples(dataset_id=dataset.id, examples=[example], max_concurrency=1)
        synced.append((spec.name, len(spec.examples)))
    return synced
