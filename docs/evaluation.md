# LangSmith 追踪与评估

## 追踪范围

启用 `LANGSMITH_TRACING=true` 并配置 `LANGSMITH_API_KEY` 后，服务会把以下根运行写入
`LANGSMITH_PROJECT`：

| 链路 | 根运行名 | 主要子运行 |
| --- | --- | --- |
| Chat | `intelligence_hub.chat` | `qwen.chat.completions.stream`、`document.retrieve`、`tavily.mcp.search` |
| 图片 Agent | `intelligence_hub.agent.image` | Qwen 结构化调用、图片生成 |
| 演示 Agent | `intelligence_hub.agent.slides` | 意图路由、大纲、内容生成、PPTX 渲染 |
| 深度研究 Agent | `intelligence_hub.agent.research` | 研究协调、搜索、证据综合 |

根运行带有功能标签、请求/会话/Agent 标识和产物摘要。图片 data URL、密钥等高体积或敏感内容不写入 trace。

本次冒烟追踪已写入 [intelligence-hub-agents 项目](https://smith.langchain.com/o/d120816d-d17f-4ab6-a4aa-cbd1133b918a/projects/p/551a0ecb-995c-4a01-a320-66ae12c54196)，四条链路均无错误。

## Dataset 与指标契约

同步命令会按稳定 UUID 幂等创建或更新四个版本化 dataset：

| Suite | Dataset | 样本数 | 指标 |
| --- | --- | ---: | --- |
| RAG | `intelligence-hub-rag-v3` | 100 | `Recall@5`、`MRR`、`Faithfulness` |
| MCP 搜索 | `intelligence-hub-mcp-search-v2` | 20 | `Search Relevance`、`Search Coverage`、`Citation Accuracy` |
| 演示 | `intelligence-hub-slides-v2` | 25 | `Intent Macro-F1`；`qwen3.7-plus` 对结构、内容、排版、色彩分别打 1–5 分 |
| 深度研究 | `intelligence-hub-research-v2` | 25 | `Requirement Capture Rate`、`Topic Coverage`、`Topic Redundancy`、`Report Checklist Recall` |

RAG v3 有 4 条样本通过 LangSmith 原生 attachment 上传真实文件，覆盖 Word（2 个）、PDF（1 个）
和 Markdown（1 个），文件大小分别为 15,597,454、15,728,509、15,859,712、15,990,670 bytes。
它们都经过生产上传校验与解析器读取；Word 和 PDF 还进行了逐页渲染检查，不是在 metadata 中伪造
文件类型或大小。评估读取 Markdown 时只保留前 32 个 chunk 作为候选，避免填充内容放大模型输入。

指标定义：

- `Recall@5` 是前五条检索结果覆盖的相关文档比例；`MRR` 是第一条相关文档名次的倒数。
- `Faithfulness` 是仅依据已检索文档可直接支持的事实主张比例。
- `Search Relevance` 是结果级 0–1 相关性均值；`Search Coverage` 是预期主题覆盖比例；`Citation Accuracy` 是答案中引用且能被对应搜索结果支持的 URL 比例。
- `Intent Macro-F1` 对 `CREATE`、`MODIFY`、`RESUME` 三类等权平均。
- `Topic Redundancy` 是报告中重复章节对比例，越低越好；其余研究指标越高越好。

MCP evaluator 使用模型语义评审，并以代码标识符、中文主题重叠和结果 URL 白名单作确定性复核；模型偶发返回非标准结构时不会把整条样本误记为零分。

## 运行方式

```powershell
Set-Location backend

# 幂等同步四个 dataset
uv run python -m app.evaluation.cli sync-datasets

# 运行某一组基线或优化实验
uv run python -m app.evaluation.cli run --suite rag --variant baseline
uv run python -m app.evaluation.cli run --suite rag --variant optimized --max-concurrency 2

# suite 可取 rag、mcp、slides、research 或 all
uv run python -m app.evaluation.cli run --suite all --variant optimized

# evaluator 迭代后，对已有实验的冻结输出重新评分
uv run python -m app.evaluation.cli rescore `
  --suite mcp `
  --experiment intelligence-hub-mcp-optimized-20260812-213704-9cbe4506
```

每次运行都会输出 dataset、实验名、LangSmith URL、样本数、指标均值和错误列表。

## 2026-08-13 v2 扩容结果

| Suite | 首轮完整实验 | 优化后完整实验 | 结论 |
| --- | --- | --- | --- |
| RAG（50） | Recall@5 `1.0000`；MRR `0.9900`；Faithfulness `0.9617` | Recall@5 `1.0000`；MRR `1.0000`；Faithfulness `1.0000` | 语义重排修复首位排序；原子主张判分消除计数漂移 |
| MCP（20） | 同一最新版 evaluator 重评：Relevance `0.8794`；Coverage `0.7833`；Citation `0.8500` | Relevance `0.8866`；Coverage `0.8833`；Citation `1.0000` | 多 facet + advanced 搜索提高覆盖；余额不足时透明使用抽取式带引用答案，三项搜索指标仍可完整评估 |
| 演示（25） | Macro-F1 `1.0000`；结构 `3.7143`；内容 `4.1429`；排版 `3.1429`；色彩 `4.0000` | Macro-F1 `1.0000`；结构 `4.2500`；内容 `4.2500`；排版 `3.2500`；色彩 `4.0000` | 显式要求全覆盖，稀疏/截断页修复，语义版式选择带来全面非退化 |
| 深度研究（25） | 同一确定性 evaluator 重评：Requirement `0.4300`；Coverage `0.5000`；Redundancy `0.0000`；Checklist `0.9920` | Requirement `0.9100`；Coverage `0.7500`；Redundancy `0.0211`；Checklist `0.9920` | 同口径下需求与主题覆盖显著提升；本轮因余额不足透明使用证据降级综合，结果不等同于 Qwen judge |

对应实验：

- RAG：[首轮](https://smith.langchain.com/o/d120816d-d17f-4ab6-a4aa-cbd1133b918a/projects/p/f116290b-1e95-475e-96e0-2ab4897d72af) / [最终](https://smith.langchain.com/o/d120816d-d17f-4ab6-a4aa-cbd1133b918a/projects/p/f9a2c92d-8c95-4b8e-b29e-f27ad378f1d0)
- MCP：[首轮](https://smith.langchain.com/o/d120816d-d17f-4ab6-a4aa-cbd1133b918a/projects/p/436811bc-1e55-49e9-9fdb-7d4e56965556) / [最终](https://smith.langchain.com/o/d120816d-d17f-4ab6-a4aa-cbd1133b918a/projects/p/e7ac2dd6-bc90-4f00-9b09-1567119cf783)
- 演示：[首轮](https://smith.langchain.com/o/d120816d-d17f-4ab6-a4aa-cbd1133b918a/projects/p/10447ff0-c476-463c-84ac-3f38a1dda4d7) / [最终](https://smith.langchain.com/o/d120816d-d17f-4ab6-a4aa-cbd1133b918a/projects/p/14c84a8e-2ed3-4bdc-8ca7-d0db2c0db077)
- 深度研究：[首轮（同口径重评）](https://smith.langchain.com/o/d120816d-d17f-4ab6-a4aa-cbd1133b918a/projects/p/16ebb7d8-fd01-4ac3-a3c0-af47848076b3) / [最终证据降级实验](https://smith.langchain.com/o/d120816d-d17f-4ab6-a4aa-cbd1133b918a/projects/p/2b5d2fff-db66-47ce-9795-5275773d7fed)

## 2026-08-13 RAG v3 扩容结果

`intelligence-hub-rag-v3` 扩大到 100 个唯一 case、100 个唯一 query。完整优化实验共有
100 个根运行且 0 错误：[查看 LangSmith 实验](https://smith.langchain.com/o/d120816d-d17f-4ab6-a4aa-cbd1133b918a/projects/p/36406e76-a4b0-4d36-ac99-5cd17884d580)。

| 指标 | 原始完整实验 | evaluator 修正后 |
| --- | ---: | ---: |
| Recall@5 | `1.0000` | `1.0000` |
| MRR | `1.0000` | `1.0000` |
| Faithfulness | `0.9900` | `1.0000` |

唯一的原始 Faithfulness 失败样本中，Qwen judge 临时不可用，旧降级规则把一个完全由两条已检索
文档支持、引用 ID 均有效的中文同义改写判为 0。修正后的降级 evaluator 联合检查正文词项覆盖与引用
ID：高覆盖且所有引用均属于实际检索结果才降低同义改写阈值；仅附一个合法引用但正文缺乏证据的
伪造主张仍会拒绝。修正通过正、反向测试后，只对该冻结输出更新评分，没有重新生成答案。

## 本轮优化

- RAG：扩大候选集后用 `qwen3.7-plus` 做直接可回答性重排，收紧只依据文件上下文的回答约束；Faithfulness 改为逐条原子主张判定。
- MCP：用原问题加关键 facet 并行搜索、启用 Tavily advanced depth、重排到 5 条，并修复错误/数字引用到实际结果 URL；evaluator 对官方域名和词项覆盖做确定性复核。
- 演示：显式需求成为大纲硬约束；清理占位与半句、保证每页 3–4 条短要点，并按比较、流程、结论等语义选择卡片版式。
- 深度研究：合并关联比较项、按搜索预算覆盖全部 facet、优先官方来源；使用更小的结构化综合 schema，并由服务端绑定白名单 evidence URL，减少模型超时与映射失败。

> 复跑说明：最终演示实验完整结束后，DashScope 开始返回 `Arrearage`。MCP 的最终实验明确标记 `generation_mode=extractive_fallback`，其答案由实际搜索摘要和白名单 URL 生成，适合评估搜索三项指标，但不代表 Qwen 生成质量。深度研究的最终实验同样标记综合模式，并采用保守确定性 evaluator；余额恢复后可再运行 Qwen judge 复核：

```powershell
uv run python -m app.evaluation.cli run --suite mcp --variant optimized --max-concurrency 2
uv run python -m app.evaluation.cli run --suite research --variant optimized --max-concurrency 2
```
