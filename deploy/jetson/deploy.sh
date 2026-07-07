#!/bin/bash
# ──────────────────────────────────────────────
# Jetson 增量部署：同步代码 → 检查模型 → 重启 → 验证
# 无编译过程。llama-server 应已由 build.sh 预编译。
#
# 首次：./build.sh（编译 + 下载模型）
# 日常：./deploy.sh
#
# 用法：./deploy.sh [ngl层数，默认20]
# ──────────────────────────────────────────────
set -euo pipefail

NGL="${1:-20}"
JETSON_HOST="${JETSON_HOST:-jetson}"
CONTAINER="${CONTAINER:-hotpot-kitchen}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
REMOTE_MODEL_DIR="/opt/hotpot-infer/models"
REMOTE_BIN_DIR="/opt/hotpot-infer/bin"
MODEL_GGUF="Ostrakon-VL-8B.IQ4_XS.gguf"
MODEL_MMPROJ="Ostrakon-VL-8B.mmproj-Q8_0.gguf"
MODEL_BASE="ostrakon-vl-8b"

echo "============================================"
echo " Jetson 增量部署 (ngl=${NGL})"
echo " Target: ${JETSON_HOST}"
echo "============================================"

# ── Step 0: 检查前置条件 ──
echo ""
echo "[0/4] 检查前置条件 ..."

# 检查 llama-server 二进制
if ! ssh "$JETSON_HOST" "[ -f $REMOTE_BIN_DIR/llama-server-cuda ]" 2>/dev/null; then
  echo "  ❌ $REMOTE_BIN_DIR/llama-server-cuda 不存在"
  echo "  👉 请先运行: cd deploy/jetson && JETSON_HOST=$JETSON_HOST ./build.sh"
  exit 1
fi
echo "  ✅ llama-server-cuda 就绪"

# 检查模型 — 缺失则自动下载
echo "  - 检查模型..."
MODEL_OK=$(ssh "$JETSON_HOST" "[ -f $REMOTE_MODEL_DIR/$MODEL_BASE/$MODEL_GGUF ] && [ -f $REMOTE_MODEL_DIR/$MODEL_BASE/$MODEL_MMPROJ ] && echo yes || echo no" 2>/dev/null)

if [ "$MODEL_OK" = "no" ]; then
  echo "  ⚠️  模型缺失，自动下载到板端..."

  # 确保目录存在
  ssh "$JETSON_HOST" "mkdir -p $REMOTE_MODEL_DIR/$MODEL_BASE"

  # 下载 GGUF（Ostrakon-VL-8B IQ4_XS 量化版，约 5GB）
  echo "  ⬇️  下载 $MODEL_GGUF ..."
  ssh "$JETSON_HOST" "
    cd $REMOTE_MODEL_DIR/$MODEL_BASE
    if [ ! -f $MODEL_GGUF ]; then
      # HuggingFace: bartowski/Ostrakon-VL-8B-GGUF
      HF_URL='https://huggingface.co/bartowski/Ostrakon-VL-8B-GGUF/resolve/main'
      wget -q --show-progress --continue \"\${HF_URL}/Ostrakon-VL-8B.IQ4_XS.gguf\" 2>&1 | tail -5
    fi
  " || {
    echo "  ❌ 下载 $MODEL_GGUF 失败"
    echo "  👉 手动下载放到: $REMOTE_MODEL_DIR/$MODEL_BASE/"
    exit 1
  }
  echo "  ✅ $MODEL_GGUF"

  # 下载 mmproj
  echo "  ⬇️  下载 $MODEL_MMPROJ ..."
  ssh "$JETSON_HOST" "
    cd $REMOTE_MODEL_DIR/$MODEL_BASE
    if [ ! -f $MODEL_MMPROJ ]; then
      HF_URL='https://huggingface.co/bartowski/Ostrakon-VL-8B-GGUF/resolve/main'
      wget -q --show-progress --continue \"\${HF_URL}/Ostrakon-VL-8B.mmproj-Q8_0.gguf\" 2>&1 | tail -5
    fi
  " || {
    echo "  ❌ 下载 $MODEL_MMPROJ 失败"
    exit 1
  }
  echo "  ✅ $MODEL_MMPROJ"
  echo "  ✅ 模型下载完成"
