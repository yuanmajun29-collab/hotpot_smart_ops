#!/usr/bin/env python3
"""一键上传本地图片到 Hub 图床，Dashboard 立即可看。

用法:
    python3 upload_to_hub.py <图片路径> [--store store_yuhuan] [--zone 备餐废弃区]
    python3 upload_to_hub.py test.jpg
    python3 upload_to_hub.py test.jpg --store store_jiaojiang --zone 前厅
"""

import argparse, base64, json, os, sys, time
from urllib.request import Request, urlopen
from urllib.error import HTTPError

HUB = os.environ.get("HOTPOT_HUB_URL", "http://127.0.0.1:8098")

def upload(image_path: str, store_id="store_yuhuan", zone="备餐废弃区", camera_id="local"):
    """上传图片到 Hub，返回图片 URL"""
    if not os.path.exists(image_path):
        print(f"❌ 文件不存在: {image_path}")
        sys.exit(1)

    with open(image_path, "rb") as f:
        raw = f.read()

    b64 = base64.b64encode(raw).decode()
    size_mb = len(raw) / 1024 / 1024

    payload = json.dumps({
        "store_id": store_id,
        "zone": zone,
        "camera_id": camera_id,
        "image_base64": b64,
    })

    req = Request(
        f"{HUB}/v1/images",
        data=payload.encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        resp = urlopen(req, timeout=30)
        data = json.loads(resp.read())
        url = data["url"]
        print(f"✅ 上传成功  {size_mb:.1f}MB")
        print(f"   URL:  {HUB}{url}")
        print(f"   路径: {data['path']}")
        return f"{HUB}{url}"
    except HTTPError as e:
        body = e.read().decode() if e.fp else ""
        print(f"❌ 上传失败 HTTP {e.code}: {body}")
        sys.exit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="上传图片到 Hotpot Hub 图床")
    parser.add_argument("image", help="图片文件路径")
    parser.add_argument("--store", default="store_yuhuan", help="门店ID")
    parser.add_argument("--zone", default="备餐废弃区", help="区域")
    parser.add_argument("--camera", default="local", help="摄像头ID")
    args = parser.parse_args()
    upload(args.image, args.store, args.zone, args.camera)
