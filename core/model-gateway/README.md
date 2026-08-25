# LightRAG RK1828 Model Gateway

This board-local process adapts the resident C++ JSONL daemons to HTTP:

- `POST /v1/chat/completions` — Qwen3.5-9B LLM
- `POST /v1/embeddings` — Qwen3-Embedding-0.6B
- `POST /v1/rerank` — Qwen3-Reranker-0.6B
- `GET /health`, `GET /v1/models`

It starts each configured daemon only once, then serializes requests to that
daemon. It does not load weights per request.

## Board configuration

Create `/userdata/lightrag-rk1828-model-gateway.env`. Commands must contain no
shell quoting: the gateway parses them with `shlex`.

```bash
export RK_GATEWAY_HOST=127.0.0.1
export RK_GATEWAY_PORT=8100

# The LLM command must end with --daemon.
export RK_LLM_COMMAND='/userdata/rk1828-rag-model-service/bin/multicard/rknn_multicard_demo ... --daemon unused 128 0 0'

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

Both vector workers are pinned to the third card. First measure each one alone;
then enable both commands and verify the card's memory use and tail latency.
The gateway keeps each successfully started worker resident rather than loading
model weights for every request.

## Smoke tests

```bash
curl http://127.0.0.1:8100/health
curl http://127.0.0.1:8100/v1/models
curl -s http://127.0.0.1:8100/v1/chat/completions -H 'content-type: application/json' -d '{"messages":[{"role":"user","content":"一句话解释 RAG。"}],"max_tokens":64}'
curl -s http://127.0.0.1:8100/v1/embeddings -H 'content-type: application/json' -d '{"input":"检索增强生成"}'
```

`/v1/rerank` returns raw model logits in descending order. The scores are for
ordering candidate context, not calibrated probabilities.

## LightRAG configuration

Copy [`config/lightrag.env.example`](config/lightrag.env.example) into the
LightRAG `.env` after measuring the embedding dimension from the daemon's
`ready` event. LightRAG's `openai` bindings call this gateway directly for both
chat completion and embeddings; its `cohere` reranker binding accepts the
gateway's standard `results` response. Keep every model concurrency at `1`:
the gateway serializes each NPU daemon and this avoids unbounded request queues.

## Verified board result

On the RK3588 + three RK1828 configuration, all three endpoints were verified
against the deployed models:

- Embedding: 1024 dimensions; gateway-returned vector L2 norm is `1.0`.
- Reranker: `RAG retrieval` ranked above an unrelated weather passage
  (`0.9873` versus approximately `0`).
- Chat completion: Qwen3.5-9B returned a Chinese RAG definition through
  `/v1/chat/completions`; first-token time was about `242 ms` after its
  one-time two-card initialization.
