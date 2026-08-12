# Intelligence Hub 实施任务

> 面向个人项目的 MVP 清单  
> 更新日期：2026-08-13

## 1. 执行原则

- 按可演示的纵向功能推进，不先建设生产级平台能力。
- 每个里程碑结束时都应有可运行页面。
- `P0` 是 MVP 必需，`P1` 是体验增强，`Later` 暂不实施。
- 任务完成需同时包含实现、基础测试和必要说明。

## 2. 里程碑

| 里程碑 | 目标 | 完成标志 |
| --- | --- | --- |
| M0 基础骨架 | 跑通前后端和模型 | 页面可发送一条流式消息 |
| M1 Chat MVP | 完成 ChatGPT 风格主流程 | 核心 Chat、标题、推荐问题、搜索、文件、Skill 和 Memory 可用 |
| M2 Agent Hub | 跑通三个 Agent | 图片和研究报告可产出；PPTX 可新建、修改和恢复 |
| M3 收尾 | 达到可稳定演示状态 | 验收场景通过，文档和错误体验完整 |

## 3. P0 任务

### M0：基础骨架

| ID | 任务 | 验收 | 依赖 |
| --- | --- | --- | --- |
| FND-01 | 初始化 Vue + FastAPI 项目 | 前后端可本地启动，提供健康检查 | - |
| FND-02 | 配置 PostgreSQL + pgvector 和迁移 | 可创建并迁移本地数据库 | FND-01 |
| FND-03 | 建立环境配置与 Qwen 适配器 | 密钥仅在服务端；思考内容和最终回答可分流输出 | FND-01 |
| FND-04 | 建立基础页面框架 | 左侧会话栏、主对话区、输入区可展示 | FND-01 |
| FND-05 | 建立 SSE 客户端与服务端事件 | 思考、工具状态和回答可按序流式显示，断开后可恢复最终状态 | FND-03/04 |
| FND-06 | 建立设置页布局 | Skill、Memory、联网和外观设置拥有统一入口 | FND-04 |

### M1：Chat MVP

| ID | 任务 | 验收 | 依赖 |
| --- | --- | --- | --- |
| CHAT-01 | 会话与消息数据模型/API | 新建、切换、重命名、删除和刷新恢复可用 | FND-02 |
| CHAT-02 | 多轮 Chat 编排 | 带近期历史调用模型，Markdown 正常渲染 | FND-03/05/CHAT-01 |
| CHAT-03 | 停止、失败与重新生成 | 状态不混乱，不重复用户消息 | CHAT-02 |
| CHAT-04 | Chat/Work 模式与 Agent 选择器 | 服务端拒绝非法模式组合 | CHAT-02 |
| CHAT-05 | 思考与工具调用 UI | 思考过程可流式展示和折叠；工具名称、状态、耗时、参数及结果摘要可查看且已脱敏 | CHAT-02/03/FND-05 |
| CHAT-06 | 自动标题 | 首轮完成后生成标题；手动标题不会被覆盖 | CHAT-02 |
| CHAT-07 | 推荐问题 | 完成回答末尾恰好一个推荐问题；点击只填充输入框 | CHAT-02/FND-05 |
| CHAT-08 | 会话搜索 | 标题和消息正文可搜索，显示命中摘要并可跳转 | CHAT-01 |
| FILE-01 | 文件上传与本地/MinIO 存储适配 | 支持格式、大小限制、进度和错误提示可用 | FND-01 |
| FILE-02 | `txt`、`md`、`pdf`、`docx` 文本提取 | 解析结果和失败状态可查询，`docx` 正文与基础段落定位可用 | FILE-01 |
| FILE-03 | 图片上传校验与多模态输入 | 支持 `png`、`jpg`、`jpeg`、`webp`；校验 MIME、文件魔数和像素尺寸；Chat 可围绕图片问答 | FND-03/FILE-01/CHAT-02 |
| FILE-04 | 长文分块、Embedding 和 pgvector 检索 | 文档问答能召回相关片段，图片不进入文本向量检索 | FND-02/03/FILE-02 |
| FILE-05 | 请求文件关联与引用展示 | 保存每条消息/运行实际使用的文件；回答可显示文件名和文档定位信息，刷新与重新生成后关联不丢失 | CHAT-02/FILE-03/04 |
| WEB-01 | Tavily MCP 适配器 | 显式搜索请求能返回统一来源结构 | FND-03 |
| WEB-02 | Chat 联网调用与来源展示 | 只有明确请求才搜索，回答展示真实链接 | CHAT-02/WEB-01 |
| SKILL-01 | Skill 数据模型与 CRUD API | 可创建、查看、编辑、启停和删除 | FND-02 |
| SKILL-02 | Skill 设置页面 | 名称、描述、指令可管理；名称重复有提示 | SKILL-01/FND-06 |
| SKILL-03 | `@Skill` 与自然语言选择 | 显式选择优先；自动选择至多一个且服务端复验 | SKILL-01/CHAT-02 |
| SKILL-04 | Skill 快照与调用展示 | 完整指令仅选中后加载；消息显示所用 Skill，历史不受后续编辑影响 | SKILL-03 |
| MEMORY-01 | Memory 数据模型、CRUD 与总开关 | 默认开启；可增删改查、清空和启停，记录来源与更新时间 | FND-02 |
| MEMORY-02 | Memory 设置页面 | 可查看、编辑、删除、清空和启停 | MEMORY-01/FND-06 |
| MEMORY-03 | 对话“记住/忘记” | 明确命令立即执行并显示与数据库一致的回执 | MEMORY-01/CHAT-02 |
| MEMORY-04 | 闲置 30 分钟自动提炼 | 使用游标避免重复；敏感、含糊和冲突内容不自动写入 | MEMORY-01/03 |
| MEMORY-05 | 相关 Memory 注入 | Chat 和 Work 在固定预算内使用相关记忆；关闭或删除后立即失效 | MEMORY-01/CHAT-02 |

