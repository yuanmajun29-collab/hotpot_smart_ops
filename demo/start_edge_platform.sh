#!/usr/bin/env bash
# 一键启动边缘推理平台（推理后端 + Dashboard）
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo "========================================="
echo " 边缘推理平台 · 一键启动"
echo "========================================="

kill_old() {
  local port=$1 name=$2
  local pid=$(lsof -ti:$port 2>/dev/null || true)
  if [[ -n "$pid" ]]; then
    echo "[$name] Killing old process on :$port (PID $pid)..."
    kill "$pid" 2>/dev/null || true
    sleep 1
  fi
}

# 1. Start edge inference API
kill_old 8090 "Inference"
echo "[Inference] Starting on :8090..."
PYTHONPATH="$ROOT" nohup python3 edge/server.py --port 8090 > /tmp/edge-inference.log 2>&1 &
INFER_PID=$!
sleep 3

if curl -sf http://127.0.0.1:8090/health > /dev/null 2>&1; then
  echo "[Inference] ✅ Running (PID $INFER_PID)"
else
  echo "[Inference] ❌ Failed! Check /tmp/edge-inference.log"
  exit 1
fi

# 2. Start dashboard
kill_old 3000 "Dashboard"
echo "[Dashboard] Starting on :3000..."
nohup python3 dashboard/serve.py --port 3000 > /tmp/edge-dashboard.log 2>&1 &
DASH_PID=$!
sleep 1

if curl -sf http://127.0.0.1:3000/edge-vision.html > /dev/null 2>&1; then
  echo "[Dashboard] ✅ Running (PID $DASH_PID)"
else
  echo "[Dashboard] ❌ Failed! Check /tmp/edge-dashboard.log"
  exit 1
fi

echo ""
echo "========================================="
echo " ✅ 平台就绪"
echo " Dashboard: http://127.0.0.1:3000/edge-vision.html"
echo " API:       http://127.0.0.1:8090/health"
echo "========================================="
echo ""
echo "停止: kill $INFER_PID $DASH_PID"
