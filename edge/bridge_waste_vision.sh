#!/bin/bash
# bridge_waste_vision.sh — Jetson VLM → hotpot Hub bridge
#
# 用法:
#   ./bridge_waste_vision.sh /path/to/image.jpg [store_id] [zone] [hub_url]
#
# 流程: 取图 → base64上传图床 → VLM推理(结构化JSON) → 附image_url → POST Hub

set -euo pipefail

IMAGE="${1:?用法: $0 <image_path> [store_id] [zone] [hub_url]}"
STORE_ID="${2:-store_yuhuan}"
ZONE="${3:-备餐废弃区}"
HUB_URL="${4:-http://127.0.0.1:8098}"

# ── 1. 图片 base64 编码 → 上传 Hub 图床 ──
echo "[bridge] 图片编码+上传图床... image=$IMAGE" >&2
CAMERA_ID=$(basename "$IMAGE" | sed 's/\.[^.]*$//')

# 构造 JSON 写入临时文件（避免 base64 溢出 shell ARG_MAX）
UPLOAD_TMP=$(mktemp /tmp/bridge_upload_XXXXXX.json)
BRIDGE_IMAGE="$IMAGE" BRIDGE_STORE="$STORE_ID" BRIDGE_ZONE="$ZONE" \
  BRIDGE_CAMERA="$CAMERA_ID" BRIDGE_TMP="$UPLOAD_TMP" \
  python3 -c '
import json, base64, os
with open(os.environ["BRIDGE_IMAGE"], "rb") as f:
    b64 = base64.b64encode(f.read()).decode("ascii")
payload = {
    "store_id": os.environ["BRIDGE_STORE"],
    "zone": os.environ["BRIDGE_ZONE"],
    "camera_id": os.environ["BRIDGE_CAMERA"],
    "image_base64": b64
}
with open(os.environ["BRIDGE_TMP"], "w") as f:
    json.dump(payload, f)
'

UPLOAD_RESP=$(curl -s -X POST "$HUB_URL/v1/images" \
  -H "Content-Type: application/json" \
  -H "X-Api-Key: edge_yuhuan_dev_key" \
  -d "@$UPLOAD_TMP")

IMAGE_URL=$(echo "$UPLOAD_RESP" | python3 -c "import sys,json; print(json.load(sys.stdin).get('url',''))" 2>/dev/null || echo "")
echo "[bridge] 图床上传: url=$IMAGE_URL" >&2

# ── 2. VLM 推理 ──
echo "[bridge] 推理中... image=$IMAGE zone=$ZONE" >&2
PROMPT='分析图片中食材浪费情况。只输出一行JSON，不要任何解释：
{"items":[{"waste_type":"食材名+损耗类型(边角料/餐后剩余/过期/品质差)","sku":"食材标准名","estimated_portion":0.5,"unit":"份","confidence":0.7,"reason":"简要判断依据"}]}

规则：waste_type=识别食材+损耗类型；sku=食材标准名(毛肚/鸭肠/牛肉片/生菜/黄喉)；estimated_portion=0~1(0.2=少量,0.5=半份,1.0=整份)；confidence=0~1；reason=一句话(颜色/数量/摆放)。无浪费时items为空数组[]'

RESULT=$(bash /root/run_ostrakon_vl.sh "$IMAGE" "$PROMPT" 2>/dev/null)

# ── 提取 JSON ──
JSON=$(echo "$RESULT" | grep -o '{"items":\[.*\]}' | head -1) || true
if [ -z "$JSON" ]; then
  JSON=$(echo "$RESULT" | grep -o '{.*}' | head -1) || true
fi

if [ -z "$JSON" ]; then
  echo "[bridge] ERROR: VLM 未输出有效 JSON" >&2
  echo "[bridge] RAW: $RESULT" >&2
  exit 1
fi

echo "[bridge] VLM JSON: $JSON" >&2

# ── 3. POST waste-estimate（附 image_url）──
TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
ITEMS=$(echo "$JSON" | python3 -c "import sys,json; d=json.load(sys.stdin); print(json.dumps(d.get('items',d)))" 2>/dev/null || echo "$JSON")

# 用 image_url 作为 image_ref（Hub 可直接访问）
IMAGE_REF="$IMAGE_URL"
if [ -z "$IMAGE_REF" ]; then
  IMAGE_REF="$IMAGE"
fi

PAYLOAD=$(cat <<EOF
{
  "store_id": "$STORE_ID",
  "image_ref": "$IMAGE_REF",
  "zone": "$ZONE",
  "ts": "$TIMESTAMP",
  "items": $ITEMS,
  "source": "vlm-shadow",
  "model": "ostrakon-vl-8b-iq4xs"
}
EOF
)

echo "[bridge] POST → $HUB_URL/v1/vlm/waste-estimate" >&2
RESPONSE=$(curl -s -X POST "$HUB_URL/v1/vlm/waste-estimate" \
  -H "Content-Type: application/json" \
  -H "X-Api-Key: edge_yuhuan_dev_key" \
  -d "$PAYLOAD")

echo "[bridge] Hub 响应: $RESPONSE" >&2
echo "$RESPONSE"
