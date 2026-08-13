# Intelligence Hub P0 验收记录

> 验收日期：2026-08-13
> 范围：`requirements.md` 第 7 节的十四个 MVP 场景

## 验收环境

- PostgreSQL 16 + pgvector，Alembic revision `20260813_0002`。
- 后端 `ruff` 与 `pytest`，前端 `vue-tsc`、Vite build 与 Vitest。
- Codex 应用内浏览器访问 `http://127.0.0.1:5173`，通过 Vite 代理连接真实 FastAPI 与 PostgreSQL。
- 服务端已配置有效的 Qwen、Qwen Vision、Qwen Image、Embedding 与 Tavily 凭据；验收期间未向前端或日志输出密钥。

## 十四场景矩阵

| # | 场景 | 自动化/数据层证据 | 页面验收 | 结果 |
| --- | --- | --- | --- | --- |
| 1 | 两轮流式对话与刷新恢复 | `test_persistent_chat_files_skill_memory_and_regeneration` | 新建会话、连续两轮发送并刷新，四条消息和自动标题均恢复 | 通过 |
| 2 | 停止与重新生成且不重复用户消息 | `test_stream_can_stop_without_duplicating_user_message`；重新生成断言用户数不变 | 卡片提供停止、取消态与重新生成入口 | 通过 |
| 3 | `docx`、图片问答与文件来源 | `test_upload_validation_checks_mime_and_magic` 覆盖 DOCX 段落和图片魔数/像素；真实 DOCX 已完成解析、Embedding、召回与定位 | DOCX 问答正确命中“第 1 段”；真实 Qwen Vision 图片问答显示图片来源 | 通过 |
| 4 | 仅显式联网并展示真实来源 | `test_search_requires_explicit_language`；Tavily 结果只接受 `http(s)` URL；未在搜索结果中的 URL 会从最终正文移除 | 真实 Tavily 工具卡、来源与耗时正常；诱导模型输出伪链接时触发最终正文替换，伪链接未持久化 | 通过 |
| 5 | Work 三 Agent；Chat 不误启动 | Pydantic 模式组合测试和三 Agent 集成测试 | Work 显示三个 Agent；Chat 隐藏 Agent 选择器 | 通过 |
| 6 | 图片参考图、预览和下载 | 图片校验、Run 文件关联及 PNG artifact 集成路径；真实 Qwen Image 生成 2.36 MB PNG | 图片产物在卡片内预览并提供下载 | 通过 |
| 7 | PPTX 确认、修改与恢复 | 验证确认前无产物、PPTX 可解析、v2 父版本、非目标页不变、取消后恢复及幂等；PostgreSQL checkpointer 以 `run_id` 为 thread | 真实模型生成大纲并确认；v1/v2 均可解析，定向页变化且其余三页保持一致；提前恢复返回 409 | 通过 |
| 8 | 带引用 Markdown 研究报告 | 外层 LangGraph、共享预算、来源归一化和引用校验单元/集成路径 | 真实研究运行使用 3/4 次搜索、108.3 秒内完成；报告含 6 个可访问来源并生成 Markdown 产物 | 通过 |
| 9 | Agent 失败可见并重试 | `test_agent_failure_is_visible_and_retryable` 验证脱敏错误、`tool.failed`、重试与单一产物 | 失败/取消卡片提供重试或恢复入口 | 通过 |
| 10 | 思考、工具与阶段刷新恢复 | 消息 parts、tool_calls、run_events 持久化集成路径；真实百炼 SSE 的 `reasoning_content` 与 `content` 分别映射为事件 | 折叠区显示阶段、工具名、状态、耗时和安全摘要；刷新顺序不变 | 通过 |
| 11 | 自动标题、搜索和推荐问题 | 集成测试检查搜索摘要、标题事件与 `follow_up.finalized` | 首轮自动标题；推荐问题恰好一个且点击只填入；侧栏搜索可跳转 | 通过 |
| 12 | Skill 选择、快照与停用 | 显式 Skill、自动至多一个和不可变快照集成路径 | 设置页 CRUD/启停，输入区只列已启用 Skill，消息/运行显示快照名称 | 通过 |
| 13 | 用户记忆摘要与记住/忘记 | 显式命令数据库回执、完整摘要注入、单摘要读写/开关路径 | 设置页编辑唯一摘要；“请记住”立即显示回执并更新摘要 | 通过 |
| 14 | 闲置队列、午夜提炼、游标与总开关 | `test_idle_memory_queue_waits_six_hours_and_processes_at_local_midnight` 与 `test_nightly_memory_queue_uses_snapshot_and_batches_per_user` 覆盖 6 小时入队、本地午夜、队列快照、按用户批量消费、去重游标和关闭开关 | Memory 开关关闭时输入禁用，重新开启立即恢复 | 通过 |

## 真实在线服务复验结果

1. 健康检查返回 `model_ready=true`、`tavily_ready=true`；百炼流式响应同时产生独立思考事件和最终回答事件。
2. 显式联网 Chat 产生 Tavily 工具事件和 5 个实际来源；测试提示中夹带的非搜索 URL 被服务端移除，刷新后的持久化正文中不存在该 URL。
3. 研究 Agent 在共享预算内完成 3 次搜索，生成结构化中文 Markdown 报告；6 个引用 URL 在验收时均返回 HTTP 200。
4. Qwen Image 生成的 PNG 可预览、下载；Qwen Vision 正确识别图片主体。演示 Agent 生成的 PPTX 可由 `python-pptx` 重新打开，定向修改保留版本链和非目标页。
5. DOCX 上传后完成 1024 维 Qwen Embedding 与 pgvector 存储；问答正确召回段落定位。长 Markdown 文档同样完成分块检索并返回文件来源。

## 回归命令

```powershell
Set-Location backend
uv run ruff check .
uv run pytest -q
uv run alembic upgrade head
uv run alembic current

Set-Location ..\frontend
npm run build
npm test -- --run
```
