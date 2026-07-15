#!/bin/bash
# ============================================================
# 火锅连锁餐饮 看门狗 — Jetson 盒子端服务保活
# 监控: Hub :8098 / Edge :9100 / VLM :8084
# 策略: 挂了自动重启，告警推 Mac
# ============================================================
WATCH_LOG="/tmp/hotpot-watchdog.log"
ALERT_URL="${ALERT_URL:-http://192.168.2.85:7890}"  # Mac告警回调
RESTART_COUNT_FILE="/tmp/hotpot-restart-count"

# ─── 服务定义 ───
declare -A SERVICES
SERVICES[hub]='8098|cd /opt/hotpot-infer && PYTHONPATH=. python3 -m uvicorn hotpot_platform.cloud.event_hub.app:app --host 0.0.0.0 --port 8098'
SERVICES[edge]='9100|cd /opt/hotpot-infer && HOTPOT_DEV_MODE=1 HOTPOT_HUB_URL=http://localhost:8098 HOTPOT_STORE_ID=store_yuhuan HOTPOT_DEVICE_ID=jetson-yuhuan-01 PYTHONPATH=. python3 -m uvicorn edge.agent.server:app --host 0.0.0.0 --port 9100'
SERVICES[vlm]='8084|export LD_LIBRARY_PATH=/opt/hotpot-infer/bin && /opt/hotpot-infer/bin/llama-server -m /opt/hotpot-infer/models/qwen2-vl-2b/qwen2-vl-2b-instruct-Q4_K_M.gguf --mmproj /opt/hotpot-infer/models/qwen2-vl-2b/mmproj-f16.gguf --host 0.0.0.0 --port 8084'

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" >> "$WATCH_LOG"; }

restart_count() {
    local svc=$1
    local f="$RESTART_COUNT_FILE-$svc"
    local c=$(cat "$f" 2>/dev/null || echo 0)
    echo $((c+1)) > "$f"
    echo $c
}

check_service() {
    local name=$1
    local IFS='|' read -r port cmd <<< "${SERVICES[$name]}"
    
    if curl -s --max-time 3 "http://localhost:${port}/health" 2>/dev/null | grep -q ok; then
        return 0
    fi
    return 1
}

restart_service() {
    local name=$1
    local IFS='|' read -r port cmd <<< "${SERVICES[$name]}"
    local count=$(restart_count "$name")
    
    log "WATCHDOG: $name :$port 挂了，第${count}次重启..."
    
    # 杀掉残留
    fuser -k ${port}/tcp 2>/dev/null
    sleep 1
    
    # 启动
    nohup bash -c "$cmd" > "/tmp/${name}.log" 2>&1 &
    sleep 4
    
    if check_service "$name"; then
        log "WATCHDOG: $name :$port 重启成功 ✓"
    else
        log "WATCHDOG: $name :$port 重启失败 ✗"
    fi
    
    # 推送告警到Mac
    curl -s -X POST "$ALERT_URL" -d "watchdog: $name :$port restarted (#$count)" 2>/dev/null || true
}

# ─── 主循环 ───
trap 'log "看门狗退出"; exit 0' INT TERM

log "========== 火锅连锁餐饮看门狗启动 =========="
log "监控: Hub:8098 Edge:9100 VLM:8084"

while true; do
    for svc in hub edge vlm; do
        if ! check_service "$svc"; then
            restart_service "$svc"
        fi
    done
    sleep 30
done
