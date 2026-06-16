#!/usr/bin/env bash
# BL-01: Switch pilot stores to RTSP+yolo and restart vision workers.
# Usage: ./scripts/enable_pilot_cv.sh [demo|pilot] [yolo|rknn]
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

MODE="${1:-pilot}"
BACKEND="${2:-yolo}"
HUB_URL="${HOTPOT_HUB_URL:-http://127.0.0.1:8088}"

python3 scripts/enable_pilot_cv.py --mode "$MODE" --backend "$BACKEND" --hub-url "$HUB_URL"

if [[ "$MODE" == "pilot" ]]; then
  export VISION_BACKEND="$BACKEND"
  export HOTPOT_RTSP_ENABLED=1
  export HOTPOT_DETECTOR_BACKEND="$BACKEND"
else
  export VISION_BACKEND=mock
  export HOTPOT_RTSP_ENABLED=0
  export HOTPOT_DETECTOR_BACKEND=mock
fi

./demo/run_vision_daemon.sh --stop 2>/dev/null || true
./demo/run_vision_daemon.sh "$HUB_URL"
echo "[enable_pilot_cv] mode=$MODE backend=$BACKEND — tail logs under demo/data/stores/*/live/vision_worker.log"
