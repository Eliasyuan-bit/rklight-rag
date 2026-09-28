# RAG 检索后证据精炼：问题与优化记录

更新日期：2026-09-17

本文记录一次面向小模型 RAG 的上下文污染修复。典型现象是：检索已经命中正确文档和正确 chunk，但 Qwen3.5-2B 的答案仍混入相邻章节，例如询问 USB 测试时同时回答产品号写入、MaskRom 或 SARADC。这个问题不是“没有检索到”，而是“送给生成模型的证据粒度仍然太粗”。

## 问题在哪里

当前知识库按 chunk 建索引。一个 chunk 为了保留语义完整性，可能同时包含一个主章节、后续子章节、表格多行或数个流程。chunk 级 reranker 只能判断整个 chunk 与问题是否相关，不能保证 chunk 内每一句都相关。

原来的查询路径大致是：

```text
问题
  -> 向量、词法和 KG 召回
  -> chunk 级融合与 rerank
  -> 上下文 token 裁剪
  -> 2B 生成答案
```

以“介绍一下 USB 测试”为例，USB 标题和流程能使整个 chunk 获得高分，但同一 chunk 后面的 `SET_PN`、MaskRom 和 SARADC 内容也会被完整送入 LLM。2B 模型更容易把相邻内容误认为 USB 流程的一部分，于是产生事实串位。

这类问题有三个特征：

- 引用文档是正确的，继续增加 `top_k` 只会带来更多噪声。
- 缩小建库 chunk 可以缓解污染，但会破坏完整流程、表格和跨句语义，也会增加索引数量。
- 用提示词要求“不要回答无关内容”只能抑制表象；LLM 仍然看到了错误证据，尤其是 2B 模型不稳定。

因此，根因不在生成长度，也不单纯在 chunk size，而在 chunk 级检索与句子级事实之间缺少一层证据准入。

## 采用的方案

在既有 chunk rerank 之后增加结构感知的 Evidence Refiner（证据精炼器），把已召回 chunk 再拆成更小但仍保持结构完整的证据单元，复用常驻 reranker 做一次批量评分，只将与问题直接相关的单元送入生成模型。

新的查询路径是：

```text
问题
  -> 向量、词法和 KG 召回
  -> chunk 级融合与 rerank
  -> 来源权威与章节隔离策略
  -> Evidence Refiner：拆分、评分、准入、重建
  -> 上下文 token 裁剪
  -> 2B 生成答案
```

该方案没有增加新的模型，也没有用 LLM 做上下文压缩。它调用现有的 Qwen3 reranker 一次，因此比 LLM 摘要式压缩更适合当前单卡、低 TTFT 的部署目标。

### 1. 结构化拆分

精炼器将候选 chunk 拆成以下证据单元：

- 普通段落按完整句子拆分；
- Markdown 列表按列表项拆分；
- Markdown 表格按数据行拆分，并保存表头；
- `<table format="json">` 按 JSON 行拆分；
- 代码块和 Mermaid 图保持为原子单元，避免流程被拆坏；
- 每个单元记录标题、章节路径以及在原 chunk 中的字符范围。

这不是简单按字符切割。重建上下文时会补回必要的 Markdown 标题和表头，JSON 表格行也会恢复成合法的表格结构。

### 2. 单次批量重排

每个证据单元以“章节路径 + 证据类型 + 正文”的形式参与评分。精炼器调用已经常驻的 `RERANK_BINDING_HOST`，一次请求完成所有候选单元的相关性计算，不启动额外 LLM，也不切换模型。

为了限制延迟和内存，当前最多对 24 个证据单元评分，每个已经排好序的 chunk 最多取 8 个单元。候选仍按 chunk 的既有排序进入，因此证据精炼不会代替第一阶段召回。

### 3. 动态证据准入

准入阈值同时考虑绝对分数和本次查询的最高分：

```text
score_floor = max(min_score, best_score * relative_ratio)
```

普通查询使用 `relative_ratio=0.5`，包含“介绍、完整、全部、流程、步骤”等宽泛意图的查询使用 `0.3`，避免概览问题只剩一个句子。如果没有单元达到阈值，至少保留最高分单元，防止生成上下文为空。

