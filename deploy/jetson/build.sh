#!/bin/bash
# ──────────────────────────────────────────────
# Jetson 首次构建（源码端 Mac 执行）
# 编译 llama.cpp → 打入 Docker 镜像 → 推板端
#
# 只跑一次。之后日常用 deploy.sh 增量部署。
# 用法：./build.sh
# ──────────────────────────────────────────────
set -euo pipefail

JETSON_HOST="${JETSON_HOST:-jetson}"
IMAGE="hotpot-kitchen:latest"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

echo "============================================"
echo " Jetson 镜像构建（源码端 → 板端）"
echo " Target: ${JETSON_HOST}"
echo "============================================"

# ── Step 1: 构建 Docker 镜像（含 llama.cpp 编译）──
echo ""
echo "[1/3] 构建镜像（含 llama.cpp 编译，约 5-10 分钟）..."

docker build \
  --platform linux/arm64 \
  -f "$SCRIPT_DIR/Dockerfile" \
  -t "$IMAGE" \
  "$PROJECT_ROOT"

echo "  ✅ 镜像构建完成: $IMAGE"

# ── Step 2: 推镜像到板端 ──
echo ""
echo "[2/3] 推送镜像到板端..."

docker save "$IMAGE" | ssh "$JETSON_HOST" "docker load"

echo "  ✅ 镜像已推送到板端"

# ── Step 3: 下载模型到板端 ──
echo ""
echo "[3/3] 模型下载到板端..."

if [ -f "$SCRIPT_DIR/download_models.sh" ]; then
  # download_models.sh 内部需要知道 JETSON_HOST
  JETSON_HOST="$JETSON_HOST" bash "$SCRIPT_DIR/download_models.sh"
else
  echo "  ⚠️  download_models.sh 不存在，跳过"
  echo "  模型需手动放到: $JETSON_HOST:/opt/hotpot-infer/models/"
fi

echo ""
echo "============================================"
echo " ✅ 首次构建完成"
echo ""
echo " 板端已有:"
echo "   - Docker 镜像: $IMAGE (含编译好的 llama-server)"
echo "   - 模型: /opt/hotpot-infer/models/"
echo ""
echo " 下次部署: cd deploy/jetson && JETSON_HOST=$JETSON_HOST ./deploy.sh"
echo "============================================"
