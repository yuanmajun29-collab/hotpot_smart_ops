#!/usr/bin/env bash
# ============================================================
# 火瞳（HotpotEye）— 统一停止脚本 v2.0
# 用法: bash scripts/stop.sh [hub|edge|all]
# ============================================================
set -euo pipefail

PORTS=(8098 9080 8084 3000)
NAMES=("Hub" "Edge-UI" "VLM" "Dashboard")

TARGET="${1:-all}"

echo "🛑 停止火瞳服务 ..."

for i in "${!PORTS[@]}"; do
    PORT="${PORTS[$i]}"
    NAME="${NAMES[$i]}"

    # 跳过非目标
    if [[ "$TARGET" != "all" ]]; then
        case $TARGET in
            hub)  [[ "$NAME" != "Hub" ]] && continue ;;
            edge) [[ "$NAME" != "Edge-UI" ]] && continue ;;
            vlm)  [[ "$NAME" != "VLM" ]] && continue ;;
            dash) [[ "$NAME" != "Dashboard" ]] && continue ;;
        esac
    fi

    PID=$(lsof -ti:$PORT 2>/dev/null || true)
    if [[ -n "$PID" ]]; then
        kill -9 "$PID" 2>/dev/null && echo "  ✅ 已停止 $NAME :$PORT (PID $PID)"
    else
        echo "  ⏭️  $NAME :$PORT 未运行"
    fi
done

echo ""
echo "✅ 所有请求的服务已停止"
