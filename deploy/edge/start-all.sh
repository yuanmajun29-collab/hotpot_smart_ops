#!/bin/bash
# ============================================================
#  火瞳 · 椒江店 一键启动脚本
#  启动所有边缘盒子服务: Agent + Pipeline + Demo UI + Edge UI
#
#  用法:
#    ./start-all.sh          # 启动全部服务
#    ./start-all.sh stop     # 停止全部服务
#    ./start-all.sh status   # 查看服务状态
# ============================================================

set -e

# ── 配置 ──
JETSON_DIR="/opt/hotpot-smart-ops"
LOG_DIR="/tmp"
STORE_ID="jiaojiang"

# 服务端口
PORT_DEMO=8080          # Demo Web UI (展会演示)
PORT_EDGE_UI=9080       # Edge UI (配置界面)
PORT_AGENT=9100         # Edge Agent API

# 颜色输出
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info()  { echo -e "${GREEN}[INFO]${NC}  $*"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
log_error() { echo -e "${RED}[ERROR]${NC} $*"; }

# ── 停止所有服务 ──
stop_all() {
    log_info "停止所有火瞳服务..."
    
    pkill -f "server.py.*$PORT_DEMO" 2>/dev/null && log_info "  Demo Web UI 已停止" || true
    pkill -f "server.py.*$PORT_EDGE_UI" 2>/dev/null && log_info "  Edge UI 已停止" || true
    pkill -f "edge.agent.server" 2>/dev/null && log_info "  Edge Agent 已停止" || true
    pkill -f "ipc_frame_grabber" 2>/dev/null && log_info "  IPC抓帧器 已停止" || true
    pkill -f "inference.pipeline" 2>/dev/null && log_info "  推理Pipeline 已停止" || true
    
    sleep 2
    log_info "所有服务已停止"
}

# ── 检查状态 ──
status_all() {
    echo ""
    echo "╔══════════════════════════════════════════════╗"
    echo "║     🔥 火瞳 · 椒江店 服务状态                ║"
    echo "╚══════════════════════════════════════════════╝"
    echo ""
    
    services=(
        ["Demo Web UI"]="server.py.*$PORT_DEMO:$PORT_DEMO"
        ["Edge UI"]="server.py.*$PORT_EDGE_UI:$PORT_EDGE_UI"
        ["Edge Agent"]="edge.agent.server:$PORT_AGENT"
        ["IPC抓帧器"]="ipc_frame_grabber:-"
        ["推理Pipeline"]="inference.pipeline:-"
    )
    
    all_running=true
    for name in "${!services[@]}"; do
        IFS=':' read -r pattern port <<< "${services[$name]}"
        if pgrep -f "$pattern" > /dev/null 2>&1; then
            if [ "$port" != "-" ]; then
                status=$(curl -s -o /dev/null -w "%{http_code}" "http://127.0.0.1:$port/" 2>/dev/null || echo "000")
                echo -e "  ${GREEN}●${NC} $name → http://$(hostname -I | awk '{print $1}'):$port [HTTP:$status]"
            else
                echo -e "  ${GREEN}●${NC} $name → 运行中"
            fi
        else
            echo -e "  ${RED}○${NC} $name → 未运行"
            all_running=false
        fi
    done
    
    echo ""
    if $all_running; then
        log_info "✅ 所有服务正常运行"
    else
        log_warn "⚠️ 部分服务未运行，请执行 ./start-all.sh 启动"
    fi
}

# ── 启动所有服务 ──
start_all() {
    log_info "启动火瞳椒江店全量服务..."
    cd "$JETSON_DIR"
    
    # 1. Demo Web UI (:8080)
    if ! pgrep -f "server.py.*$PORT_DEMO" > /dev/null 2>&1; then
        nohup python3 demo/web/server.py --port $PORT_DEMO \
            > "$LOG_DIR/hotpot-demo.log" 2>&1 &
        log_info "  [1/4] Demo Web UI 启动中... :$PORT_DEMO"
    else
        log_warn "  [1/4] Demo Web UI 已在运行"
    fi
    
    # 2. Edge UI (:9080)
    if ! pgrep -f "server.py.*$PORT_EDGE_UI" > /dev/null 2>&1; then
        nohup python3 edge-ui/server.py --port $PORT_EDGE_UI \
            > "$LOG_DIR/edge-ui.log" 2>&1 &
        log_info "  [2/4] Edge UI 启动中... :$PORT_EDGE_UI"
    else
        log_warn "  [2/4] Edge UI 已在运行"
    fi
    
    # 3. Edge Agent (:9100) - 如果代码存在
    if [ -f "edge/agent/server.py" ]; then
        if ! pgrep -f "edge.agent.server" > /dev/null 2>&1; then
            nohup python3 -m edge.agent.server --port $PORT_AGENT \
                > "$LOG_DIR/hotpot-agent.log" 2>&1 &
            log_info "  [3/4] Edge Agent 启动中... :$PORT_AGENT"
        else
            log_warn "  [3/4] Edge Agent 已在运行"
        fi
    else
        log_warn "  [3/4] Edge Agent 代码不存在，跳过"
    fi
    
    # 4. IPC 抓帧器 + Pipeline - 需要配置文件
    CONFIG_FILE="edge/common/config/ipc_config_${STORE_ID}.yml"
    if [ -f "$CONFIG_FILE" ]; then
        # 检查是否为模拟模式
        if grep -q 'mock_mode:\s*enabled:\s*true' "$CONFIG_FILE" 2>/dev/null; then
            log_info "  [4/4] 当前为模拟模式（RTSP待开启），Pipeline使用模拟数据"
        else
            if ! pgrep -f "ipc_frame_grabber" > /dev/null 2>&1; then
                nohup python3 -m edge.kitchen.capture.ipc_frame_grabber \
                    --config "$CONFIG_FILE" > "$LOG_DIR/ipc-grabber.log" 2>&1 &
                log_info "  [4/4a] IPC抓帧器启动中..."
            fi
            
            if ! pgrep -f "inference.pipeline" > /dev/null 2>&1; then
                PIPELINE_CONFIG="edge/common/config/pipeline_config_${STORE_ID}.yml"
                nohup python3 -m edge.kitchen.inference.pipeline \
                    --config "$PIPELINE_CONFIG" > "$LOG_DIR/hotpot-pipeline.log" 2>&1 &
                log_info "  [4/4b] 推理Pipeline启动中..."
            fi
        fi
    else
        log_warn "  [4/4] 配置文件 $CONFIG_FILE 不存在，跳过Pipeline"
    fi
    
    # 等待启动
    sleep 3
    
    # 输出访问地址
    echo ""
    echo "╔══════════════════════════════════════════════╗"
    echo "║     🎉 火瞳椒江店 · 服务已启动              ║"
    echo "╠══════════════════════════════════════════════╣"
    LOCAL_IP=$(hostname -I | awk '{print $1}')
    echo "║  展会演示:  http://$LOCAL_IP:$PORT_DEMO           ║"
    echo "║  设备配置:  http://$LOCAL_IP:$PORT_EDGE_UI         ║"
    echo "║  Agent API: http://$LOCAL_IP:$PORT_AGENT          ║"
    echo "╠══════════════════════════════════════════════╣"
    echo "║  日志目录:  $LOG_DIR/hotpot-*.log             ║"
    echo "║  停止服务:  ./start-all.sh stop               ║"
    echo "╚══════════════════════════════════════════════╝"
}

# ── 主入口 ──
case "${1:-start}" in
    start)   start_all ;;
    stop)    stop_all ;;
    status)  status_all ;;
    restart) stop_all; sleep 2; start_all ;;
    *)       echo "用法: $0 {start|stop|restart|status}" ;;
esac
