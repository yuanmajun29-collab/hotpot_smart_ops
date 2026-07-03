#!/usr/bin/env bash
# hotpot_smart_ops 一键启动（脱离 Hermes 进程树，独立存活）
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

kill_old() { local pid=$(lsof -ti:$1 2>/dev/null); [[ -n "$pid" ]] && kill -9 "$pid" 2>/dev/null && echo "  killed old :$1"; }

echo "🚀 启动火锅智能系统..."

# 1. Edge Inference (YOLO)
kill_old 8090
(cd "$ROOT" && PYTHONPATH="$ROOT" nohup python3 edge/server.py --port 8090 > /tmp/edge-8090.log 2>&1 &)
sleep 2 && curl -sf http://127.0.0.1:8090/health >/dev/null && echo "  ✅ Edge  :8090" || echo "  ❌ Edge  :8090"

# 2. Event Hub
kill_old 8098
(cd "$ROOT" && nohup python3 cloud/event_hub/server.py --port 8098 --auth-mode demo > /tmp/hub-8098.log 2>&1 &)
sleep 3 && curl -sf http://127.0.0.1:8098/health >/dev/null && echo "  ✅ Hub   :8098" || echo "  ❌ Hub   :8098"

# 3. Dashboard
kill_old 3000
(cd "$ROOT/dashboard" && nohup python3 -m http.server 3000 --bind 127.0.0.1 > /tmp/dash-3000.log 2>&1 &)
sleep 1 && curl -sf http://127.0.0.1:3000/edge-vision.html >/dev/null && echo "  ✅ Dash  :3000" || echo "  ❌ Dash  :3000"

echo ""
echo "🌐 http://127.0.0.1:3000/edge-vision.html"
echo "🛑 停止: bash scripts/stop_all.sh"