### M2：Agent Hub

| ID | 任务 | 验收 | 依赖 |
| --- | --- | --- | --- |
| RUN-01 | 框架无关的 `agent_runs`、阶段事件和通用运行 UI | LangChain、LangGraph 和 Deep Agents 实现可通过统一接口启动；所选 Skill、相关 Memory、思考、工具调用和公开阶段按序展示，刷新后可恢复业务状态 | CHAT-04/05/SKILL-04/MEMORY-05/FND-05 |
| RUN-02 | Artifact Service | 图片、PPTX、Markdown 可登记和下载 | FILE-01/RUN-01 |
| IMG-01 | LangChain 图片 Agent 工作流 | 可读取当前运行关联的参考图，生成结构化 `ImageBrief`，通过受控图片工具和有限迭代完成生成并保存结果；不依赖 LangGraph 检查点 | FILE-03/05/RUN-01/02 |
| IMG-02 | 图片结果 UI | 可预览、下载和重试 | IMG-01 |
| SLIDE-01 | LangGraph 演示大纲生成与确认 | 通过图中断等待确认，未确认前不生成 PPTX | RUN-01 |
| SLIDE-02 | LangChain 页面内容与 PPTX 渲染 | 图节点使用结构化内容模型；生成文件可被常用演示软件打开 | SLIDE-01/RUN-02 |
| SLIDE-03 | 演示进度、预览与下载 | 阶段清晰，最终文件可下载 | SLIDE-02 |
| SLIDE-04 | 演示意图路由与版本模型 | 正确识别 `CREATE`、`MODIFY`、`RESUME`；版本关系可追溯 | SLIDE-02 |
| SLIDE-05 | 定向修改演示 | 基于指定版本生成新版本；原版本保留，非目标内容不被无故改动 | SLIDE-04/RUN-02 |
| SLIDE-06 | PostgreSQL LangGraph 检查点与恢复 | 以 `run_id` 作为 `thread_id` 保存检查点；中断后从最近阶段继续，幂等副作用不重复产物 | SLIDE-04 |
| SLIDE-07 | 修改与恢复 UI | 可选择源版本、提交修改，并对中断运行执行恢复 | SLIDE-05/06 |
| RES-01 | 研究外层 LangGraph 与预算控制 | 外层图管理阶段、取消、总耗时和共享搜索次数，所有 Deep Agents 主/子 Agent 调用均受同一预算约束 | RUN-01/WEB-01 |
| RES-02 | Deep Agents 研究子图 | 能拆解问题、调整计划、搜索与提取资料，并返回包含章节、证据、引用关系和未解决问题的结构化 `ResearchResult` | RES-01 |
| RES-03 | 证据校验与带引用报告 | 外层图复验 URL 和引用关系；Deep Agents 不能直接写业务数据库或登记 Artifact；输出 Markdown | RES-02/RUN-02 |
| RES-04 | 研究进度与报告下载 | 可查看外层公开阶段、正文、来源并下载 | RES-03 |

