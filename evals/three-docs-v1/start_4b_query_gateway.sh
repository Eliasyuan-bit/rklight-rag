#!/bin/sh
set -a
. /userdata/rklight-rag/core/model-gateway/deploy/rk3588.env
export RK_LLM_MODEL=qwen3.5-4b
export RK_QUERY_MODEL=qwen3.5-4b-query
export RK_LLM_SERVER_COMMAND='/usr/bin/rkllm3-server --alias qwen3.5-4b --model /userdata/RK1828-qwen3.5-4b-service/models/Qwen3.5-4B/Qwen3.5-4B.rknn --weight /userdata/RK1828-qwen3.5-4b-service/models/Qwen3.5-4B/Qwen3.5-4B.weight --vocab /userdata/RK1828-qwen3.5-4b-service/models/Qwen3.5-4B/Qwen3.5-4B.tokenizer.gguf --embed /userdata/RK1828-qwen3.5-4b-service/models/Qwen3.5-4B/Qwen3.5-4B.embed.bin --device-id 0001:11:00.0 --host 127.0.0.1 --port 8080 --ctx-size 4096 --n-predict 512 --core-mask 0xff --top-k 1 --top-p 0.0 --temp 0.0 --reasoning off --reasoning-format deepseek --log-level 1'
exec python3 /userdata/rklight-rag/core/model-gateway/rk1828_model_gateway.py
