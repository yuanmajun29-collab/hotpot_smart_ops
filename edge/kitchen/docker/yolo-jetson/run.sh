#!/usr/bin/env bash
# 不依赖 docker compose：在 Jetson 上直接 build + run（需已配置 nvidia runtime）
set -euo pipefail
IMAGE="${IMAGE:-yolo-jetson-infer:local}"
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

cd "$ROOT_DIR"
docker build -t "$IMAGE" .

exec docker run --rm -it \
  --runtime=nvidia \
  --network=host \
  --ipc=host \
  -e NVIDIA_VISIBLE_DEVICES=all \
  -e NVIDIA_DRIVER_CAPABILITIES=compute,utility \
  -v "$ROOT_DIR/models:/models:ro" \
  -v "$ROOT_DIR/data:/data:ro" \
  -v "$ROOT_DIR/runs:/workspace/runs" \
  -w /workspace \
  "$IMAGE" \
  "$@"