### 4. Small-to-big 邻近恢复

只保留独立高分句子可能丢失条件、结果或说明，因此系统会检查入选单元的前后相邻单元。邻居必须同时满足：

- 与已选单元属于同一个结构章节；
- 自身分数达到较低的邻居阈值；
- 没有超过总单元数和字符预算。

这相当于“小粒度命中，大粒度恢复”，既保留必要上下文，又不会跨标题把下一节内容带进来。

### 5. 安全回退

如果 reranker 超时、返回异常、分数数量不一致，或拆分后单元过少，精炼器直接返回原始 chunk。证据精炼失败不会导致查询失败，也不会返回空答案。

## 实现位置

| 内容 | 文件 |
| --- | --- |
| 证据拆分、评分、选择和重建 | `core/lightrag-extensions/rk_evidence_refiner.py` |
| 将精炼器接入 LightRAG 查询链路 | `core/lightrag-extensions/install_lightrag_source_policy_hook.py` |
| 部署时复制扩展 | `scripts/internal/install-lightrag-extensions.sh` |
| 板端默认参数 | `core/model-gateway/deploy/lightrag-rk3588.env` |
| 单元测试 | `core/lightrag-extensions/tests/test_rk_evidence_refiner.py` |
| Hook 安装测试 | `core/lightrag-extensions/tests/test_source_policy_install.py` |

对应功能提交为 `47f6b45 feat: refine retrieved evidence before generation`。

当前主要配置如下：

```bash
RK_EVIDENCE_REFINER_ENABLED=1
RK_EVIDENCE_MIN_TOTAL_CHARS=240
RK_EVIDENCE_MIN_UNITS=3
RK_EVIDENCE_MAX_CANDIDATES=24
RK_EVIDENCE_MAX_UNITS_PER_CHUNK=8
RK_EVIDENCE_MIN_SCORE=0.1
RK_EVIDENCE_RELATIVE_SCORE_RATIO=0.5
RK_EVIDENCE_BROAD_SCORE_RATIO=0.3
RK_EVIDENCE_NEIGHBOR_SCORE_RATIO=0.35
RK_EVIDENCE_MAX_UNITS=12
RK_EVIDENCE_MAX_CHARS=6000
RK_EVIDENCE_RERANK_TIMEOUT=60
```

关闭此功能只需设置 `RK_EVIDENCE_REFINER_ENABLED=0` 并重启 LightRAG，不需要重建知识库。

## 验证结果

2026-09-17 在 162 的 RK3588 + 单张 RK1828 环境完成了代表性冒烟测试：

| 查询 | 优化后的上下文或回答表现 |
| --- | --- |
| `介绍一下USB测试` | 上下文只保留 USB 标题和 USB 流程，不再包含 SET_PN、MaskRom、SARADC；完整回答约 5.2 秒。 |
| `FT测试中USB错误是为什么？` | 回答聚焦 USB 识别、速率判断和 ADB `date/local` 校验；完整回答约 3.2 秒。 |
| `产品号怎么写入` | 8 个 chunk、24 个候选证据单元收敛为 3 个 chunk、4 个证据单元，约 910 字；JSON 错误表只保留 SET_PN、PN_GET 等相关行；只取上下文约 3.8 秒。 |
| `介绍一下FT的测试流程` | 保留完整的六步流程，没有因细粒度过滤丢失整体结构；完整回答约 7.7 秒。 |

代码级回归通过 75 项 LightRAG 扩展测试和 35 项模型网关测试。以上延迟包含检索、排队和生成，只用于此次板端冒烟对照，不应视为严格性能基准。

## 为什么不采用其他做法

| 方案 | 本次未作为主方案的原因 |
| --- | --- |
| 继续减小建库 chunk | 会增加索引规模，并可能切断流程、表格和条件关系；不能保证所有文档边界都恰好正确。 |
| 增加或减少 `top_k` | `top_k` 控制 chunk 数量，不能删除一个正确 chunk 内部的无关章节。 |
| 修改回答提示词 | 只能要求模型自我约束，不能阻止污染证据进入上下文；对 2B 模型尤其不稳定。 |
| 使用 LLM 摘要/压缩上下文 | 会新增一次生成调用，增加 TTFT，并可能在摘要时改写命令或精确参数。 |
| 针对 USB 写规则 | 只能修复一个问题类型，无法覆盖产品号、授权、部署、性能表等新领域。当前实现仅识别通用 Markdown 结构。 |
| 全量句子级重新建索引 | 工程改动和迁移成本更高，需要重建现有库；可作为后续演进，而非本次最小闭环。 |

