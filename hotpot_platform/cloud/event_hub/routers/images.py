"""Image upload/serve router for hotpot Hub (VLM-604)."""

from __future__ import annotations

import base64
import imghdr
import time
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator

from hotpot_platform.cloud.event_hub.auth import AuthContext, get_auth_context
from common.schemas import utc_now_iso

MAX_IMAGE_BYTES = 10 * 1024 * 1024  # 10 MB

STATIC_DIR = Path(__file__).resolve().parents[1] / "static" / "images"
STATIC_DIR.mkdir(parents=True, exist_ok=True)

router = APIRouter()


class ImageUploadBody(BaseModel):
    store_id: str
    zone: str
    camera_id: Optional[str] = "cam01"
    ts: Optional[str] = None
    image_base64: str

    @field_validator("image_base64")
    @classmethod
    def check_size(cls, v: str) -> str:
        raw_size = len(v)
        decoded_size = (raw_size * 3) // 4
        if decoded_size > MAX_IMAGE_BYTES:
            raise ValueError(f"图片过大 ({decoded_size / 1024 / 1024:.1f} MB)，上限 {MAX_IMAGE_BYTES / 1024 / 1024:.0f} MB")
        return v


def _detect_image_type(raw: bytes) -> Optional[str]:
    """Detect JPEG/PNG by magic bytes (reliable than imghdr)."""
    if raw[:4] == b"\x89PNG":
        return "png"
    if raw[:2] in (b"\xff\xd8",):
        return "jpeg"
    return None


@router.post("/v1/images")
def upload_image(body: ImageUploadBody, auth: AuthContext = Depends(get_auth_context)):
    ts = body.ts or utc_now_iso()
    safe_ts = ts.replace(":", "-").replace(" ", "T")[:19]
    store_dir = STATIC_DIR / body.store_id / body.zone
    store_dir.mkdir(parents=True, exist_ok=True)

    # Strip data URI prefix if present
    b64 = body.image_base64
    if "," in b64 and b64.startswith("data:"):
        b64 = b64.split(",", 1)[1]

    try:
        raw = base64.b64decode(b64)
    except Exception:
        raise HTTPException(status_code=400, detail="无效的 base64 编码")

    # Validate image type by magic bytes
    fmt = _detect_image_type(raw)
    if fmt not in ("jpeg", "png"):
        raise HTTPException(status_code=400, detail=f"不支持的图片格式（magic={raw[:4].hex()}），仅接受 jpeg/png")

    timestamp = int(time.time())
    fname = f"{safe_ts}_{body.camera_id}.{fmt}"
    fpath = store_dir / fname
    fpath.write_bytes(raw)

    url = f"/static/images/{body.store_id}/{body.zone}/{fname}"
    return {
        "ok": True,
        "url": url,
        "path": str(fpath),
        "size_bytes": len(raw),
    }


@router.get("/v1/images")
def list_images(
    store_id: str = "",
    zone: str = "",
    auth: AuthContext = Depends(get_auth_context),
):
    """列出已存储的图片。可按 store_id/zone 过滤。"""
    images = []
    if not STATIC_DIR.exists():
        return {"images": []}

    for store_dir in sorted(STATIC_DIR.iterdir()):
        if not store_dir.is_dir():
            continue
        if store_id and store_dir.name != store_id:
            continue
        for zone_dir in sorted(store_dir.iterdir()):
            if not zone_dir.is_dir():
                continue
            if zone and zone_dir.name != zone:
                continue
            for img_file in sorted(zone_dir.iterdir(), reverse=True):
                if img_file.suffix.lower() in (".jpg", ".jpeg", ".png"):
                    url = f"/static/images/{store_dir.name}/{zone_dir.name}/{img_file.name}"
                    images.append({
                        "store_id": store_dir.name,
                        "zone": zone_dir.name,
                        "filename": img_file.name,
                        "url": url,
                        "size_bytes": img_file.stat().st_size,
                    })

    # 限制返回数量
    return {"images": images[:100]}
