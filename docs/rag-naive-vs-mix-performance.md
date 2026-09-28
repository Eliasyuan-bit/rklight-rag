# Naive RAG 与 LightRAG Mix 稳定态性能对比

问题：“FT 测试中 USB 错误是为什么？”单客户端流式请求、同一知识库、Rerank 开启。LightRAG 重启后先分别用 Naive 和 Mix 各预热 1 次，再各测 5 次；下表均为**逐次请求的中位数**。

> 测试期间临时关闭 LightRAG 的 LLM 缓存，Mix 每次均实际执行查询理解和回答两次 LLM 调用；测试后已恢复默认缓存设置。Rerank daemon 的热/冷态仍可能变化：Naive 的 5 次中有 1 次为 222.4 ms，其余约 42.7–42.8 ms，因此报告中位数及逐次原始值。

## 端到端指标

| 指标 | Naive RAG | LightRAG Mix | Mix − Naive |
| --- | ---: | ---: | ---: |
| 系统首字时间 TTFT | 1447.8 ms | 2861.4 ms | +1413.6 ms |
| 总耗时 | 2906.7 ms | 4005.0 ms | +1098.3 ms |
| 模型调用外耗时¹ | 149.1 ms | 210.9 ms | +61.8 ms |

¹ 每条请求先用总耗时减去查询理解 LLM、Embedding、Rerank 和回答 LLM 的网关调用耗时，再取中位数。它包含检索处理、队列/调度、引用处理和传输等，**不是一个单独执行的阶段**。上表各项分别取中位数，不能直接相加。

## 阶段耗时与输入规模

| 阶段 | Naive RAG | LightRAG Mix |
| --- | ---: | ---: |
| 查询理解 LLM | 不调用 | 662 输入 / 41 输出 token；921.1 ms |
| Embedding | 1 条 / 12 输入 token；27.0 ms | 3 条 / 34 输入 token；79.8 ms |
| Rerank | 1 候选 / 762 输入 token；42.8 ms | 6 候选 / 2340 输入 token；681.7 ms |
| 回答 LLM | 1613 输入 / 142 输出 token；2654.1 ms | 1188 输入 / 117 输出 token；2111.4 ms |

阶段耗时同样分别取中位数，不能把这一行行的中位数相加作为某次请求总耗时。Rerank 的输入 token 包含查询、候选文本和模型提示模板；Naive 与 Mix 的候选数量不同，不能把阶段耗时差解释为纯模型速度差。

完整逐次数据见 [JSON](../evals/three-docs-v1/results/qa-usb-warm-uncached-timing-20260921.json)，可编辑图表见 [Excel](rag-naive-vs-mix-warm-performance.xlsx)，网页图见 [HTML](rag-naive-vs-graph-timing.html)。早先的[单次基线](rag-qa-performance-baseline.md)保留为历史记录；关键词缓存命中的另一组后续请求见[缓存态 JSON](../evals/three-docs-v1/results/qa-usb-warm-timing-20260921.json)，不可混进本表。首次请求的内部打点及原因分析见[耗时排查记录](rag-query-timing-investigation.md)。
