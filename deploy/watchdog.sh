#!/bin/bash
# ============================================================
# 火锅连锁餐饮 看门狗 — Jetson 盒子端服务保活
# 监控: Hub :8098 / Edge :9100 / VLM :8084
# 策略: 挂了自动重启，告警推 Mac
# v2 — P0-4 Hub HA: 健康检查增强 + 3连败重启 + ALIVE_TIMESTAMP
# ============================================================
WATCH_LOG="/tmp/hotpot-watchdog.log"
ALERT_URL="${ALERT_URL:-http://192.168.2.85:7890}"  # Mac告警回调
RESTART_COUNT_FILE="/tmp/hotpot-restart-count"
FAIL_COUNT_DIR="/tmp/hotpot-fail-count"              # 3-strike state
ALIVE_FILE="${HOTPOT_ALIVE_FILE:-/tmp/hotpot-hub-alive.timestamp}"
ALIVE_MAX_AGE_SEC="${ALIVE_MAX_AGE_SEC:-300}"        # 5 min stale → restart
STRIKE_MAX="${STRIKE_MAX:-3}"                        # 连续失败阈值

mkdir -p "$FAIL_COUNT_DIR"

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

# ─── fail counter (3-strike) ───

get_fail_count() {
    local svc=$1
    cat "$FAIL_COUNT_DIR/$svc" 2>/dev/null || echo 0
}

inc_fail_count() {
    local svc=$1
    local c=$(get_fail_count "$svc")
    echo $((c+1)) > "$FAIL_COUNT_DIR/$svc"
}

reset_fail_count() {
    local svc=$1
    echo 0 > "$FAIL_COUNT_DIR/$svc"
}

# ─── enhanced health check (Hub only — parses JSON) ───

check_hub_health() {
    local port=$1
    local resp
    resp=$(curl -s --max-time 3 "http://localhost:${port}/health" 2>/dev/null) || return 1

    # Parse JSON: check overall status
    local status
    status=$(echo "$resp" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('status',''))" 2>/dev/null)
    if [ "$status" != "ok" ]; then
        log "WATCHDOG: hub status=$status (expected 'ok')"
        return 1
    fi

    # Check DB connectivity
    local db_status
    db_status=$(echo "$resp" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('db_status',''))" 2>/dev/null)
    if [ "$db_status" != "ok" ]; then
        local db_error
        db_error=$(echo "$resp" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('db_error',''))" 2>/dev/null)
        log "WATCHDOG: hub db_status=$db_status error=$db_error"
        return 1
    fi

    # Check ALIVE_TIMESTAMP freshness
    if [ -f "$ALIVE_FILE" ]; then
        local file_age
        file_age=$(($(date +%s) - $(stat -c %Y "$ALIVE_FILE" 2>/dev/null || stat -f %m "$ALIVE_FILE" 2>/dev/null || echo 0)))
        if [ "$file_age" -gt "$ALIVE_MAX_AGE_SEC" ]; then
            log "WATCHDOG: hub ALIVE_TIMESTAMP stale (${file_age}s > ${ALIVE_MAX_AGE_SEC}s)"
            return 1
        fi
    else
        log "WATCHDOG: hub ALIVE_TIMESTAMP file missing"
        return 1
    fi

    return 0
}

# ─── simple health check (Edge/VLM — port only) ───

check_service() {
    local name=$1
    local IFS='|' read -r port cmd <<< "${SERVICES[$name]}"

    if [ "$name" = "hub" ]; then
        check_hub_health "$port"
        return
    fi

    if curl -s --max-time 3 "http://localhost:${port}/health" 2>/dev/null | grep -q ok; then
        return 0
    fi
    return 1
}

# ─── restart handler with 3-strike logic ───

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
        reset_fail_count "$name"
    else
        log "WATCHDOG: $name :$port 重启失败 ✗"
    fi

    # 推送告警到Mac
    curl -s -X POST "$ALERT_URL" -d "watchdog: $name :$port restarted (#$count)" 2>/dev/null || true
}

# ─── 主循环 ───
trap 'log "看门狗退出"; exit 0' INT TERM

log "========== 火锅连锁餐饮看门狗 v2 (HA) 启动 =========="
log "监控: Hub:8098 Edge:9100 VLM:8084 | 3-strike=${STRIKE_MAX} | alive_max_age=${ALIVE_MAX_AGE_SEC}s"

while true; do
    for svc in hub edge vlm; do
        if ! check_service "$svc"; then
            # Increment fail counter; restart only after STRIKE_MAX consecutive failures
            inc_fail_count "$svc"
            local fails=$(get_fail_count "$svc")
            log "WATCHDOG: $svc 健康检查失败 ($fails/${STRIKE_MAX})"
            if [ "$fails" -ge "$STRIKE_MAX" ]; then
                restart_service "$svc"
            fi
        else
            # Service healthy — reset counter
            current=$(get_fail_count "$svc")
            if [ "$current" != "0" ]; then
                reset_fail_count "$svc"
                log "WATCHDOG: $svc 恢复正常 ✓ (fail counter reset)"
            fi
        fi
    done
    sleep 30
done