## 当前边界与后续优化

这次优化解决的是文档 chunk 内的证据污染，不代表整个 RAG 已完成准确性验收：

- KG 的实体和关系上下文目前还没有经过相同的证据准入，KG 噪声仍可能进入生成上下文；下一步优先把实体、关系也纳入统一的 evidence admission。
- 当前每个 chunk 只取前 8 个证据单元参与评分。异常密集且答案位于 chunk 尾部的文档可能漏掉后段单元，可改为结构分层采样或小批次评分。
- Mermaid 当前保持整体原子性，适合回答完整流程；原因类问题中，2B 偶尔仍可能把图中的成功分支描述成故障原因。后续可增加 Mermaid 节点/边级解析，但必须保留概览查询的完整图。
- `evidence_ranges` 已记录字符范围，但尚未暴露到引用 API 和网页预览。接通后可以直接高亮本次实际使用的段落，而不是只定位到整个 chunk。
- 动态阈值目前来自代表性问题调试，需要运行 40 题评测集并进行人工证据核验后再校准，不能仅以“有 References”判断正确。
- 同一原文的多个内部 chunk 仍可能产生多个后端引用项；网页可以按文档聚合展示，但更理想的是服务端合并同文档引用并保留多个证据范围。

完整准确性回归、建库分页抽取和引用展示的其他改动见 [RAG 准确性回归记录](rag-accuracy-validation.md) 与 [引用预览说明](reference-preview.md)。

## 查询感知的混合检索补充

2026-09-17 的后续回归发现，“`burn_stress` 检查版本”虽然在第一阶段已经召回包含 `burn_stress -V` 的正确 chunk，固定权重融合后的 reranker 和章节裁剪仍可能只留下文档总标题。完整回答因此依据宽泛 KG 关系补写了原文不存在的 `rknn-smi` 操作。这属于检索后误删，不是知识库缺少内容。

当前查询链路进一步加入查询感知的软路由：BM25 和向量检索始终执行，不做二选一；含命令、版本、参数、路径、错误码等精确结构的查询提高 BM25 权重并扩大 rerank 候选窗口，概览和原理类查询提高向量权重，其余查询保持原有平衡权重。精确查询随后按 rerank 排名、第一次 RRF 排名和 BM25 排名进行第二次排名融合，并为最强的实质证据保留席位。

同时增加以下防护：

- 文档一级标题没有实质正文时不能被单独选为证据；
- Markdown 章节选择支持中文意图词，版本、参数、路径等目标词高于“输出”等动作词；
- 精确查询存在直接原文时，不向 2B 展示独立 KG 实体和关系，防止间接关系覆盖命令原文；
- Evidence Refiner 至少保留受保护 chunk 中得分最高的证据单元；
- 答案缓存策略版本同步递增，避免继续返回修复前的旧回答。

板端回归结果如下：

| 查询 | 最终证据与回答 |
| --- | --- |
| `burn_stress检查版本怎么做` | 只保留 `版本检查`，回答 `burn_stress -V` 和 `V1.0.4_20260806`，单一原文引用。 |
| `burn_stress版本如何输出` | 不再误选 DRAM 的普通“输出说明”，回答版本命令及版本值，单一原文引用。 |
| `介绍一下USB测试` | 仍保留 USB 自动测试流程，未受精确查询路由影响。 |
| `FT测试中USB错误是为什么？` | 仍保留 USB/ADB 判断分支，未混入产品号、SARADC 等章节。 |

实现主要位于 `rk_lexical_retrieval.py`、`rk_source_policy.py`、`rk_evidence_refiner.py`、查询默认参数 Hook 和 `lightrag-rk3588.env`。动态权重只是初始工程参数，仍应以固定评测集的 Recall、MRR、回答正确性及 TTFT 共同校准。
