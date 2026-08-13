# Intelligence Hub

Intelligence Hub 是一个面向个人工作区的 ChatGPT 风格 Agent Hub。当前仓库已完成 `docs/tasks.md` 中的 P0 MVP：持久化多轮 Chat、文件与联网上下文、Skill、Memory，以及图片、演示文稿和深度研究三个 Work Agent。

Work 模式的目标是完成一项任务并产出一个可查看、可下载的 Artifact（产物）。Artifact 可以是图片、研究报告、PPT/PPTX 演示文稿等；阶段进度、思考和工具调用都是过程信息，最终交付以产物为准。

## 已实现能力

- 会话新建、切换、改名、删除、搜索与刷新恢复；回答支持 Markdown、思考区、工具详情、停止、重试、自动标题和单个推荐问题。
- 上传 `txt`、`md`、`pdf`、`docx`、`png`、`jpg`、`jpeg`、`webp`；单文件上限 20 MB、单次最多 3 个。文档支持定位、分块、Qwen Embedding 与 PostgreSQL/pgvector 相似度检索，图片走多模态输入。
- 显式联网请求通过 Tavily Remote MCP 搜索，普通问答不会自动搜索；文件和网页来源均持久化展示。
- Skill 完整 CRUD、启停、选择器显式调用、任务自动匹配和不可变调用快照；Chat 与 Work 均支持多选 Skill。
- 单份用户记忆摘要、总开关、对话“记住/忘记”、每轮 System Prompt 注入，以及闲置 30 分钟后的游标式安全提炼。
- 图片 Agent：LangChain 结构化 `ImageBrief`、参考图、受控 Qwen Image 调用、预览/下载/重试。
- 演示 Agent：LangGraph 大纲中断确认、LangChain 结构化页面、PPTX 生成、定向修改、版本链和 PostgreSQL 检查点恢复。
- 研究 Agent：外层 LangGraph、共享搜索/总时长预算、Deep Agents 证据子 Agent、URL/引用复验和 Markdown 产物。
- 统一的 `agent_runs`、阶段事件、脱敏工具记录与 Artifact 下载接口；本地文件和 MinIO 两种存储适配。
- 手机号/密码登录、管理员/普通用户 RBAC，以及会话、文件、任务、Skill、Memory 和设置的用户级数据隔离；暂不提供独立管理端。

## 技术结构

```text
frontend/                 Vue 3 + TypeScript + Vite + Pinia
backend/app/api/          FastAPI REST 与 SSE 路由
backend/app/chat/         持久化 Chat 编排
backend/app/agents/       LangChain / LangGraph / Deep Agents 工作流
backend/app/files/        文件校验、提取、检索与存储适配
backend/app/skills/       Skill 选择与快照
backend/app/memory/       用户记忆摘要、对话命令与闲置提炼
backend/migrations/       PostgreSQL + pgvector Alembic 迁移
docs/                     需求、架构、任务和验收记录
storage/                  本地上传与产物（内容不会提交）
```

## 环境要求

