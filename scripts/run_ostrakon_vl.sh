#!/bin/bash
# Ostrakon-VL-8B 推理脚本 (Jetson Orin)
# 部署路径: /root/run_ostrakon_vl.sh (Jetson 192.168.2.240)
# 本文件为参考副本，实际部署在 Jetson 盒子上
#
# 用法: bash run_ostrakon_vl.sh <image_path>
# 环境变量:
#   VLM_PROMPT - 推理 prompt（默认中文后厨废料识别）
#   OLLAMA_HOST - llama.cpp 服务地址（默认 localhost:11434）

set -euo pipefail

IMAGE="$1"
PROMPT="${VLM_PROMPT:-你是一个后厨废料识别系统。分析这张图片中的废弃食材/餐余。}"
MODEL_DIR="${MODEL_DIR:-/root/models/ostrakon-vl-8b}"
MMPROJ="${MMPROJ:-${MODEL_DIR}/mmproj-ostrakon-vl-8b.gguf}"
MODEL="${MODEL:-${MODEL_DIR}/ostrakon-vl-8b-iq4xs.gguf}"

export CUDA_VISIBLE_DEVICES=0

exec llama-mtmd-cli \
    -m "$MODEL" \
    --mmproj "$MMPROJ" \
    --image "$IMAGE" \
    --temp 0.1 \
    -p "$PROMPT" \
    --no-display-prompt \
    2>/dev/null
