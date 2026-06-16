#!/usr/bin/env bash
# Start periodic vision workers for pilot stores (background).
# Usage: run_vision_daemon.sh [hub_url] [interval_seconds]
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

PID_DIR="${ROOT}/demo/data/.pids"
mkdir -p "$PID_DIR"

stop_workers() {
  for f in "$PID_DIR"/vision_*.pid; do
    [[ -f "$f" ]] || continue
    pid="$(cat "$f")"
    kill "$pid" 2>/dev/null || true
    rm -f "$f"
  done
}

if [[ "${1:-}" == "--stop" ]]; then
  stop_workers
  echo "[vision_daemon] stopped"
  exit 0
fi

HUB_URL="${1:-http://127.0.0.1:8088}"
INTERVAL="${2:-${VISION_INTERVAL:-5}}"
STORES="${STORES:-store_yuhuan,store_jiaojiang}"
BACKEND="${VISION_BACKEND:-${HOTPOT_DETECTOR_BACKEND:-mock}}"
UAT_ROOT="${HOTPOT_UAT_ROOT:-deploy/uat}"
RTSP_FLAG="${HOTPOT_RTSP_ENABLED:-1}"
export HOTPOT_RTSP_ENABLED="$RTSP_FLAG"
export HOTPOT_DETECTOR_BACKEND="$BACKEND"

stop_workers

IFS=',' read -ra PILOT_STORES <<< "$STORES"
for sid in "${PILOT_STORES[@]}"; do
  sid="$(echo "$sid" | xargs)"
  LIVE_DIR="demo/data/stores/${sid}/live"
  mkdir -p "$LIVE_DIR"
  LOG="${LIVE_DIR}/vision_worker.log"
  echo "[vision_daemon] starting ${sid} interval=${INTERVAL}s -> ${LOG}"
  nohup python3 edge/stream/vision_worker.py \
    --store-id "$sid" \
    --hub-url "$HUB_URL" \
    --backend "$BACKEND" \
    --uat-root "$ROOT/$UAT_ROOT" \
    --output-dir "$LIVE_DIR" \
    --interval "$INTERVAL" \
    --interval-from-config \
    --cycles 0 \
    >> "$LOG" 2>&1 &
  echo $! > "${PID_DIR}/vision_${sid}.pid"
done

echo "[vision_daemon] backend=${BACKEND} rtsp=${RTSP_FLAG} uat=${UAT_ROOT}"
echo "[vision_daemon] ${#PILOT_STORES[@]} worker(s) running (Ctrl+C safe; use --stop to kill)"
echo "  tail -f demo/data/stores/store_yuhuan/live/vision_worker.log"
