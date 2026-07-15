#!/bin/bash
# ──────────────────────────────────────────────
# 边缘服务 Docker 入口脚本
# 启动顺序: llama-server(VLM) → edge agent → 设备注册 → 推理循环
# ──────────────────────────────────────────────
set -e

echo "============================================"
echo " Hotpot Edge Server starting..."
echo " Device: ${HOTPOT_DEVICE_ID:-jetson-yuhuan-01}"
echo " Store:  ${HOTPOT_STORE_ID:-store_yuhuan}"
echo " Hub:    ${HOTPOT_HUB_URL:-http://192.168.2.85:8098}"
echo "============================================"

MODEL_DIR="${MODEL_DIR:-/opt/hotpot-infer/models}"
VLM_MODEL="${VLM_MODEL:-$MODEL_DIR/qwen2-vl-2b.gguf}"
LLAMA_BIN="${LLAMA_BIN:-/opt/hotpot-infer/bin/llama-server-cuda}"

# ── Step 1: 启动 llama-server（VLM 推理）──
if [ -f "$LLAMA_BIN" ] && [ -f "$VLM_MODEL" ]; then
    echo "[1/4] Starting llama-server for VLM..."
    $LLAMA_BIN \
        -m "$VLM_MODEL" \
        --host 0.0.0.0 --port 8080 \
        -ngl "${LLAMA_NGL:-999}" \
        -c 4096 \
        --no-webui \
        > /tmp/llama-server.log 2>&1 &
    LLAMA_PID=$!
    echo "  llama-server PID=$LLAMA_PID :8080"
else
    echo "[1/4] ⚠️  llama-server or VLM model not found"
    echo "  LLAMA_BIN=$LLAMA_BIN"
    echo "  VLM_MODEL=$VLM_MODEL"
    echo "  → 跳过 VLM，仅运行 YOLO+CLIP"
fi

# ── Step 2: 等待 llama-server 就绪 ──
if [ -n "${LLAMA_PID:-}" ]; then
    echo "[2/4] Waiting for llama-server..."
    for i in $(seq 1 30); do
        if curl -s http://localhost:8080/health > /dev/null 2>&1; then
            echo "  ✅ llama-server ready"
            break
        fi
        sleep 2
    done
fi

# ── Step 3: 启动 Edge Agent ──
echo "[3/4] Starting Edge Agent :9100..."
cd /workspace
exec python3 -m uvicorn edge.agent.server:app --host 0.0.0.0 --port 9100 &

AGENT_PID=$!
sleep 3

# ── Step 4: 首次注册到 Hub ──
echo "[4/4] Registering with Hub..."
DEVICE_ID="${HOTPOT_DEVICE_ID:-jetson-yuhuan-01}"
STORE_ID="${HOTPOT_STORE_ID:-store_yuhuan}"
HUB_URL="${HOTPOT_HUB_URL:-http://192.168.2.85:8098}"

curl -s -X POST "$HUB_URL/v1/devices/register" \
    -H "Content-Type: application/json" \
    -d "{
        \"device_id\": \"$DEVICE_ID\",
        \"store_id\": \"$STORE_ID\",
        \"ip\": \"$(hostname -I | awk '{print $1}')\",
        \"device_type\": \"jetson\",
        \"active_modules\": [\"kitchen\", \"front_hall\"]
    }" > /dev/null 2>&1 || echo "  ⚠️ 无法连接 Hub: $HUB_URL"

echo ""
echo "============================================"
echo " ✅ Edge Server Ready"
echo "    Agent: http://localhost:9100"
echo "    VLM:   http://localhost:8080 (if available)"
echo "    Hub:   $HUB_URL"
echo "============================================"

# 保持进程存活
wait $AGENT_PID
