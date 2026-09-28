# Engineered Mix RAG v33 Evaluation

Date: 2026-09-15  
Target: RK3588 + RK1828, Qwen3.5-4B  
Default query mode: `mix`

## Configuration

- `top_k=6`, `chunk_top_k=3`
- entity budget 500 tokens, relation budget 300 tokens, total context budget 3000 tokens
- vector + BM25 weighted RRF, exact-evidence boosts, reranking, source authority policy
- intent-specific output contracts with a runtime generation cap of 256 tokens

## Smoke comparison

| Run | API success | Queries with references | Median TTFT | Median total |
| --- | ---: | ---: | ---: | ---: |
| Earlier Mix baseline | 10/10 | 6/10 | 7816.6 ms | 9437.1 ms |
| Engineered Mix v30 | 10/10 | 10/10 | 6470.4 ms | 7746.1 ms |

The v30 release smoke result is `release-mix-v30-20260915-144537+0800.json`.
The v33 reproduction regression result is `mix-reproduction-v33-20260915-145222+0800.json`.

## Manual acceptance

The ten smoke cases were inspected rather than counted as passed solely from HTTP status:

- FT USB failure causes distinguish missing device, `speed!=5000`, and missing `timestamps`.
- Missing `timestamps` after a successful USB speed check is classified as ADB failure.
- FT log location and the `Executing_Test` to `Done_Test` search window are retained.
- PCIe virtual console entry and exit commands are retained.
- ROCKRAGCLAW reproduction is five complete steps. The v33 follow-up adds the authorization chain, model directory, and `run.sh` / `run_server.sh` startup anchors.
- Unix socket readiness returns the exact `curl --unix-socket` command and expected JSON.
- Account-based RAG authorization returns the exact `rkauth_tool_bin` command.
- Repeated-device authorization and the USB-dongle exception are kept distinct.
- Current-device questions refuse to infer live state from historical documents.

The FT1/FIT1/IQC comparison was also checked separately in Mix mode. Section-scoped passage selection prevents `SET_PN` from being copied into FT1 and retains FIT1's `BURN_CHECK_PN`, `SN_MATCH_FAN_DET`, and `SET_PN`, plus IQC's `PN_GET`.

## Operational notes

- Warm TTFT is generally about 5.4–8.0 seconds in the final smoke.
- The first request after restarting both services can take about 16–27 seconds because embedding and reranker workers initialize lazily.
- The active optimized services are transient systemd units; reboot-persistent service installation is outside this evaluation.
