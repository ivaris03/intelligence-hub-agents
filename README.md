# Intelligence Hub

Intelligence Hub 是一个个人 Agent Hub。当前仓库已完成 M0 基础骨架：Vue 3 前端、FastAPI 后端、SSE 流式消息、百炼 Qwen 适配边界，以及 PostgreSQL + pgvector 迁移入口。

## 当前可用

- Chat / Work 模式与三个内置 Agent 的选择入口
- 思考内容和最终回答分流的 SSE 事件协议
- 未配置模型密钥时可运行的本地演示回复
- 左侧会话栏、主对话区、输入区和设置页框架
- FastAPI 健康检查和 OpenAPI 文档
- PostgreSQL + pgvector 容器与初始 Alembic 迁移
- 前后端基础测试、类型检查和生产构建

会话持久化、文件、Skill、Memory 和 Agent 工作流仍属于后续里程碑；页面上的对应入口目前仅作为布局骨架。

## 环境要求

- Node.js 20.19+ 或 22.12+
- Python 3.12+
- [uv](https://docs.astral.sh/uv/)
- Docker（运行 PostgreSQL 时需要）

## 本地启动

先复制环境变量示例：

```powershell
Copy-Item .env.example .env
```

启动数据库并执行迁移：

```powershell
docker compose up -d postgres
Set-Location backend
uv sync --dev
uv run alembic upgrade head
```

根目录的 `sql/schema.sql` 和 `sql/data.sql` 分别提供当前基础表结构与幂等演示数据，适合直接检查 SQL 或手动初始化空库。日常开发仍以 Alembic 迁移为准，避免在同一个数据库上混用两种建表方式。

启动 API：

```powershell
Set-Location backend
uv run uvicorn app.main:app --reload --env-file ../.env
```

另开一个终端启动 Web：

```powershell
Set-Location frontend
npm install
npm run dev
```

打开 <http://localhost:5173>。API 健康检查位于 <http://127.0.0.1:8000/api/health>，接口文档位于 <http://127.0.0.1:8000/docs>。

未设置 `DASHSCOPE_API_KEY` 时，发送消息会收到逐字流式的本地演示回复。设置密钥后，服务端通过百炼的 OpenAI 兼容接口调用模型：Chat 使用 `qwen3.7-flash`，Work 使用 `qwen3.7-plus`，嵌入使用 `qwen3.7-text-embedding`，图片生成使用 `qwen-image-3.0`；模型 ID 均可通过环境变量覆盖，密钥不会进入前端包。

如需记录 LangChain 调用链，请在 `.env` 中填写 `LANGSMITH_API_KEY`，并保留 `LANGSMITH_TRACING=true`。`LANGSMITH_PROJECT` 用于指定追踪项目，私有部署时可调整 `LANGSMITH_ENDPOINT`。后端启动命令通过 `--env-file ../.env` 将这些变量提供给 LangSmith SDK。

## 验证

```powershell
Set-Location backend
uv run ruff check .
uv run pytest

Set-Location ..\frontend
npm run build
npm test
```

## 目录

```text
frontend/                 Vue 3 + TypeScript + Vite
backend/app/api/          FastAPI 路由与请求模型
backend/app/db/           SQLAlchemy 模型与会话
backend/app/integrations/ Qwen 等外部服务适配器
backend/migrations/       Alembic 数据库迁移
docs/                     产品需求、架构与任务清单
storage/                  本地产物目录（内容不提交）
```

更多范围与实现顺序见 [需求](docs/requirements.md)、[架构](docs/architecture.md) 和 [任务清单](docs/tasks.md)。