- Node.js 20.19+ 或 22.12+
- Python 3.12+
- [uv](https://docs.astral.sh/uv/)
- Docker（本地 PostgreSQL + pgvector）

## 本地启动

在仓库根目录复制配置：

```powershell
Copy-Item .env.example .env
```

启动 PostgreSQL 并执行迁移：

```powershell
docker compose up -d postgres minio
Set-Location backend
uv sync --dev
uv run alembic upgrade head
```

启动 API：

```powershell
Set-Location backend
uv run uvicorn app.main:app --reload --env-file ../.env
```

另开终端启动 Web：

```powershell
Set-Location frontend
npm install
npm run dev
```

打开 <http://127.0.0.1:5173>。健康检查为 <http://127.0.0.1:8000/api/health>，OpenAPI 文档为 <http://127.0.0.1:8000/docs>。

迁移会初始化 21 个账号：`13700000001` 至 `13700000020` 均为普通用户，`13900000001` 为管理员，初始密码统一为 `12345678`。生产使用前应更换初始密码策略，并为 `AUTH_SECRET_KEY` 配置独立随机值。

MinIO API 默认监听 <http://127.0.0.1:9000>，管理控制台为 <http://127.0.0.1:9001>。本地默认账号和密码均为 `minioadmin`；后端首次保存文件时会自动创建 `intelligence-hub-agents` bucket。

Alembic 是数据库结构的唯一日常升级入口。`sql/schema.sql` 是空数据库的完整参考结构，`sql/data.sql` 是迁移后可选的幂等演示数据；不要在同一个数据库上混用参考建表脚本与 Alembic。

## 服务端配置

密钥只从后端环境读取，不会由 API 返回或进入前端包。常用变量如下，完整默认值见 `.env.example`。

| 变量 | 用途 |
| --- | --- |
| `DATABASE_URL` | SQLAlchemy 异步 PostgreSQL 地址；LangGraph 会自动转换为 psycopg 地址 |
| `AUTH_SECRET_KEY` / `AUTH_TOKEN_TTL_MINUTES` | 登录令牌签名密钥与有效期；生产环境必须显式配置密钥 |
| `DASHSCOPE_API_KEY` | Qwen Chat、Vision、Embedding 与 Image |
| `QWEN_*_MODEL` | 分别覆盖 Chat、Work、Vision、Embedding 和图片模型 |
| `QWEN_THINKING_EFFORT` | 默认思考强度，可选 `none`、`low`、`medium`、`high`，默认 `medium` |
| `TAVILY_API_KEY` / `TAVILY_MCP_URL` | Tavily Remote MCP 联网搜索 |
| `LANGSMITH_TRACING` / `LANGSMITH_API_KEY` / `LANGSMITH_PROJECT` | Chat 与三个 Agent 的链路追踪和离线评估 |
| `STORAGE_BACKEND` | `local` 或 `minio` |
| `STORAGE_PATH` | 本地上传与产物根目录 |
| `MINIO_*` | MinIO 端点、凭据、桶和 TLS 开关 |
| `RESEARCH_MAX_SEARCHES` | 单次研究共享搜索预算，默认 4 |
| `RESEARCH_TIMEOUT_SECONDS` | 研究外层总超时，默认 120 秒 |
| `MAX_UPLOAD_BYTES` / `MAX_IMAGE_PIXELS` | 上传字节和图片像素上限 |

未配置 `DASHSCOPE_API_KEY` 时，Chat 与图片 Agent 使用确定性的本地演示输出，演示 Agent 仍会生成有效 PPTX。未配置 Tavily 时，联网 Chat 会明确显示工具失败，研究 Agent 会输出“待配置”报告，不会编造来源。配置凭据后会启用真实 Qwen 与 Tavily 链路。

如果不需要 LangSmith，请保持 `LANGSMITH_TRACING=false`；启用时还需在服务端配置 `LANGSMITH_API_KEY` 和项目名。

## 使用主流程

1. 在 Chat 中连续提问；点击回答末尾的推荐问题只会填充输入框。
2. 用输入框左下角的 `＋` 上传或选择文件；发送后，本轮使用的文件和定位会保留在消息中。
3. 只有明确写出“联网搜索/上网查找/search the web”等请求时才调用 Tavily。
4. 在设置页管理 Skill、Memory、联网开关和外观；也可以在 Chat 中说“请记住……”或“请忘记……”。
5. 新建会话时先选择 Chat 或 Work；选择模式不会立即落库，发送第一句话后才以该内容命名并创建会话。创建后类型不可切换；两种会话统一显示在侧栏，但不共用历史、文件或上下文。Work 会话中选择 Agent 来完成任务，目标是产出一个 Artifact，例如图片、研究报告或 PPT/PPTX 演示文稿。
6. 失败或取消的运行可在卡片中重试；演示运行从最近检查点恢复，已登记产物不会重复创建。

## 验证

```powershell
Set-Location backend
uv run ruff check .
uv run pytest -q
uv run alembic current

Set-Location ..\frontend
npm run build
npm test -- --run
```

自动化覆盖模式校验、SSE 停止/重新生成、标题/搜索、Skill、Memory、文件安全、引用、三类 Agent、失败重试、PPTX 修改与幂等恢复。十四个 MVP 场景的对应证据和外部服务复验方式见 [验收记录](docs/acceptance.md)。

LangSmith 的四个版本化 dataset、指标定义、基线/优化结果和复现命令见 [追踪与评估](docs/evaluation.md)。

## MVP 边界

- 当前提供独立用户工作区与管理员/普通用户两级权限，不包含组织、团队空间、细粒度自定义角色、计费或分布式任务队列。
- 首版不支持任意外部 PPTX 编辑、OCR、表格文件或图片向量检索。
- 模型和搜索结果仍需人工核对；联网验收需要有效的百炼和 Tavily 凭据。
- 开发配置默认使用本地目录；生产化的对象存储、密钥管理、审计与高可用不在 P0 范围。

更多背景见 [产品需求](docs/requirements.md)、[架构设计](docs/architecture.md) 和 [任务清单](docs/tasks.md)。
