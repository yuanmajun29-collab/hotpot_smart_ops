#!/usr/bin/env bash
# Hotpot Smart Ops PoC - one-click demo (multi-tenant live pipeline)
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

HUB_PORT="${HUB_PORT:-8088}"
DASH_PORT="${DASH_PORT:-3000}"
STORE_ID="${STORE_ID:-store_yuhuan}"
case "$STORE_ID" in
  store_jiaojiang) STORE_NAME="${STORE_NAME:-冯校长火锅·椒江店}" ;;
  *)               STORE_NAME="${STORE_NAME:-冯校长火锅·玉环店}" ;;
esac
HUB_URL="http://127.0.0.1:${HUB_PORT}"
VISION_INTERVAL="${VISION_INTERVAL:-5}"
VISION_DAEMON="${VISION_DAEMON:-1}"

# Comma-separated override, e.g. STORES=store_yuhuan,store_jiaojiang
if [[ -n "${STORES:-}" ]]; then
  IFS=',' read -ra PILOT_STORES <<< "$STORES"
else
  PILOT_STORES=(store_yuhuan store_jiaojiang)
fi

declare -A STORE_NAMES=(
  [store_yuhuan]="冯校长火锅·玉环店"
  [store_jiaojiang]="冯校长火锅·椒江店"
)
declare -A STORE_ANOMALY=(
  [store_yuhuan]=1
  [store_jiaojiang]=0
)

echo "=============================================="
echo " 冯校长火锅 · 智能运营 PoC 演示"
echo " ROOT: $ROOT"
echo " 实时流水线: ${PILOT_STORES[*]}"
echo "=============================================="

# Install deps if needed
if ! python3 -c "import cv2, fastapi, jwt" 2>/dev/null; then
  echo "[1/11] Installing Python dependencies..."
  pip install -q -r requirements.txt
else
  echo "[1/11] Dependencies OK"
fi

# Generate demo images
echo "[2/11] Generating demo images..."
python3 demo/generate_demo_images.py --out-dir demo/data

# Start event hub (multi-tenant, auto-seed both pilot stores)
echo "[3/11] Starting event hub on port ${HUB_PORT}..."
if python3 -c "import urllib.request; urllib.request.urlopen('${HUB_URL}/health', timeout=1)" 2>/dev/null; then
  echo "[INFO] Event hub already running on ${HUB_URL}, refreshing seeds..."
  python3 demo/seed_hub.py --hub-url "$HUB_URL" --all --build
  HUB_PID=""
else
  python3 cloud/event_hub/server.py --port "$HUB_PORT" --seed-dir demo/data/stores &
  HUB_PID=$!
  sleep 1
fi

cleanup() {
  echo ""
  echo "Stopping services..."
  if [[ "${VISION_DAEMON:-1}" == "1" ]]; then
    bash demo/run_vision_daemon.sh --stop 2>/dev/null || true
  fi
  [[ -n "${HUB_PID:-}" ]] && kill "$HUB_PID" 2>/dev/null || true
  [[ -n "${DASH_PID:-}" ]] && kill "$DASH_PID" 2>/dev/null || true
}
trap cleanup EXIT

if [[ -z "${HUB_PID:-}" ]]; then
  echo "[4/11] Multi-tenant seeds already loaded or refreshed"
else
  echo "[4/11] Multi-tenant seeds loaded (玉环 + 椒江)"
fi

chmod +x demo/run_store_pipeline.sh demo/run_vision_daemon.sh

echo "[5-9/11] Running live pipeline for all pilot stores..."
for sid in "${PILOT_STORES[@]}"; do
  sname="${STORE_NAMES[$sid]:-$sid}"
  anomaly="${STORE_ANOMALY[$sid]:-0}"
  bash demo/run_store_pipeline.sh "$sid" "$sname" "$anomaly" "$HUB_URL"
done

# Symlink default demo outputs to primary store for backward compatibility
PRIMARY_LIVE="demo/data/stores/${STORE_ID}/live"
mkdir -p demo/data
for f in front_result.json kitchen_result.json iot_lifecycle_result.json sop_result.json cost_result.json daily_report.md; do
  if [[ -f "${PRIMARY_LIVE}/${f}" ]]; then
    cp "${PRIMARY_LIVE}/${f}" "demo/data/${f}"
  fi
done

echo "[10/11] Starting dashboard..."
python3 dashboard/serve.py --port "$DASH_PORT" &
DASH_PID=$!
sleep 0.5

if [[ "$VISION_DAEMON" == "1" ]]; then
  echo "[11/11] Starting vision workers (interval=${VISION_INTERVAL}s)..."
  export STORES="$(IFS=,; echo "${PILOT_STORES[*]}")"
  bash demo/run_vision_daemon.sh "$HUB_URL" "$VISION_INTERVAL"
else
  echo "[11/11] Vision daemon disabled (VISION_DAEMON=0)"
fi

echo ""
echo "=============================================="
echo " PoC 演示已就绪（两店实时流水线 + 周期视觉扫描）"
echo "----------------------------------------------"
echo " 默认看板门店:  ${STORE_NAME} (${STORE_ID})"
echo " 多租户 API:    ${HUB_URL}/stores"
for sid in "${PILOT_STORES[@]}"; do
  echo "  ${STORE_NAMES[$sid]:-$sid}: ${HUB_URL}/summary?store_id=${sid}"
done
if [[ "$VISION_DAEMON" == "1" ]]; then
  echo " 视觉 worker:   每 ${VISION_INTERVAL}s 扫描 · demo/data/stores/<id>/live/vision_worker.log"
fi
echo " MVP 看板:      http://127.0.0.1:${DASH_PORT}/login.html"
echo " 手机 H5:       http://127.0.0.1:${DASH_PORT}/mobile/index.html"
echo " 旧版 PoC:      http://127.0.0.1:${DASH_PORT}/poc.html"
echo " 各店 live 输出: demo/data/stores/<store_id>/live/"
echo " 解决方案文档:  docs/solution.md"
echo "=============================================="
echo ""
echo "按 Ctrl+C 停止服务"
echo ""

echo "--- 运营日报预览 (${STORE_NAME}) ---"
head -30 "demo/data/stores/${STORE_ID}/live/daily_report.md" 2>/dev/null || head -30 demo/data/daily_report.md
echo "..."
echo ""

if [[ -n "${HUB_PID:-}" ]]; then
  wait "$HUB_PID"
else
  wait "$DASH_PID"
fi
