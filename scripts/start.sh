#!/usr/bin/env bash
# ============================================================
# 火瞳（HotpotEye）— 统一启动脚本 v2.0
# 用法: bash scripts/start.sh [dev|pilot|prod] [hub|edge|all]
# 示例: bash scripts/start.sh dev all
#       bash scripts/start.sh pilot hub
# ============================================================
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

# ── 颜色定义 ──
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
ok()   { echo -e "  ${GREEN}✅ $1${NC}"; }
fail() { echo -e "  ${RED}❌ $1${NC}"; }
warn() { echo -e "  ${YELLOW}⚠️  $1${NC}"; }

MODE="${1:-dev}"
TARGET="${2:-all}"

echo "╔══════════════════════════════════════════════════╗"
echo "║     🔥 火瞳智能运营系统 · 统一启动 v2.0          ║"
echo "╠══════════════════════════════════════════════════╣"
echo "║  模式: ${MODE:<20} 目标: ${TARGET:<15} ║"
echo "╚══════════════════════════════════════════════════╝"
echo ""

# ── 端口配置（唯一真相源）──
HUB_PORT=8098      # 主 Hub (Event Hub)
EDGE_PORT=9080     # Edge UI (FastAPI)
VLM_PORT=8084      # VLM 服务 (可选)
DASH_PORT=3000     # Dashboard (开发用)

kill_old() {
    local port=$1
    local pid=$(lsof -ti:$port 2>/dev/null || true)
    if [[ -n "$pid" ]]; then
        kill -9 "$pid" 2>/dev/null && warn "已终止旧进程 :$port (PID $pid)"
    fi
}

wait_ready() {
    local url=$1
    local name=$2
    local max_wait=${3:-10}
    for i in $(seq 1 $max_wait); do
        if curl -sf "$url" >/dev/null 2>&1; then
            ok "$name 就绪 (${i}s)"
            return 0
        fi
        sleep 1
    done
    fail "$name 启动超时 (${max_wait}s)"
    return 1
}

# ── 启动主 Hub ──
start_hub() {
    echo "→ 启动主 Hub (Event Hub) :$HUB_PORT ..."
    kill_old $HUB_PORT

    case $MODE in
        dev)
            # 开发模式: demo数据 + 详细日志
            PYTHONPATH="$ROOT" nohup python3 hotpot_platform/cloud/event_hub/server.py \
                --port $HUB_PORT \
                --auth-mode demo \
                --seed-dir demo/data/stores \
                > /tmp/hotpot-hub.log 2>&1 &
            ;;
        pilot)
            # 试点模式: 真实数据库 + JWT认证
            PYTHONPATH="$ROOT" nohup python3 hotpot_platform/cloud/event_hub/server.py \
                --port $HUB_PORT \
                --auth-mode jwt \
                > /tmp/hotpot-hub.log 2>&1 &
            ;;
        prod)
            # 生产模式: 完整配置 + systemd管理
            fail "生产模式请使用 systemctl start hotpot-hub"
            return 1
            ;;
    esac

    sleep 3
    wait_ready "http://127.0.0.1:${HUB_PORT}/health" "Hub" 10
}

# ── 启动 Edge UI ──
start_edge() {
    echo "→ 启动 Edge UI :$EDGE_PORT ..."
    kill_old $EDGE_PORT

    # 使用正确的启动脚本（含PYTHONPATH）
    if [[ -f edge/edge-ui/start-edge-ui-fastapi.sh ]]; then
        (cd "$ROOT" && bash edge/edge-ui/start-edge-ui-fastapi.sh >/dev/null 2>&1) &
    else
        # 回退: 直接启动
        (cd "$ROOT/edge/edge-ui" && PYTHONPATH="$ROOT:$ROOT/edge" nohup python3 main.py \
            --host 0.0.0.0 --port $EDGE_PORT > /tmp/hotpot-edge.log 2>&1) &
    fi

    sleep 4
    wait_ready "http://127.0.0.1:${EDGE_PORT}/api/v1/system/status" "Edge UI" 10 || \
    wait_ready "http://127.0.0.1:${EDGE_PORT}/login.html" "Edge UI" 5
}

# ── 启动 VLM (可选) ──
start_vlm() {
    echo "→ 启动 VLM 服务 :$VLM_PORT (可选) ..."
    kill_old $VLM_PORT

    if command -v llama-server &>/dev/null; then
        (nohup llama-server --model models/qwen2-vl-q4f16.gguf \
            --port $VLM_PORT > /tmp/hotpot-vlm.log 2>&1) &
        sleep 5
        wait_ready "http://127.0.0.1:${VLM_PORT}/health" "VLM" 5 || warn "VLM未启动(非必需)"
    else
        warn "llama-server 未安装，跳过 VLM"
    fi
}

# ── Dashboard (仅开发) ──
start_dashboard() {
    if [[ "$MODE" != "dev" ]]; then return; fi
    echo "→ 启动 Dashboard :$DASH_PORT ..."
    kill_old $DASH_PORT
    (cd "$ROOT/dashboard" && nohup python3 -m http.server $DASH_PORT --bind 127.0.0.1 \
        > /tmp/hotpot-dash.log 2>&1) &
    sleep 1
    wait_ready "http://127.0.0.1:${DASH_PORT}/" "Dashboard" 3
}

# ── Smoke 检查 ──
smoke_test() {
    echo ""
    echo "🔥 执行 Smoke 检查 ..."

    local passed=0
    local failed=0

    # 检查 Hub
    if curl -sf "http://127.0.0.1:${HUB_PORT}/health" | grep -q "ok\|running"; then
        ((passed++)); ok "Hub health check"
    else
        ((failed++)); fail "Hub health check"
    fi

    # 检查 Edge UI
    if curl -sf "http://127.0.0.1:${EDGE_PORT}/login.html" >/dev/null 2>&1 || \
       curl -sf "http://127.0.0.1:${EDGE_PORT}/api/v1/cameras" >/dev/null 2>&1; then
        ((passed++)); ok "Edge UI health check"
    else
        ((failed++)); fail "Edge UI health check"
    fi

    echo ""
    echo "━━━ Smoke 结果: ${passed} 通过, ${failed} 失败 ━━━"

    if [[ $failed -gt 0 ]]; then
        return 1
    fi
}

# ── 主流程 ──
case $TARGET in
    hub)   start_hub ;;
    edge)  start_edge ;;
    vlm)   start_vlm ;;
    dash)  start_dashboard ;;
    all)
        start_hub
        start_edge
        start_vlm
        start_dashboard
        smoke_test
        ;;
    *)
        echo "用法: $0 [dev|pilot|prod] [hub|edge|vlm|dash|all]"
        exit 1
        ;;
esac

echo ""
echo "🌐 服务地址:"
[[ "$TARGET" =~ hub|all ]] && echo "   Hub:      http://127.0.0.1:${HUB_PORT}"
[[ "$TARGET" =~ edge|all ]] && echo "   Edge UI:  http://127.0.0.1:${EDGE_PORT}"
[[ "$TARGET" =~ vlm|all ]] && echo "   VLM:      http://127.0.0.1:${VLM_PORT}"
[[ "$TARGET" =~ dash|all && "$MODE" == "dev" ]] && echo "   Dashboard:http://127.0.0.1:${DASH_PORT}"
echo ""
echo "🛑 停止: bash scripts/stop.sh"
echo "📋 日志: tail -f /tmp/hotpot-*.log"
