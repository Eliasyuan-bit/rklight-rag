#!/bin/sh
set -eu

model_dir=/userdata/RK1828-qwen3.5-4b-service/models/Qwen3.5-4B
export LD_LIBRARY_PATH=/userdata/RK1828-qwen3.5-4b-service/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}

exec /usr/bin/rkllm3-server \
  --alias qwen3.5-4b \
  --model "$model_dir/Qwen3.5-4B.rknn" \
  --weight "$model_dir/Qwen3.5-4B.weight" \
  --vocab "$model_dir/Qwen3.5-4B.tokenizer.gguf" \
  --embed "$model_dir/Qwen3.5-4B.embed.bin" \
  --device-id 0001:11:00.0 \
  --host 127.0.0.1 --port 8080 \
  --ctx-size 4096 --n-predict 512 --core-mask 0xff \
  --top-k 1 --top-p 0.0 --temp 0.0 \
  --reasoning off --reasoning-format deepseek --log-level 1
