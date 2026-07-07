#!/bin/bash
# edge/scripts/download_models.sh
# 边缘端模型下载脚本 — 在 Docker build 或 deploy 时运行
# 模型文件不进 Git，从此脚本从指定 URL 下载

set -euo pipefail

MODEL_DIR="${MODEL_DIR:-/opt/hotpot-infer/models}"
mkdir -p "$MODEL_DIR"

# ===== 模型清单 =====
# 格式: "文件名 | 下载URL | SHA256(可选)"

MODELS=(
  # YOLOv8n — 目标检测（~6MB）
  "yolov8n.pt|https://github.com/ultralytics/assets/releases/download/v8.2.0/yolov8n.pt|"

  # YOLOv8s — 更高精度版本（~22MB）
  "yolov8s.pt|https://github.com/ultralytics/assets/releases/download/v8.2.0/yolov8s.pt|"

  # kitchen_compliance — 厨房合规检测
  "kitchen_compliance.onnx|PLACEHOLDER_URL|"

  # table_state — 桌面状态检测
  "table_state.onnx|PLACEHOLDER_URL|"

  # CLIP ViT-B/32 — 自动下载（PyTorch hub）
  # pip install git+https://github.com/openai/CLIP.git 时自动缓存
)

download_model() {
  local name="$1"
  local url="$2"
  local sha256="$3"
  local target="$MODEL_DIR/$name"

  if [ -f "$target" ]; then
    echo "[skip] $name already exists"
    return 0
  fi

  if [ "$url" = "PLACEHOLDER_URL" ]; then
    echo "[skip] $name — URL not configured yet"
    return 0
  fi

  echo "[download] $name ← $url"
  curl -fSL --connect-timeout 30 --max-time 600 -o "$target" "$url"

  if [ -n "$sha256" ]; then
    echo "[verify] $name SHA256..."
    echo "$sha256  $target" | sha256sum -c -
  fi

  echo "[done] $name"
}

echo "=== Hotpot Edge Model Download ==="
echo "Target: $MODEL_DIR"

for entry in "${MODELS[@]}"; do
  IFS='|' read -r name url sha <<< "$entry"
  download_model "$name" "$url" "$sha"
done

echo "=== All models ready ==="
ls -lh "$MODEL_DIR"/*.pt "$MODEL_DIR"/*.onnx 2>/dev/null || echo "(some models not downloaded — PLACEHOLDER_URL)"
