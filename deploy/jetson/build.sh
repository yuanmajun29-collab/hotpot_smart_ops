#!/bin/bash
# ──────────────────────────────────────────────
# Jetson 首次构建：编译 llama.cpp + 下载模型
# 只跑一次。之后日常用 deploy.sh 增量部署。
#
# 用法：./build.sh
# ──────────────────────────────────────────────
set -euo pipefail

JETSON_HOST="${JETSON_HOST:-jetson}"
CONTAINER="${CONTAINER:-hotpot-kitchen}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "============================================"
echo " Jetson 首次构建"
echo " Target: ${JETSON_HOST}"
echo "============================================"

# ── Step 1: 编译 llama.cpp (CUDA) ──
echo ""
echo "[1/2] 编译 llama-server (CUDA) ..."

ssh "$JETSON_HOST" bash << 'BUILD'
set -e
CONTAINER=hotpot-kitchen

echo "  - git clone llama.cpp ..."
docker exec $CONTAINER bash -c '
cd /tmp
rm -rf llama.cpp
git clone --depth=1 https://github.com/ggerganov/llama.cpp.git 2>&1 | tail -3
'

echo "  - cmake + make (j2) ..."
docker exec $CONTAINER bash -c '
set -e
cd /tmp/llama.cpp
mkdir -p build_cuda && cd build_cuda

cmake .. \
  -DGGML_CUDA=ON \
  -DCMAKE_CUDA_ARCHITECTURES="87" \
  -DGGML_CUDA_FORCE_MMQ=ON \
  -DCMAKE_BUILD_TYPE=Release \
  2>&1 | tail -3

make -j2 llama-server 2>&1 | tail -5

# 安装到标准路径
mkdir -p /opt/hotpot-infer/bin
cp bin/llama-server /opt/hotpot-infer/bin/llama-server-cuda
cp bin/*.so /opt/hotpot-infer/bin/ 2>/dev/null || true

ls -lh /opt/hotpot-infer/bin/llama-server-cuda
echo "  ✅ 编译完成"
'

# 验证
docker exec $CONTAINER /opt/hotpot-infer/bin/llama-server-cuda --version 2>&1 | head -1 || echo "  (version check skipped)"
BUILD

# ── Step 2: 下载模型 ──
echo ""
echo "[2/2] 下载模型 ..."

if [ -f "$SCRIPT_DIR/download_models.sh" ]; then
  bash "$SCRIPT_DIR/download_models.sh"
else
  echo "  ⚠️  download_models.sh 不存在，跳过"
  echo "  模型需手动放到板端 /models/ 目录"
fi

echo ""
echo "============================================"
echo " ✅ 首次构建完成"
echo ""
echo " 下次部署直接跑: ./deploy.sh"
echo "============================================"
