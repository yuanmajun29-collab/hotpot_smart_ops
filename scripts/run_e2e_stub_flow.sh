#!/usr/bin/env bash
# End-to-end stub business flow: seed Hub → tick all stores → verify pipeline.
# Usage: ./scripts/run_e2e_stub_flow.sh [hub_url]

set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

HUB_URL="${1:-http://127.0.0.1:8088}"
SEED_DIR="${HOTPOT_SEED_DIR:-demo/data/stores}"

echo "=============================================="
echo " E2E Stub Flow · Hotpot Smart Ops"
echo " Hub: $HUB_URL"
echo "=============================================="

echo ""
echo "[1/4] Health check..."
HEALTH_JSON="$(curl -fsS "$HUB_URL/health" 2>/tmp/hotpot_e2e_health.err || true)"
if ! python3 - "$HEALTH_JSON" <<'PY' >/tmp/hotpot_e2e_health_pretty 2>/dev/null
import json
import sys

json.loads(sys.argv[1])
PY
then
  echo "[FAIL] Hub health check did not return JSON from $HUB_URL/health" >&2
  if [ -s /tmp/hotpot_e2e_health.err ]; then
    sed 's/^/  curl: /' /tmp/hotpot_e2e_health.err >&2
  fi
  echo "Start Hub first, for example:" >&2
  echo "  python3 cloud/event_hub/server.py --host 127.0.0.1 --port 8088 --seed-dir demo/data/stores" >&2
  exit 1
fi
python3 -m json.tool <<<"$HEALTH_JSON" | head -5

echo ""
echo "[2/4] Login as 总部 PMO..."
TOKEN=$(curl -sf -X POST "$HUB_URL/auth/token" \
  -H "Content-Type: application/json" \
  -d '{"username":"zongbu","password":"demo","role":"总部PMO","store_id":"store_yuhuan"}' \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")
echo "  Token OK (${#TOKEN} chars)"

echo ""
echo "[3/4] Pipeline tick (inprocess stub) all stores..."
curl -sf -X POST "$HUB_URL/v1/admin/pipeline/tick" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"mode":"inprocess"}' \
  | python3 -m json.tool | head -30

echo ""
echo "[4/4] Verify national overview + pipeline status..."
curl -sf "$HUB_URL/v1/national/overview" -H "Authorization: Bearer $TOKEN" \
  | python3 -c "import sys,json; d=json.load(sys.stdin); print('  stores:', d.get('rollup',{}).get('store_count')); print('  level:', d.get('level'))"
curl -sf "$HUB_URL/v1/admin/pipeline/status" -H "Authorization: Bearer $TOKEN" \
  | python3 -c "import sys,json; d=json.load(sys.stdin); print('  avg_pipeline_pct:', d.get('summary',{}).get('avg_pipeline_pct'))"

echo ""
echo "[optional] Full subprocess pipeline per store (slower)..."
for sid in store_yuhuan store_jiaojiang; do
  name=$(python3 -c "import json; d=json.load(open('demo/data/stores.json')); print(next(s['store_name'] for s in d['pilot_stores'] if s['store_id']=='$sid'))")
  echo "  → $sid ($name)"
  bash demo/run_store_pipeline.sh "$sid" "$name" 0 "$HUB_URL" 2>/dev/null | tail -1 || true
done

echo ""
echo "[DONE] Open dashboard:"
echo "  python3 dashboard/serve.py --port 3000"
echo "  http://127.0.0.1:3000/admin/index.html  (zongbu / demo)"
echo "  http://127.0.0.1:3000/regional.html"
