#!/bin/bash
# ──────────────────────────────────────────────
# Jetson 增量部署：同步代码 → 重启服务 → 验证
# 无编译过程。llama-server 和模型应已预置在板端。
#
# 首次部署：先跑一次 build.sh（编译 llama.cpp + 下载模型）
# 日常部署：./deploy.sh
#
# 用法：./deploy.sh [ngl层数，默认20]
# ──────────────────────────────────────────────
set -euo pipefail

NGL="${1:-20}"
JETSON_HOST="${JETSON_HOST:-jetson}"
CONTAINER="${CONTAINER:-hotpot-kitchen}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
REMOTE_BIN_DIR="/opt/hotpot-infer/bin"

echo "============================================"
echo " Jetson 增量部署 (ngl=${NGL})"
echo " Target: ${JETSON_HOST}"
echo "============================================"

# ── Step 1: 停止旧服务 ──
echo ""
echo "[1/3] 停止旧服务 ..."
ssh "$JETSON_HOST" bash << 'STOP'
set -e
CONTAINER=hotpot-kitchen
echo "  - 停止 llama-server ..."
pkill -f llama-server 2>/dev/null || true
docker exec $CONTAINER pkill -f llama-server 2>/dev/null || true
sleep 2
echo "  ✅ 已停止"
STOP

# ── Step 2: 同步代码 ──
echo ""
echo "[2/3] 同步代码 ..."

# jetson_server.py
echo "  - jetson_server.py"
scp "$SCRIPT_DIR/jetson_server.py" "$JETSON_HOST:/tmp/jetson_server_new.py"
ssh "$JETSON_HOST" "docker cp /tmp/jetson_server_new.py $CONTAINER:/workspace/jetson_server.py"
ssh "$JETSON_HOST" "rm /tmp/jetson_server_new.py"

# 同步 pipeline 模块 (如有变更)
if [ -d "$PROJECT_ROOT/edge/kitchen/pipeline" ]; then
  echo "  - pipeline/"
  ssh "$JETSON_HOST" "docker exec $CONTAINER mkdir -p /workspace/pipeline"
  tar czf - -C "$PROJECT_ROOT/edge/kitchen" pipeline/ 2>/dev/null | \
    ssh "$JETSON_HOST" "docker exec -i $CONTAINER tar xzf - -C /workspace/"
fi

# 同步 bridge
echo "  - bridge_waste_vision.py"
scp "$PROJECT_ROOT/edge/kitchen/bridge_waste_vision.py" "$JETSON_HOST:/tmp/bridge_new.py" 2>/dev/null && \
  ssh "$JETSON_HOST" "docker cp /tmp/bridge_new.py $CONTAINER:/workspace/bridge_waste_vision.py && rm /tmp/bridge_new.py" || true

# 同步 detector (共用模块)
if [ -d "$PROJECT_ROOT/edge/shared/detector" ]; then
  echo "  - detector/"
  ssh "$JETSON_HOST" "docker exec $CONTAINER mkdir -p /workspace/detector"
  tar czf - -C "$PROJECT_ROOT/edge/shared" detector/ 2>/dev/null | \
    ssh "$JETSON_HOST" "docker exec -i $CONTAINER tar xzf - -C /workspace/"
fi

echo "  ✅ 代码同步完成"

# ── Step 3: 启动服务 + 验证 ──
echo ""
echo "[3/3] 启动服务 ..."

ssh "$JETSON_HOST" bash << 'START'
set -e
CONTAINER=hotpot-kitchen
BIN_DIR='/opt/hotpot-infer/bin'
NGL='"${NGL}"'

# 重启容器
docker restart $CONTAINER
sleep 5

# 检查二进制是否存在
if [ ! -f "$BIN_DIR/llama-server-cuda" ]; then
  echo "  ❌ $BIN_DIR/llama-server-cuda 不存在！请先运行 build.sh"
  exit 1
fi

# 启动 GPU llama-server
docker exec -d $CONTAINER bash -c "
pkill -f llama-server 2>/dev/null || true
sleep 1

$BIN_DIR/llama-server-cuda \
  -m /models/ostrakon-vl-8b/Ostrakon-VL-8B.IQ4_XS.gguf \
  --mmproj /models/ostrakon-vl-8b/Ostrakon-VL-8B.mmproj-Q8_0.gguf \
  --host 127.0.0.1 --port 8080 --no-webui \
  -ngl $NGL \
  > /tmp/llama-server.log 2>&1 &

echo \"GPU llama-server PID: \$!\"
"

echo "  ✅ 已启动，等待模型加载 (约 60s)..."
START

sleep 60

echo ""
echo "============================================"
echo " 验证服务..."
echo "============================================"

# Health check
echo ""
HEALTH=$(curl -s "http://${JETSON_HOST}:9200/health" 2>/dev/null || echo '{"status":"loading"}')
echo "$HEALTH" | python3 -m json.tool 2>/dev/null || echo "$HEALTH"

# 跑一次测试推理
echo ""
echo "=== 测试推理 ==="
curl -s -X POST "http://${JETSON_HOST}:9200/infer" \
  -H "Content-Type: application/json" \
  -d '{"image_path":"/images/real_hotpot_waste.jpg"}' \
  | python3 -m json.tool 2>/dev/null | head -30

echo ""
echo "============================================"
echo " ✅ 部署完成"
echo " Health: http://${JETSON_HOST}:9200/health"
echo "============================================"
