#!/usr/bin/env python3
"""将 test_images/ 图片上传到 Hub 图床，并推送到 VLM 全链路。"""

import base64
import json
import os
import sys
from pathlib import Path
from urllib import request, error

HUB = os.environ.get("HUB_URL", "http://127.0.0.1:8098")
API_KEY = os.environ.get("HOTPOT_API_KEY", "edge_yuhuan_dev_key")
IMAGES_DIR = Path(__file__).resolve().parent.parent / "test_images"

SCENES = {
    "01_waste_meat": "毛肚边角料 · 备餐区",
    "02_waste_veg": "蔬菜大量浪费 · 洗菜区",
    "03_over_production": "过量备菜未消耗 · 出菜口",
    "04_expired": "鸭肠过期变质 · 冷库出库",
    "05_overflow": "火锅溢锅 · 后厨灶台",
    "06_unserved_return": "未食用回收 · 回收区",
}


def upload_image(fpath: Path) -> dict:
    with open(fpath, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()

    body = json.dumps({
        "store_id": "store_yuhuan",
        "zone": "kitchen",
        "camera_id": "cam01",
        "image_base64": b64,
    }).encode()
    req = request.Request(
        f"{HUB}/v1/images",
        data=body,
        headers={"Content-Type": "application/json", "X-Api-Key": API_KEY},
    )
    with request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def push_waste_estimate(image_ref: str) -> dict:
    """推送 VLM 废料估算（mock 模式，VLM 特征由 Hub 规则引擎生成）。"""
    body = {
        "store_id": "store_yuhuan",
        "zone": "kitchen",
        "image_ref": image_ref,
        "stream_id": "cam01",
        "source": "mock",
        "model": "mock-rule",
    }
    data = json.dumps(body).encode()
    req = request.Request(
        f"{HUB}/v1/vlm/waste-estimate",
        data=data,
        headers={"Content-Type": "application/json", "X-Api-Key": API_KEY},
    )
    with request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def main():
    print(f"🔗 Hub: {HUB}")

    # 健康检查
    try:
        req = request.Request(f"{HUB}/health")
        with request.urlopen(req, timeout=5) as resp:
            health = json.loads(resp.read())
            print(f"🟢 Hub 在线: {health.get('status', '?')}")
    except error.URLError:
        print("🔴 Hub 离线 — 请先启动: bash scripts/start_all.sh")
        sys.exit(1)

    print()
    results = []
    for fname in sorted(IMAGES_DIR.glob("scene_*.jpg")):
        key = fname.stem.replace("scene_", "")
        desc = SCENES.get(key, "未知")

        print(f"📤 {fname.name} — {desc}")
        try:
            result = upload_image(fname)
            url = result.get("url", "")
            print(f"   ✅ 图床: {url}")

            vlm = push_waste_estimate(url)
            event_id = vlm.get("event_id", "?")
            items = vlm.get("items", [])
            print(f"   🧠 VLM: event_id={event_id}  items={len(items)}")
            if items:
                for item in items[:3]:
                    print(f"      · {item.get('sku','?')} {item.get('waste_type','?')} conf={item.get('confidence',0)}")
            results.append({"file": fname.name, "event_id": event_id, "items": len(items)})
        except error.HTTPError as e:
            body = e.read().decode()[:200]
            print(f"   ❌ HTTP {e.code}: {body}")
        except error.URLError as e:
            print(f"   ❌ 连接失败: {e.reason}")
            sys.exit(1)

    print(f"\n{'='*50}")
    print(f"✅ 完成 {len(results)} 张图片上传+VLM推理")
    print(f"📊 Dashboard: http://127.0.0.1:3099/vlm-demo.html")
    for r in results:
        print(f"   event_id={r['event_id']}  ← {r['file']}")


if __name__ == "__main__":
    main()
