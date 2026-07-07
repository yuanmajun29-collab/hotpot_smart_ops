#!/bin/bash
# ──────────────────────────────────────────────
# Jetson 全量部署：清空 → 重编译 → 部署
# 用法：./deploy.sh [ngl层数，默认20]
# ──────────────────────────────────────────────
set -euo pipefail

NGL="${1:-20}"
JETSON_HOST="${JETSON_HOST:-jetson}"
CONTAINER="${CONTAINER:-hotpot-kitchen}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
REMOTE_LLAMA_SRC="/opt/hotpot-infer/llama.cpp"
REMOTE_BIN_DIR="/opt/hotpot-infer/bin"

echo "============================================"
echo " Jetson 全量部署 (ngl=${NGL})"
echo "============================================"

# ── Step 0: 清空 ──
echo ""
echo "[0/4] 清空盒子上原有内容 ..."
ssh "$JETSON_HOST" bash << 'CLEANUP'
set -e
CONTAINER=hotpot-kitchen

echo "  - 杀掉 llama-server 进程..."
pkill -f llama-server 2>/dev/null || true
docker exec $CONTAINER pkill -f llama-server 2>/dev/null || true
sleep 2

echo "  - 清空 llama.cpp 源码和编译产物..."
rm -rf /opt/hotpot-infer/llama.cpp /tmp/llama_src /tmp/llama.cpp
docker exec $CONTAINER rm -rf /tmp/llama_src /tmp/llama.cpp 2>/dev/null || true

echo "  - 恢复干净二进制目录..."
rm -f /opt/hotpot-infer/bin/llama-server-cuda /opt/hotpot-infer/bin/*.so
# 确保 CPU 版备份存在
[ -f /opt/hotpot-infer/bin/llama-server ] && cp /opt/hotpot-infer/bin/llama-server /opt/hotpot-infer/bin/llama-server-cpu.bak 2>/dev/null || true

echo "  - 容器日志清理..."
docker exec $CONTAINER rm -f /tmp/llama-server.log /tmp/llama-gpu.log /tmp/llama-gpu2.log 2>/dev/null || true

echo "  ✅ 清空完成"
CLEANUP

# ── Step 1: Git clone 最新 llama.cpp ──
echo ""
echo "[1/4] 拉取 llama.cpp 源码 ..."
ssh "$JETSON_HOST" bash << 'CLONE'
set -e
CONTAINER=hotpot-kitchen
docker exec $CONTAINER bash -c '
cd /tmp
git clone --depth=1 https://github.com/ggerganov/llama.cpp.git 2>&1 | tail -3
echo "clone OK: $(du -sh llama.cpp | cut -f1)"
'
CLONE

# ── Step 2: 编译 CUDA 版 ──
echo ""
echo "[2/4] 编译 CUDA 版 llama-server (ngl=${NGL}) ..."
ssh "$JETSON_HOST" bash << 'BUILD'
set -e
CONTAINER=hotpot-kitchen
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

echo "cmake OK, compiling (j2)..."

make -j2 llama-server 2>&1 | tail -5
echo "BUILD_EXIT: $?"

ls -lh bin/llama-server
ldd bin/llama-server | grep -c cuda && echo "CUDA linked OK"

# 复制编译产物到标准路径
cp bin/llama-server /opt/hotpot-infer/bin/llama-server-cuda
cp bin/*.so /opt/hotpot-infer/bin/ 2>/dev/null || true
echo "copied to /opt/hotpot-infer/bin/"
'
BUILD

# ── Step 3: 部署 jetson_server.py ──
echo ""
echo "[3/4] 部署 jetson_server.py ..."
scp "$SCRIPT_DIR/jetson_server.py" "$JETSON_HOST:/tmp/jetson_server_new.py"
ssh "$JETSON_HOST" "docker cp /tmp/jetson_server_new.py $CONTAINER:/workspace/edge/jetson_server.py"
echo "  ✅ 已同步"

# ── Step 4: 重启容器 ──
echo ""
echo "[4/4] 重启容器 + 启动 GPU llama-server ..."
ssh "$JETSON_HOST" bash << 'START'
set -e
CONTAINER=hotpot-kitchen
NGL='"${NGL}"'

docker restart $CONTAINER
sleep 5

docker exec -d $CONTAINER bash -c "
pkill -f llama-server 2>/dev/null || true
sleep 1

/opt/hotpot-infer/bin/llama-server-cuda \
  -m /models/ostrakon-vl-8b/Ostrakon-VL-8B.IQ4_XS.gguf \
  --mmproj /models/ostrakon-vl-8b/Ostrakon-VL-8B.mmproj-Q8_0.gguf \
  --host 127.0.0.1 --port 8080 --no-webui \
  -ngl $NGL \
  > /tmp/llama-server.log 2>&1 &

echo \"GPU llama-server PID: \$!\"
"

echo "  ✅ 已启动，等待模型加载..."
START

echo ""
echo "============================================"
echo " 部署完成！等待 60s 模型加载..."
echo "============================================"
sleep 60

echo ""
echo "=== 验证 ==="
curl -s "http://${JETSON_HOST}:9200/health" 2>/dev/null | python3 -m json.tool || echo "⏳ 服务还在加载中..."

echo ""
echo "=== llama-server 日志（最后 5 行）==="
ssh "$JETSON_HOST" "docker exec $CONTAINER tail -5 /tmp/llama-server.log 2>/dev/null"

echo ""
echo "=== 跑测试 ==="
curl -s -X POST "http://${JETSON_HOST}:9200/infer" \
  -H "Content-Type: application/json" \
  -d '{"image_path":"/images/real_hotpot_waste.jpg"}' \
  | python3 -m json.tool 2>/dev/null | head -30
