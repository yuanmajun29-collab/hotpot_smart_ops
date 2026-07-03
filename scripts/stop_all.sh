#!/usr/bin/env bash
set -euo pipefail
echo "🛑 停止火锅智能系统..."
for port in 8090 9090 3000; do
  pid=$(lsof -ti:$port 2>/dev/null) && kill -9 "$pid" && echo "  killed :$port" || echo "  :$port already stopped"
done
echo "✅ 全部停止"