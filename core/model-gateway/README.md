# LightRAG RK1828 Model Gateway

This board-local process presents one API for the vendor LLM HTTP server and
the resident vector-model JSONL daemons:

- `POST /v1/chat/completions` — Qwen3.5 LLM through `rkllm3-server`
- `POST /v1/embeddings` — Qwen3-Embedding-0.6B
- `POST /v1/rerank` — Qwen3-Reranker-0.6B
- `GET /health`, `GET /v1/models`

It starts the configured query workers once and serializes requests to each
worker. An optional ingestion LLM is switched once around a complete indexing
run, never once per chunk or query. Legacy `RK_LLM_COMMAND` JSONL workers
remain supported, but `RK_LLM_SERVER_COMMAND` selects the vendor HTTP server
backend.

When all three models use one RK1828, set `RK_GATEWAY_SINGLE_DEVICE=1`. The
gateway then serializes LLM, embedding and reranker execution with one shared
device lock. Without it, different HTTP requests may run the LLM and a vector
model concurrently even though each individual daemon is serialized.

On a 5 GB card, eagerly start the 2B query LLM and both vector workers.
Single-device mode initializes the larger reranker before embedding to avoid
the reranker's higher startup peak after embedding is already resident:

```bash
export RK_GATEWAY_EAGER_WORKERS=llm,reranker,embedding
```

## Board configuration

Create `/userdata/lightrag-rk1828-model-gateway.env`. Commands must contain no
shell quoting: the gateway parses them with `shlex`.

```bash
export RK_GATEWAY_HOST=127.0.0.1
export RK_GATEWAY_PORT=8100
export RK_GATEWAY_SINGLE_DEVICE=1

# The 2B model is resident in query mode.
export RK_LLM_MODEL=qwen3.5-2b
export RK_LLM_SERVER_URL=http://127.0.0.1:8080
export RK_LLM_SERVER_COMMAND='... rkllm3-server --alias qwen3.5-2b ... --port 8080 ...'

# In ingest mode the gateway stops 2B, embedding and reranker, starts 4B once,
# and lets embedding restart lazily when vector writes begin. On completion it
# restores 2B -> reranker -> embedding in that order.
export RK_GATEWAY_INGEST_MODE_ENABLED=1
export RK_INGEST_LLM_MODEL=qwen3.5-4b
export RK_INGEST_LLM_SERVER_URL=http://127.0.0.1:8080
export RK_INGEST_LLM_SERVER_COMMAND='... rkllm3-server --alias qwen3.5-4b ... --port 8080 ...'

# Pin both vector programs to the third RK1828. Prefixing env is intentionally
# avoided; put this into the systemd Environment= field instead.
export RK_EMBEDDING_COMMAND='/userdata/RK1828-qwen3-embedding-reranker-service/bin/rk1828_embedding_daemon --config /userdata/RK1828-qwen3-embedding-reranker-service/config/config.json'
export RK_RERANKER_COMMAND='/userdata/RK1828-qwen3-embedding-reranker-service/bin/rk1828_reranker_daemon --config /userdata/RK1828-qwen3-embedding-reranker-service/config/config.json'
export LD_LIBRARY_PATH=/userdata/RK1828-qwen3-embedding-reranker-service/lib:/userdata/rk1828-rag-model-service/lib
```

Start it:

```bash
set -a
. /userdata/lightrag-rk1828-model-gateway.env
set +a
python3 /userdata/lightrag-rk1828-model-gateway/rk1828_model_gateway.py
```

All worker configs may be pinned to one card when its measured capacity is
sufficient. First measure each one alone; then enable all commands and verify
the card's combined memory use and tail latency.
The gateway keeps the query layout resident. Only a complete ingestion run
causes the 2B/4B phase transition; ordinary retrieval and generation never
reload the model.

For LLM requests, the gateway forwards its resolved output ceiling as both
OpenAI `max_tokens` and RKLLM `n_predict`. The server can therefore use a
different maximum for each request without restarting. `max_tokens` remains a
ceiling: generation still stops early on EOS. Multiple leading LightRAG system
messages are folded into one because Qwen3.5's bundled Jinja template accepts
only one system turn at the beginning.

## Smoke tests

```bash
curl http://127.0.0.1:8100/health
curl http://127.0.0.1:8100/v1/models
curl -s http://127.0.0.1:8100/v1/chat/completions -H 'content-type: application/json' -d '{"messages":[{"role":"user","content":"一句话解释 RAG。"}],"max_tokens":64}'
curl -s http://127.0.0.1:8100/v1/embeddings -H 'content-type: application/json' -d '{"input":"检索增强生成"}'
```

`/v1/rerank` returns raw model logits in descending order. The scores are for
ordering candidate context, not calibrated probabilities.

Embedding 响应的标准 `usage.prompt_tokens` 以及两类向量接口的 `rk_metrics`
来自 RKNN3 原生 `n_prefill_tokens`。`rk_metrics` 同时返回逐输入 token 数和按网关
内部请求耗时计算的 `effective_input_tps`；管理端 `/admin/chat-metrics` 使用相同口径。

## LightRAG configuration

Copy [`config/lightrag.env.example`](config/lightrag.env.example) into the
LightRAG `.env` after measuring the embedding dimension from the daemon's
`ready` event. LightRAG's `openai` bindings call this gateway directly for both
chat completion and embeddings; its `cohere` reranker binding accepts the
gateway's standard `results` response. Keep every model concurrency at `1`:
the gateway serializes each NPU daemon and this avoids unbounded request queues.

## Verified board result

On the single-RK1828 RK3588 configuration, all three endpoints were verified
against the deployed models:

- Embedding: 1024 dimensions; gateway-returned vector L2 norm is `1.0`.
- Reranker: `RAG retrieval` ranked above an unrelated weather passage
  (`0.9873` versus approximately `0`).
- Query chat completion uses resident Qwen3.5-2B. A direct mode-switch smoke
  test loaded Qwen3.5-4B for ingestion, generated a response, then restored
  Qwen3.5-2B plus both vector workers.
- A full LightRAG Mix query completed keyword extraction, embedding, reranking,
  and streamed final generation with all three models on one card.
