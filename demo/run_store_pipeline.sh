#!/usr/bin/env bash
# Run live PoC pipeline for a single store tenant.
# Usage: run_store_pipeline.sh <store_id> <store_name> <inject_anomaly:0|1> <hub_url>

set -euo pipefail

STORE_ID="${1:?store_id required}"
STORE_NAME="${2:?store_name required}"
INJECT_ANOMALY="${3:-0}"
HUB_URL="${4:?hub_url required}"

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

LIVE_DIR="demo/data/stores/${STORE_ID}/live"
mkdir -p "$LIVE_DIR"

# Per-store SOP signals (avoid cross-store merge overwrite)
SOP_SIGNALS="demo/data/stores/${STORE_ID}/sop_signals_noon.json"
cp demo/data/sop_signals_noon.json "$SOP_SIGNALS"

echo ""
echo "----------------------------------------------"
echo " Live pipeline · ${STORE_NAME} (${STORE_ID})"
echo "----------------------------------------------"

echo "  [vision] UAT ROI + file mode (DEV-203 mock)..."
VISION_ARGS=(
  --store-id "$STORE_ID"
  --hub-url "$HUB_URL"
  --backend mock
  --output-dir "$LIVE_DIR"
)
if [[ -n "${VISION_INTERVAL:-}" && "${VISION_INTERVAL}" != "0" ]]; then
  VISION_ARGS+=(--interval "$VISION_INTERVAL")
  if [[ -n "${VISION_CYCLES:-}" ]]; then
    VISION_ARGS+=(--cycles "$VISION_CYCLES")
  fi
  echo "  [vision] periodic mode interval=${VISION_INTERVAL}s"
fi
python3 edge/stream/vision_worker.py "${VISION_ARGS[@]}"

echo "  [iot] environment sensors..."
IOT_ARGS=(--store-id "$STORE_ID" --hub-url "$HUB_URL" --cycles 1)
if [[ "$INJECT_ANOMALY" == "1" ]]; then
  IOT_ARGS+=(--inject-anomaly)
fi
python3 edge/iot_mock/sensor_simulator.py "${IOT_ARGS[@]}"

echo "  [iot] ingredient lifecycle..."
python3 edge/iot_mock/ingredient_iot_bridge.py \
  --input demo/data/ingredient_lifecycle_iot.json \
  --store-id "$STORE_ID" \
  --hub-url "$HUB_URL" \
  --merge-sop-signals "$SOP_SIGNALS" \
  > "${LIVE_DIR}/iot_lifecycle_result.json" 2>/dev/null

echo "  [sop] compliance evaluation..."
python3 cloud/sop/sop_engine.py \
  --store-id "$STORE_ID" \
  --shift noon \
  --signals-file "$SOP_SIGNALS" \
  --hub-url "$HUB_URL" > "${LIVE_DIR}/sop_result.json" 2>/dev/null

# 椒江店 SOP 结果略优于玉环（模拟运营更规范）
if [[ "$STORE_ID" == "store_jiaojiang" ]]; then
  python3 - <<PY
import json
from pathlib import Path

path = Path("${LIVE_DIR}/sop_result.json")
data = json.loads(path.read_text(encoding="utf-8"))
data["passed"] = max(data.get("passed", 0), 4)
data["failed"] = min(data.get("failed", 99), 1)
data["compliance_rate"] = round(data["passed"] / max(data.get("total", 1), 1) * 100, 1)
for r in data.get("results", []):
    if r.get("sop_id") == "sop_opening" and r.get("status") == "failed":
        r["status"] = "passed"
        r["reason"] = "开档检查全部达标"
        for cp in r.get("checkpoints", []):
            if cp.get("id") == "kitchen_gear_ok":
                cp["passed"] = True
                cp["actual"] = True
path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

import urllib.request
req = urllib.request.Request(
    "${HUB_URL}/sop?store_id=${STORE_ID}",
    data=json.dumps(data).encode(),
    headers={"Content-Type": "application/json"},
    method="POST",
)
urllib.request.urlopen(req)
print("[OK] Refined SOP stats for store_jiaojiang")
PY
fi

echo "  [cost] incoming material analysis..."
python3 cloud/cost_control/analyzer.py \
  --input demo/data/incoming_materials.json \
  --iot-enrichments "${LIVE_DIR}/iot_lifecycle_result.json" \
  --store-id "$STORE_ID" \
  --hub-url "$HUB_URL" > "${LIVE_DIR}/cost_result.json" 2>/dev/null

echo "  [report] daily operations report..."
python3 cloud/llm_report/report_agent.py \
  --hub-url "$HUB_URL" \
  --store-id "$STORE_ID" \
  --store-name "$STORE_NAME" \
  --backend rule \
  --output "${LIVE_DIR}/daily_report.md"

echo "[DONE] ${STORE_NAME} live pipeline complete -> ${LIVE_DIR}/"
