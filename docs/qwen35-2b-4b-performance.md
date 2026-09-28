# Qwen3.5-2B 与 Qwen3.5-4B 性能对比

| 模型 | 芯片 | 输入 / 输出 token | TTFT | 近似 Prefill TPS | TPOT | Decode TPS |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| Qwen3.5-2B | RK182X | 128 / 128 | 79.32 ms | 1613.7 token/s | 10.94 ms | 91.40 token/s |
| Qwen3.5-4B | RK1828 | 128 / 128 | 160.56 ms | 797.2 token/s | 19.66 ms | 50.86 token/s |

> 近似 Prefill TPS 使用 `Input Tokens / TTFT(s)` 计算。TTFT 可能包含固定调度和首 token
> 生成开销，因此该结果是有效吞吐估算值，不等同于推理框架直接报告的纯 Prefill TPS。

## Qwen3.5-4B 板端实测（2026-09-21）

RK1828 新增卡（设备 `0001:11:00.0`），使用 `rkllm3-server` 单卡运行 Qwen3.5-4B；
单客户端流式请求，关闭 prompt cache。用合成文本校准到表中的**实际输入 token 数**，
每种长度预热 1 次、再测 3 次。以下各项是分别取中位数，不代表一次请求的完整时序。

| 输入 / 输出 token | 客户端 TTFT | 服务端 Prefill 耗时 | 服务端 Prefill TPS | 服务端 Decode TPS | 客户端总耗时 |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 128 / 128 | 207.4 ms | 162.4 ms | 788.2 token/s | 50.4 token/s | 2726.5 ms |
| 662 / 41 | 972.8 ms | 925.6 ms | 715.2 token/s | 48.9 token/s | 1791.0 ms |
| 1188 / 117 | 1591.0 ms | 1542.4 ms | 770.2 token/s | 49.1 token/s | 3954.3 ms |
| 1613 / 142 | 2066.7 ms | 2016.1 ms | 800.1 token/s | 48.6 token/s | 4965.3 ms |

客户端 TTFT 从发请求到首个内容 token，含请求传输与服务端开销；Prefill/Decode TPS
是服务端返回的原生计时。上表的 128/128 与开头的参考行测试口径不同，不能把两行 TTFT
当作模型性能变化。后三行仅模拟 RAG 中出现过的 token 长度，**不是 4B 的 RAG 端到端实测**；
没有包含 Embedding、Rerank、检索或提示词组装。测试程序见
[benchmark_4b_server.py](../evals/three-docs-v1/benchmark_4b_server.py)。
