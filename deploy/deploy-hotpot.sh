#!/bin/bash
# ============================================================
# 火锅连锁餐饮 — 一键部署 + 监控
# Mac 源码 → Jetson 盒子 → 全链路验证 → 实时监控
# ============================================================
set -euo pipefail

JETSON_HOST="${JETSON_HOST:-192.168.2.240}"
JETSON_USER="${JETSON_USER:-root}"
JETSON_DIR="${JETSON_DIR:-/opt/hotpot-infer}"
SRC_DIR="${SRC_DIR:-$HOME/company/products/to-b/hotpot_smart_ops}"
STORE_ID="${STORE_ID:-store_yuhuan}"
DEVICE_ID="${DEVICE_ID:-jetson-yuhuan-01}"
LOG_FILE="/tmp/hotpot-deploy-$(date +%Y%m%d-%H%M%S).log"
TEST_IMG="${TEST_IMG:-/tmp/hotpot-test/scene_05_overflow.jpg}"

GREEN='\033[0;32m'; RED='\033[0;31m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; NC='\033[0m'
log()   { echo -e "${GREEN}[$(date +%H:%M:%S)]${NC} $*" | tee -a "$LOG_FILE"; }
warn()  { echo -e "${YELLOW}[$(date +%H:%M:%S)] WARN:${NC} $*" | tee -a "$LOG_FILE"; }
err()   { echo -e "${RED}[$(date +%H:%M:%S)] ERR:${NC} $*" | tee -a "$LOG_FILE"; }
check() { echo -e "  ${GREEN}✓${NC} $*" | tee -a "$LOG_FILE"; }
fail()  { echo -e "  ${RED}✗${NC} $*" | tee -a "$LOG_FILE"; }
info()  { echo -e "  ${BLUE}ℹ${NC} $*" | tee -a "$LOG_FILE"; }

# ─── 辅助函数 ───
jetson() { ssh ${JETSON_USER}@${JETSON_HOST} "$@"; }
health_check() {
    local port=$1 name=$2
    if curl -s --max-time 3 "http://${JETSON_HOST}:${port}/health" 2>/dev/null | grep -q ok; then
        return 0
    fi
    return 1
}

# ═══════════════════════════════════════════════
# Phase 0: 环境检查
# ═══════════════════════════════════════════════
phase0_check() {
    log "Phase 0: 环境自检"
    [ -d "$SRC_DIR" ] || { err "源码目录 $SRC_DIR 不存在"; exit 1; }
    check "Mac 源码: $SRC_DIR"
    
    if ssh -o ConnectTimeout=5 ${JETSON_USER}@${JETSON_HOST} "echo ok" >/dev/null 2>&1; then
        check "Jetson: ${JETSON_USER}@${JETSON_HOST}"
    else
        fail "Jetson 不可达"; exit 1
    fi
    
    jetson "[ -f ${JETSON_DIR}/yolov8n.pt ]" 2>/dev/null && check "YOLO 模型" || warn "YOLO 模型未找到"
    jetson "[ -f ${JETSON_DIR}/models/qwen2-vl-2b/*.gguf ]" 2>/dev/null && check "VL 模型" || warn "VL 模型未找到（VLM 跳过）"
}

# ═══════════════════════════════════════════════
# Phase 1: 推送源码
# ═══════════════════════════════════════════════
phase1_push() {
    log "Phase 1: rsync 源码 → Jetson"
    jetson "mkdir -p ${JETSON_DIR}"
    rsync -avz --delete \
        --exclude '.git' --exclude '__pycache__' --exclude '*.pyc' \
        --exclude '.venv' --exclude 'node_modules' --exclude 'runs' \
        --exclude 'models/' --exclude 'bin/' \
        --exclude 'hotpot_platform/dashboard/' \
        "$SRC_DIR/" ${JETSON_USER}@${JETSON_HOST}:${JETSON_DIR}/ \
        2>&1 | tail -2 | tee -a "$LOG_FILE"
    check "源码推送完成"
}

# ═══════════════════════════════════════════════
# Phase 2: Python 依赖
# ═══════════════════════════════════════════════
phase2_deps() {
    log "Phase 2: pip 安装依赖"
    jetson "
        pip install -i https://pypi.tuna.tsinghua.edu.cn/simple \
            fastapi uvicorn httpx pyyaml opencv-python-headless \
            python-multipart sse-starlette starlette-context pydantic-settings \
            backports.zoneinfo \
            'ultralytics>=8.0,<8.3' 'torchvision>=0.15,<0.16' \
            2>&1 | tail -3
    "
    check "Python 依赖就绪"
}

# ═══════════════════════════════════════════════
# Phase 3: 停止旧服务
# ═══════════════════════════════════════════════
phase3_stop() {
    log "Phase 3: 停止旧服务"
    jetson "
        pkill -f 'edge.agent.server' 2>/dev/null || true
        pkill -f 'hotpot_platform.cloud.event_hub' 2>/dev/null || true
        pkill -f llama-server 2>/dev/null || true
        sleep 2
    " 2>/dev/null
    check "旧服务已停止"
}

# ═══════════════════════════════════════════════
# Phase 4: 编译 VLM (如果需要)
# ═══════════════════════════════════════════════
phase4_vlm() {
    log "Phase 4: VLM 推理服务"
    
    # 检查是否已有二进制
    if jetson "[ -x ${JETSON_DIR}/bin/llama-server ]" 2>/dev/null; then
        check "llama-server 已就绪"
        SKIP_VLM_COMPILE=1
    else
        SKIP_VLM_COMPILE=0
    fi
    
    if [ "$SKIP_VLM_COMPILE" = "1" ]; then
        # 直接启动
        jetson "
            mkdir -p ${JETSON_DIR}/scripts
            cat > ${JETSON_DIR}/scripts/start-vlm.sh << 'SSCRIPT'
#!/bin/bash
export LD_LIBRARY_PATH=/opt/hotpot-infer/bin
exec /opt/hotpot-infer/bin/llama-server \
  -m /opt/hotpot-infer/models/qwen2-vl-2b/qwen2-vl-2b-instruct-Q4_K_M.gguf \
  --mmproj /opt/hotpot-infer/models/qwen2-vl-2b/mmproj-f16.gguf \
  --host 0.0.0.0 --port 8084
SSCRIPT
            chmod +x ${JETSON_DIR}/scripts/start-vlm.sh
            nohup ${JETSON_DIR}/scripts/start-vlm.sh > /tmp/vlm.log 2>&1 &
        " 2>/dev/null
        sleep 8
        if jetson "curl -s --max-time 3 localhost:8084/health | grep -q ok" 2>/dev/null; then
            check "VLM :8084 启动成功"
        else
            fail "VLM 启动失败，查看 /tmp/vlm.log"
        fi
        return
    fi
    
    # 首次编译
    warn "首次部署，编译 llama.cpp (约 5 分钟)..."
    jetson "
        export http_proxy=http://localhost:17890 https_proxy=http://localhost:17890
        cd /tmp
        [ -d llama.cpp ] || git clone --depth=1 https://github.com/ggerganov/llama.cpp.git 2>/dev/null
        cd llama.cpp && mkdir -p build && cd build
        cmake .. -DGGML_CUDA=OFF -DCMAKE_BUILD_TYPE=Release 2>/dev/null
        make -j2 llama-server 2>/dev/null
        mkdir -p ${JETSON_DIR}/bin
        cp bin/* ${JETSON_DIR}/bin/ 2>/dev/null
        echo 'version:'\$(cd /tmp/llama.cpp && git rev-parse --short HEAD)
    " 2>&1 | tail -3 | tee -a "$LOG_FILE"
    
    if jetson "[ -x ${JETSON_DIR}/bin/llama-server ]" 2>/dev/null; then
        check "llama-server 编译成功"
        SKIP_VLM_COMPILE=1
        phase4_vlm  # 递归调用启动
    else
        fail "llama-server 编译失败"
    fi
}

# ═══════════════════════════════════════════════
# Phase 5: 启动 Hub
# ═══════════════════════════════════════════════
phase5_hub() {
    log "Phase 5: 启动 Hub :8098"
    jetson "
        cd ${JETSON_DIR}
        PYTHONPATH=. nohup python3 -m uvicorn \
            hotpot_platform.cloud.event_hub.app:app \
            --host 0.0.0.0 --port 8098 \
            > /tmp/hub.log 2>&1 &
    " 2>/dev/null
    sleep 4
    if jetson "curl -s --max-time 3 localhost:8098/health | grep -q ok" 2>/dev/null; then
        check "Hub :8098"
    else
        fail "Hub 启动失败"; return 1
    fi
}

# ═══════════════════════════════════════════════
# Phase 6: 启动 Edge Agent
# ═══════════════════════════════════════════════
phase6_edge() {
    log "Phase 6: 启动 Edge Agent :9100"
    jetson "
        cd ${JETSON_DIR}
        HOTPOT_DEV_MODE=1 HOTPOT_HUB_URL=http://localhost:8098 \
        HOTPOT_STORE_ID=${STORE_ID} HOTPOT_DEVICE_ID=${DEVICE_ID} \
        PYTHONPATH=. nohup python3 -m uvicorn \
            edge.agent.server:app --host 0.0.0.0 --port 9100 \
            > /tmp/edge-agent.log 2>&1 &
    " 2>/dev/null
    sleep 4
    if jetson "curl -s --max-time 3 localhost:9100/health | grep -q ok" 2>/dev/null; then
        check "Edge :9100"
    else
        fail "Edge Agent 启动失败"; return 1
    fi
}

# ═══════════════════════════════════════════════
# Phase 7: 激活 kitchen 模块
# ═══════════════════════════════════════════════
phase7_modules() {
    log "Phase 7: 激活 kitchen 模块"
    jetson "
        curl -s -X POST localhost:8098/v1/devices/register \
            -H 'Content-Type: application/json' \
            -d '{\"device_id\":\"${DEVICE_ID}\",\"store_id\":\"${STORE_ID}\"}' >/dev/null
        
        curl -s -X PUT localhost:8098/v1/devices/${DEVICE_ID}/config \
            -H 'Content-Type: application/json' \
            -d '{\"modules\":{\"kitchen\":{\"enabled\":true,\"cameras\":[\"file:///tmp/test.jpg\"],\"inference_interval\":30},\"front_hall\":{\"enabled\":false}}}' >/dev/null
        
        curl -s -X POST localhost:8098/v1/devices/${DEVICE_ID}/pull-config >/dev/null
    " 2>/dev/null
    sleep 3
    
    ACTIVE=$(jetson "curl -s localhost:9100/health | python3 -c 'import sys,json;print(json.load(sys.stdin).get(\"active_modules\",[])[0])'" 2>/dev/null || echo "")
    if [ "$ACTIVE" = "kitchen" ]; then
        check "kitchen 模块已激活"
    else
        warn "kitchen 未激活, 当前: $ACTIVE"
    fi
}

# ═══════════════════════════════════════════════
# Phase 8: 全链路验证
# ═══════════════════════════════════════════════
phase8_verify() {
    log "Phase 8: 全链路验证"
    
    # Hub
    health_check 8098 "Hub" && check "Hub :8098 ok" || fail "Hub :8098 down"
    
    # Edge
    health_check 9100 "Edge" && check "Edge :9100 ok" || fail "Edge :9100 down"
    
    # VLM
    health_check 8084 "VLM" && check "VLM :8084 ok" || warn "VLM :8084 down (非阻塞)"
    
    # YOLO 推理
    log "  YOLO 推理测试..."
    RESULT=$(jetson "curl -s 'localhost:9100/infer/kitchen/yolo?image_path=${TEST_IMG}&store_id=${STORE_ID}&device_id=${DEVICE_ID}'" 2>/dev/null)
    OK=$(echo "$RESULT" | python3 -c "import sys,json;print(json.load(sys.stdin)['ok'])" 2>/dev/null || echo "False")
    MS=$(echo "$RESULT" | python3 -c "import sys,json;print(json.load(sys.stdin)['inference_ms'])" 2>/dev/null || echo "?")
    
    if [ "$OK" = "True" ]; then
        check "YOLO 推理成功  耗时 ${MS}ms"
    else
        fail "YOLO 推理失败: $(echo $RESULT | head -c 200)"
    fi
}

# ═══════════════════════════════════════════════
# Phase 9: 部署状态面板
# ═══════════════════════════════════════════════
phase9_status() {
    echo ""
    echo "╔══════════════════════════════════════════════╗"
    echo "║       火锅连锁餐饮 · 部署完成                    ║"
    echo "╠══════════════════════════════════════════════╣"
    printf "║  Hub    %-36s ║\n" "http://${JETSON_HOST}:8098"
    printf "║  Edge   %-36s ║\n" "http://${JETSON_HOST}:9100"
    printf "║  VLM    %-36s ║\n" "http://${JETSON_HOST}:8084"
    printf "║  日志   %-36s ║\n" "$LOG_FILE"
    echo "╚══════════════════════════════════════════════╝"
}

# ═══════════════════════════════════════════════
# Phase 10: 实时监控
# ═══════════════════════════════════════════════
monitor() {
    log "实时监控 (Ctrl+C 退出)"
    printf "\n%-10s %-8s %-8s %-8s %-10s %s\n" "TIME" "HUB" "EDGE" "VLM" "YOLO(ms)" "STATUS"
    echo   "---------- -------- -------- -------- ---------- ------"
    
    while true; do
        HUB=$(curl -s --max-time 2 http://${JETSON_HOST}:8098/health 2>/dev/null | python3 -c "import sys,json;print(json.load(sys.stdin)['status'])" 2>/dev/null || echo "DOWN")
        EDGE=$(curl -s --max-time 2 http://${JETSON_HOST}:9100/health 2>/dev/null | python3 -c "import sys,json;print(json.load(sys.stdin)['status'])" 2>/dev/null || echo "DOWN")
        VLM_ST=$(curl -s --max-time 2 http://${JETSON_HOST}:8084/health 2>/dev/null | python3 -c "import sys,json;print(json.load(sys.stdin)['status'])" 2>/dev/null || echo "DOWN")
        
        # YOLO 推理测试
        YOLO_MS="?"
        STATUS="?"
        RESULT=$(jetson "curl -s --max-time 10 'localhost:9100/infer/kitchen/yolo?image_path=${TEST_IMG}&store_id=${STORE_ID}&device_id=${DEVICE_ID}' 2>/dev/null" 2>/dev/null)
        if [ -n "$RESULT" ]; then
            YOLO_MS=$(echo "$RESULT" | python3 -c "import sys,json;print(int(json.load(sys.stdin)['inference_ms']))" 2>/dev/null || echo "?")
            OK=$(echo "$RESULT" | python3 -c "import sys,json;print(json.load(sys.stdin)['ok'])" 2>/dev/null || echo "False")
            [ "$OK" = "True" ] && STATUS="OK" || STATUS="FAIL"
        fi
        
        # 颜色
        HUB_C="${GREEN}"; [ "$HUB" != "ok" ] && HUB_C="${RED}"
        EDGE_C="${GREEN}"; [ "$EDGE" != "ok" ] && EDGE_C="${RED}"
        VLM_C="${GREEN}"; [ "$VLM_ST" != "ok" ] && VLM_C="${YELLOW}"
        STATUS_C="${GREEN}"; [ "$STATUS" != "OK" ] && STATUS_C="${RED}"
        
        printf "${NC}%-10s ${HUB_C}%-8s${NC} ${EDGE_C}%-8s${NC} ${VLM_C}%-8s${NC} ${STATUS_C}%-10s${NC} ${STATUS_C}%s${NC}\n" \
            "$(date +%H:%M:%S)" "$HUB" "$EDGE" "$VLM_ST" "${YOLO_MS}ms" "$STATUS"
        
        sleep 10
    done
}

# ═══════════════════════════════════════════════
# 主流程
# ═══════════════════════════════════════════════
main() {
    echo ""
    echo "╔══════════════════════════════════════════════╗"
    echo "║  火锅连锁餐饮  一键部署  v2.0                    ║"
    echo "║  ${SRC_DIR}  →  ${JETSON_HOST}:${JETSON_DIR}"
    echo "╚══════════════════════════════════════════════╝"
    
    phase0_check
    phase1_push
    phase2_deps
    phase3_stop
    phase4_vlm
    phase5_hub
    phase6_edge
    phase7_modules
    phase8_verify
    phase9_status
    
    echo ""
    echo "输入 'm' 启动实时监控，其他任意键退出:"
    read -r CMD
    [ "$CMD" = "m" ] && monitor
}

case "${1:-}" in
    monitor) monitor ;;
    *) main ;;
esac
