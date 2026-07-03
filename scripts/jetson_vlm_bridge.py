#!/usr/bin/env python3
"""Jetson VLM bridge — Ostrakon-VL inference → POST Hub /v1/vlm/waste-estimate.

Usage:
    python3 jetson_vlm_bridge.py <image_path> [zone]
    python3 jetson_vlm_bridge.py /tmp/waste-snapshot.jpg "备餐废弃区"

Env:
    HOTPOT_HUB_URL   Hub base URL (default: http://192.168.2.100:8088)
    HOTPOT_API_KEY   API key for X-Api-Key header
    HOTPOT_STORE_ID  Store identifier (default: store_yuhuan)
    VLM_SCRIPT       Path to run_ostrakon_vl.sh (default: /root/run_ostrakon_vl.sh)

Interface contract (aligned with Hub WasteEstimateBody):
    POST /v1/vlm/waste-estimate
    {"store_id","items":[{"sku","waste_type","estimated_portion","unit",
     "confidence","reason","suggested_action"}],"source","model","zone","ts"}
"""

import base64
import json
import os
import re
import subprocess
import sys
import urllib.request
from datetime import datetime, timezone

# ── config ──────────────────────────────────────────────────────────────────
HUB_URL = os.environ.get("HOTPOT_HUB_URL", "http://127.0.0.1:8098").rstrip("/")
API_KEY = os.environ.get("HOTPOT_API_KEY", "edge_yuhuan_dev_key")
STORE_ID = os.environ.get("HOTPOT_STORE_ID", "store_yuhuan")
VLM_SCRIPT = os.environ.get("VLM_SCRIPT", "/root/run_ostrakon_vl.sh")
TIMEOUT_VLM = int(os.environ.get("VLM_TIMEOUT", "60"))
TIMEOUT_POST = int(os.environ.get("POST_TIMEOUT", "15"))

# ── VLM prompt — 纯 JSON 输出 (已验证可行) ────────────────────────────────
VLM_PROMPT = (
    "你是后厨废料识别系统。分析图片，输出纯 JSON 对象，不要 ```json 包裹，不要任何解释文字：\n"
    '{"items":[{"sku":"食材名","waste_type":"备餐废弃|边角料|过期临界|餐后剩余",'
    '"estimated_portion":0.5,"unit":"份","confidence":0.82,'
    '"reason":"判断依据","suggested_action":"建议操作"}]}\n'
    "严格只输出 JSON，从 { 开始，到 } 结束。"
)


# ── VLM inference ────────────────────────────────────────────────────────────

def run_vlm(image_path: str) -> str:
    """Run Ostrakon-VL on image, return stdout text."""
    cmd = [
        "bash", VLM_SCRIPT,
        image_path,
    ]
    env = os.environ.copy()
    env["VLM_PROMPT"] = VLM_PROMPT

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=TIMEOUT_VLM,
            env=env,
        )
        output = result.stdout.strip()
        if result.returncode != 0:
            raise RuntimeError(f"VLM exit {result.returncode}: {result.stderr.strip()}")
        if not output:
            raise RuntimeError("VLM produced empty output")
        return output
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"VLM timeout after {TIMEOUT_VLM}s")


# ── JSON parsing (robust: direct + regex fallback) ───────────────────────────

def extract_json(text: str) -> list[dict]:
    """Parse VLM output into items list. VLM 已验证稳定纯 JSON 输出，两层兜底。"""
    cleaned = text.strip()

    # Try 1: direct parse (VLM confirmed pure JSON)
    try:
        data = json.loads(cleaned)
        return _normalize_items(data)
    except json.JSONDecodeError:
        pass

    # Try 2: regex extract first {...} block (extreme edge fallback)
    m = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if m:
        try:
            data = json.loads(m.group(0))
            return _normalize_items(data)
        except json.JSONDecodeError:
            pass

    raise ValueError(f"Cannot parse VLM output as JSON: {text[:200]}")


def _normalize_items(data: dict) -> list[dict]:
    """Extract and normalize items from parsed JSON."""
    raw_items = data.get("items", [])
    if not isinstance(raw_items, list):
        raw_items = [data] if isinstance(data, dict) else []

    items = []
    for i in raw_items:
        if not isinstance(i, dict):
            continue
        items.append({
            "sku": str(i.get("sku", "未知")).strip(),
            "waste_type": str(i.get("waste_type", "未分类")).strip(),
            "estimated_portion": _safe_float(i.get("estimated_portion", 0)),
            "unit": str(i.get("unit", "份")).strip(),
            "confidence": _safe_float(i.get("confidence", 0.5)),
            "reason": str(i.get("reason", "")).strip(),
            "suggested_action": str(i.get("suggested_action", "人工复核")).strip(),
        })
    return items


def _safe_float(v) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


# ── POST to Hub ──────────────────────────────────────────────────────────────

def post_to_hub(items: list[dict], *, zone: str = "备餐废弃区",
                 image_ref: str = "", image_b64: str = "") -> dict:
    """POST waste estimate to Hub /v1/vlm/waste-estimate."""
    url = f"{HUB_URL}/v1/vlm/waste-estimate"
    payload = {
        "store_id": STORE_ID,
        "items": items,
        "source": "ostrakon-vl",
        "model": "ostrakon-vl-8b-iq4xs",
        "zone": zone,
        "ts": datetime.now(timezone.utc).isoformat(),
        "image_base64": image_b64,
    }
    if image_ref:
        payload["image_ref"] = image_ref

    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "Content-Type": "application/json",
            "X-Api-Key": API_KEY,
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_POST) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Hub {e.code}: {detail[:300]}")
    except urllib.error.URLError as e:
        raise RuntimeError(f"Hub unreachable: {e.reason}")


# ── main ─────────────────────────────────────────────────────────────────────

def main():
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <image_path> [zone]", file=sys.stderr)
        sys.exit(1)

    image_path = sys.argv[1]
    zone = sys.argv[2] if len(sys.argv) > 2 else "备餐废弃区"

    print(f"[bridge] VLM inference on {image_path} ...")
    raw_output = run_vlm(image_path)
    print(f"[bridge] VLM raw: {raw_output[:200]}...")

    items = extract_json(raw_output)
    if not items:
        print("[bridge] No items detected, skipping POST", file=sys.stderr)
        sys.exit(0)

    print(f"[bridge] Parsed {len(items)} item(s): {items[0].get('sku', '?')}")

    # 原图 base64 编码
    image_b64 = ""
    try:
        with open(image_path, "rb") as f:
            image_b64 = base64.b64encode(f.read()).decode("ascii")
    except Exception:
        pass  # 编码失败不影响主流程

    result = post_to_hub(items, zone=zone, image_ref=f"file://{image_path}", image_b64=image_b64)
    print(f"[bridge] Hub response: ok={result.get('ok')}, "
          f"event_id={result.get('event_id')}, "
          f"source={result.get('source')}")


if __name__ == "__main__":
    main()
