# 三文档 RAG 人工验收集 v1

本集根据 2026-09-18 板端知识库中的三份源文档建立，共 60 题：

- `RM182xMC0模组测试软件说明.md`：20 题；
- `burn_stress使用说明_1.0.4.md`：15 题；
- `00_Rockchip_RKNPU3_ReleaseNote_RKNN3_SDK_V1.0.4_EN.pdf`：25 题。

题目覆盖流程、命令、故障分支、数值表格、跨行比较、术语和证据边界。`expected` 是语义验收要点，不要求回答逐字一致；`forbidden` 用于识别串表、串章节和无依据断言。评测集本身不要上传到知识库。

## 板端自动跑题

部署后在 RK3588 板端直接执行：

```bash
cd /userdata/rklight-rag/evals/three-docs-v1
./run-board.sh
```

脚本从板端访问 `http://127.0.0.1:9621`，串行运行全部 60 题。每题都是空历史，请求中不会携带预期答案。结果保存到：

```text
/userdata/lightrag-data/eval-results/three-docs-时间.json
/userdata/lightrag-data/eval-results/three-docs-时间.md
```

Markdown 报告把实际回答、预期要点、禁止错误、API References 和耗时放在一起，运行结束后可直接逐题人工勾选。

## P0：证据级基线与失败分类

`run_eval.py` 的每个结果会保存：

- `retrieval_trace_id`：与板端 LightRAG 日志中的隐私安全 Retrieval trace 对应；
- `expected_source`：本题应命中的原始文档；
- `assessment`：人工填写的 `retrieval_hit`、`evidence_complete`、`grounded`、
  `answer_correct` 和 `primary_failure`。

先运行评测，再对结果副本做人工归因。审核过程不会重发请求、不会修改知识库或原始
结果文件：

```bash
python3 evals/three-docs-v1/review_run.py \
  /userdata/lightrag-data/eval-results/three-docs-时间.json
```

失败类别含义：

- `retrieval_miss`：正确章节或表格没有进入候选；
- `context_loss`：正确候选存在，但没有进入最终生成证据；
- `evidence_insufficient`：最终证据存在，但回答所需字段不完整；
- `generation_error`：证据完整，回答仍然错误；
- `api_error`：请求或流式响应失败；
- `not_reviewed`：尚未分类，不能作为正确率结论。

审核后生成可比较的基线报告：

```bash
python3 evals/three-docs-v1/analyze_baseline.py \
  /userdata/lightrag-data/eval-results/three-docs-时间-reviewed.json
```

自动报告只统计 API 是否成功、预期源是否被引用、可见引用片段是否包含必需摘录；它不会
用关键词猜测答案正确性。`retrieval_hit` 必须结合相同 `retrieval_trace_id` 的板端日志人工判断。

如果一次完整 60 题被拆成多段运行，可按时间顺序合并；后输入的同题结果会覆盖前一次
结果，适合用干净复测覆盖超时记录：

```bash
python3 evals/three-docs-v1/merge_runs.py run-1.json run-2.json run-3.json \
  --output /userdata/lightrag-data/eval-results/three-docs-baseline-60.json
```

先跑 9 题冒烟测试：

```bash
./run-board.sh --smoke
```

只跑 PDF 的 25 题，或者指定题目：

```bash
./run-board.sh --source sdk
./run-board.sh --ids FT02 BURN01 SDK08 SDK09
```

只检查将运行哪些题，不请求 RAG：

```bash
./run-board.sh --dry-run
```

默认使用 `mix`、启用 rerank，并使用 `top_k=6`、`chunk_top_k=3`、实体/关系/总 token 预算 `500/300/3000`。完整 60 题单并发串行执行，运行时不要同时在网页查询。

## 手工网页测试（可选）

先确保 PDF 在网页中显示建库完成，再运行：

```bash
python3 evals/three-docs-v1/manual_review.py
```

脚本逐题显示问题。把问题复制到 WebUI，每题新建空历史会话；网页回答完整后回到终端按 Enter，脚本才显示预期答案、禁止错误和原文位置。输入：

- `p`：通过；
- `f`：失败；
- `s`：跳过；
- `q`：保存并退出。

结果持续写入 `evals/three-docs-v1/results/manual-时间.json`，中途退出不会丢失已评分项目。脚本不自动提交问题，也不会修改知识库。

按文档分批测试：

```bash
python3 evals/three-docs-v1/manual_review.py --source ft
python3 evals/three-docs-v1/manual_review.py --source burn
python3 evals/three-docs-v1/manual_review.py --source sdk
```

只测指定题，或从中断位置继续：

```bash
python3 evals/three-docs-v1/manual_review.py --ids FT02 BURN01 SDK08 SDK09
python3 evals/three-docs-v1/manual_review.py --source sdk --start SDK12
```

打印问题清单，或打印带答案的审核稿：

```bash
python3 evals/three-docs-v1/manual_review.py --questions-only
python3 evals/three-docs-v1/manual_review.py --with-answers
```

## 判定原则

每题建议满足以下条件才记 `pass`：

1. 覆盖全部 `expected` 核心要点；
2. 没有出现任一 `forbidden` 行为；
3. 数字、单位、型号、命令和路径准确；
4. References 指向实际支持回答的源文档；
5. 对当前设备状态等文档不能证明的内容，不做无依据确定断言。

如果事实正确但漏一个次要点，可先记 `fail` 并在备注中写“部分通过”，后续汇总时再区分检索缺失、生成遗漏、表格串行或引用错误。

## 校验

```bash
python3 evals/three-docs-v1/validate.py
```

该命令只检查 JSON 结构、题目数量和三份文档的题量分布，不会调用模型，也不能代替人工正确性审核。

## 已知边界

- 本集是可见回归集，后续若持续针对这 60 题调参，应另建一批不参与调参的盲测题。
- Release Note 的问题依据 PDF 可辨识正文和表格建立；PDF 重新解析、升级版本或替换文件后，要重新核对数字。
- 文档写明的性能数据是指定测试条件下的结果，不等同于当前 RAG 端到端响应时间或当前设备实时状态。