else
  echo "  ✅ 模型就绪"
fi

# ── Step 1: 停止旧服务 ──
echo ""
echo "[1/4] 停止旧服务 ..."
ssh "$JETSON_HOST" bash << 'STOP'
set -e
CONTAINER=hotpot-kitchen
pkill -f llama-server 2>/dev/null || true
docker exec $CONTAINER pkill -f llama-server 2>/dev/null || true
sleep 2
echo "  ✅ 已停止"
STOP

# ── Step 2: 同步代码 ──
echo ""
echo "[2/4] 同步代码 ..."

# jetson_server.py
scp "$SCRIPT_DIR/jetson_server.py" "$JETSON_HOST:/tmp/jetson_server_new.py"
ssh "$JETSON_HOST" "docker cp /tmp/jetson_server_new.py $CONTAINER:/workspace/jetson_server.py && rm /tmp/jetson_server_new.py"
echo "  ✅ jetson_server.py"

# pipeline 模块
if [ -d "$PROJECT_ROOT/edge/kitchen/pipeline" ]; then
  ssh "$JETSON_HOST" "docker exec $CONTAINER mkdir -p /workspace/pipeline"
  tar czf - -C "$PROJECT_ROOT/edge/kitchen" pipeline/ 2>/dev/null | \
    ssh "$JETSON_HOST" "docker exec -i $CONTAINER tar xzf - -C /workspace/"
  echo "  ✅ pipeline/"
fi

# bridge
if [ -f "$PROJECT_ROOT/edge/kitchen/bridge_waste_vision.py" ]; then
  scp "$PROJECT_ROOT/edge/kitchen/bridge_waste_vision.py" "$JETSON_HOST:/tmp/bridge_new.py"
  ssh "$JETSON_HOST" "docker cp /tmp/bridge_new.py $CONTAINER:/workspace/bridge_waste_vision.py && rm /tmp/bridge_new.py"
  echo "  ✅ bridge_waste_vision.py"
fi

# detector
if [ -d "$PROJECT_ROOT/edge/shared/detector" ]; then
  ssh "$JETSON_HOST" "docker exec $CONTAINER mkdir -p /workspace/detector"
  tar czf - -C "$PROJECT_ROOT/edge/shared" detector/ 2>/dev/null | \
    ssh "$JETSON_HOST" "docker exec -i $CONTAINER tar xzf - -C /workspace/"
  echo "  ✅ detector/"
fi

echo "  ✅ 代码同步完成"

# ── Step 3: 启动服务 ──
echo ""
echo "[3/4] 启动服务 ..."

ssh "$JETSON_HOST" bash << 'START'
set -e
CONTAINER=hotpot-kitchen
BIN_DIR='/opt/hotpot-infer/bin'
NGL='"${NGL}"'

docker restart $CONTAINER
sleep 5

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

echo "  ✅ 已启动"
START

sleep 60

# ── Step 4: 验证 ──
echo ""
echo "[4/4] 验证 ..."

HEALTH=$(curl -s "http://${JETSON_HOST}:9200/health" 2>/dev/null || echo '{"status":"loading"}')
echo "$HEALTH" | python3 -m json.tool 2>/dev/null || echo "$HEALTH"

echo ""
echo "=== 测试推理 ==="
curl -s -X POST "http://${JETSON_HOST}:9200/infer" \
  -H "Content-Type: application/json" \
  -d '{"image_path":"/data/real_hotpot_waste.jpg"}' \
  | python3 -m json.tool 2>/dev/null | head -30

echo ""
echo "============================================"
echo " ✅ 部署完成"
echo " Health: http://${JETSON_HOST}:9200/health"
echo "============================================"