### M3：收尾

| ID | 任务 | 验收 | 依赖 |
| --- | --- | --- | --- |
| QA-01 | 核心单元与集成测试 | 模式、状态、事件、标题、推荐问题、搜索、Skill、Memory、文件、来源和 Agent 流程有覆盖 | M1/M2 |
| QA-02 | 十四个 MVP 场景端到端验收 | `requirements.md` 的场景全部通过 | QA-01 |
| UX-01 | 加载、空、失败、取消和重试体验 | 主流程不存在无反馈状态 | M1/M2 |
| SEC-01 | 基础安全检查 | 前端包和日志无密钥；上传和 Markdown 有限制 | M1/M2 |
| DOC-01 | 补齐 README 和本地启动说明 | 新环境可按文档启动并完成一次对话 | QA-02 |

## 4. P1 任务

P0 完成后按兴趣选择，不影响 MVP 验收：

| ID | 任务 |
| --- | --- |
| FILE-P1-01 | 支持 `pptx`、`csv`、`xlsx`，以及图片 OCR 与图片内容向量检索 |
| CHAT-P1-01 | 消息分支、高级搜索过滤和多个推荐问题 |
| SLIDE-P1-01 | 上传并编辑任意外部 PPTX |
| OBS-P1-01 | 接入 LangSmith 并建立小规模回归样本 |

## 5. 暂不实施

- 多用户登录、团队空间和复杂权限。
- Redis/Celery 集群、任务 outbox 和多 Worker 调度。
- 全套审计、成本账本、告警、灾备和发布门禁。
- 大规模离线评测集与模型 Judge 体系。
- 第三方 Agent、Skill、MCP 市场。
- 高可用、跨地域和大并发压测。

## 6. 推荐顺序

```text
FND -> 核心 Chat -> 标题/推荐问题/搜索 -> 文件与联网
    -> Skill/Memory -> 通用 Agent Run
    -> 图片 Agent -> 演示 Agent -> 研究 Agent -> 验收与文档
```

图片 Agent 最适合先验证通用运行和产物链路；演示 Agent 复用图片与产物能力；研究 Agent 最后接入已有的 Tavily 和引用能力。

## 7. Definition of Done

任务满足以下条件即可标记完成：

1. 验收描述可在本地复现。
2. 关键失败有用户可见提示。
3. 新增核心逻辑有基础测试。
4. 配置、接口或限制发生变化时同步更新文档。
5. 不提交密钥、生成产物或本地数据库。

## 8. P0 实施状态

> 完成日期：2026-08-13
> 详细的十四场景证据见 [`acceptance.md`](acceptance.md)。

| 里程碑 | 已完成 P0 | 状态 |
| --- | --- | --- |
| M0 基础骨架 | FND-01～FND-06 | ✅ 完成 |
| M1 Chat MVP | CHAT-01～CHAT-08、FILE-01～FILE-05、WEB-01～WEB-02、SKILL-01～SKILL-04、MEMORY-01～MEMORY-05 | ✅ 完成 |
| M2 Agent Hub | RUN-01～RUN-02、IMG-01～IMG-02、SLIDE-01～SLIDE-07、RES-01～RES-04 | ✅ 完成 |
| M3 收尾 | QA-01～QA-02、UX-01、SEC-01、DOC-01 | ✅ 完成 |

验收说明：已使用服务端配置的真实 Qwen、Qwen Vision、Qwen Image、Embedding 与 Tavily 凭据完成在线复验；模型思考/回答分流、真实来源过滤、文档向量检索、图片、PPTX 和研究报告产物链路均通过。无密钥环境仍保留可预测的安全演示与明确失败分支。
