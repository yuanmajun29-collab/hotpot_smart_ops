#!/usr/bin/env bash
# BL-02 IoT 打桩：无需 MQTT broker / 真设备，直接向 Hub 推送模拟传感器数据
# Usage:
#   ./scripts/run_iot_stub.sh                    # 两店 normal 场景
#   ./scripts/run_iot_stub.sh door_alert         # 演示门磁超时告警
#   ./scripts/run_iot_stub.sh --stop
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

PID_DIR="${ROOT}/demo/data/.pids"
mkdir -p "$PID_DIR"

stop_stubs() {
  for f in "$PID_DIR"/iot_stub_*.pid; do
    [[ -f "$f" ]] || continue
    pid="$(cat "$f")"
    kill "$pid" 2>/dev/null || true
    rm -f "$f"
  done
  echo "[iot_stub] stopped"
}

if [[ "${1:-}" == "--stop" ]]; then
  stop_stubs
  exit 0
fi

SCENARIO="${1:-normal}"
HUB_URL="${HOTPOT_HUB_URL:-http://127.0.0.1:8088}"
INTERVAL="${IOT_STUB_INTERVAL:-30}"
EXTRA_ARGS=()
if [[ "${FAST_DEMO:-}" == "1" || "$SCENARIO" == "door_alert" ]]; then
  EXTRA_ARGS+=(--fast-demo)
fi

stop_stubs 2>/dev/null || true

for sid in store_yuhuan store_jiaojiang; do
  LOG="${ROOT}/demo/data/stores/${sid}/live/iot_stub.log"
  mkdir -p "$(dirname "$LOG")"
  echo "[iot_stub] starting ${sid} scenario=${SCENARIO} -> ${LOG}"
  nohup python3 edge/iot_mock/iot_stub_bridge.py \
    --store-id "$sid" \
    --hub-url "$HUB_URL" \
    --scenario "$SCENARIO" \
    --interval "$INTERVAL" \
    --cycles 0 \
    "${EXTRA_ARGS[@]}" \
    >> "$LOG" 2>&1 &
  echo $! > "${PID_DIR}/iot_stub_${sid}.pid"
done

echo "[iot_stub] 2 stub worker(s) running — tail demo/data/stores/*/live/iot_stub.log"
echo "[iot_stub] door_alert demo: FAST_DEMO=1 ./scripts/run_iot_stub.sh door_alert"
