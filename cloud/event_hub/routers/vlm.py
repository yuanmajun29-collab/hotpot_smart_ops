"""VLM routes — waste estimate (VLM-603 · LOSS-431 / §2.3).

Edge path: ``items`` present → use directly (Jetson already inferred).
Hub path:  no items → deterministic mock.
"""

from __future__ import annotations

import base64
import os
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, model_validator

from cloud.event_hub import runtime
from cloud.event_hub.auth import AuthContext, get_auth_context, enforce_store_write
from cloud.event_hub.domain.waste_estimate import compute_waste_estimate
from cloud.event_hub.hub_core import DEFAULT_STORE_ID
from cloud.cost_control.feature_builder import build_loss_features, persist_loss_features
from shared.schemas import utc_now_iso

router = APIRouter()

# ── Hub 自身的基础 URL，返回绝对路径图片 URL（Dashboard :3000 需要完整 URL） ──
_HUB_BASE_URL = os.environ.get("HOTPOT_HUB_BASE_URL", "http://127.0.0.1:8098").rstrip("/")

# ── 图片存储目录 ──
_IMAGES_DIR = Path(__file__).resolve().parent.parent / "static" / "images"
_IMAGES_DIR.mkdir(parents=True, exist_ok=True)


class WasteEstimateBody(BaseModel):
    store_id: Optional[str] = None
    image_ref: Optional[str] = None
    stream_id: Optional[str] = None
    zone: Optional[str] = None
    ts: Optional[str] = None
    # ── edge inference fields ──
    items: Optional[List[Dict[str, Any]]] = None
    source: str = "mock"
    model: str = "mock-rule"
    # ── 边缘图片（base64 编码） ──
    image_base64: Optional[str] = None
    image_data: Optional[str] = None   # base64 编码图片（新字段）
    image_mime: Optional[str] = None   # image/jpeg, image/png

    @model_validator(mode="after")
    def require_input_source(self) -> "WasteEstimateBody":
        # 允许三种输入源：image_ref / stream_id / items（边缘已推理）
        if not self.image_ref and not self.stream_id and not self.items:
            raise ValueError("至少需要 image_ref、stream_id 或 items 之一")
        return self


def _save_base64_image(b64: str, store_id: str = "default", zone: str = "unknown") -> str:
    """将 base64 字符串解码存盘，返回 Hub 绝对 URL 路径。

    图片存入 static/images/{store_id}/{zone}/ 目录，
    返回 `${_HUB_BASE_URL}/static/images/...` 以使 Dashboard 等前端可直接拉取。
    """
    ts = utc_now_iso().replace(":", "-").replace(" ", "T")[:19]
    img_id = uuid.uuid4().hex[:8]
    zone_dir = _IMAGES_DIR / store_id / zone
    zone_dir.mkdir(parents=True, exist_ok=True)
    img_path = zone_dir / f"{ts}_{img_id}.jpg"
    raw = base64.b64decode(b64)
    img_path.write_bytes(raw)
    return f"{_HUB_BASE_URL}/static/images/{store_id}/{zone}/{ts}_{img_id}.jpg"


@router.post("/v1/vlm/waste-estimate")
def vlm_waste_estimate(
    body: WasteEstimateBody,
    auth: AuthContext = Depends(get_auth_context),
) -> Dict[str, Any]:
    """废料识别。

    items 非空（Jetson 桥接）→ 走真实 VLM 路径（source 由调用方标注）；
    否则走 mock。始终写入事件并刷新 loss_features snapshot。
    """
    sid = body.store_id or auth.store_id or DEFAULT_STORE_ID
    enforce_store_write(auth, sid)

    # ── 图片存盘（旧字段 image_base64，向后兼容） ──
    image_url: Optional[str] = None
    if body.image_base64:
        try:
            image_url = _save_base64_image(body.image_base64, sid, body.zone or "unknown")
        except Exception:
            pass  # 图片解码失败不影响主流程

    result = compute_waste_estimate(
        store_id=sid,
        image_ref=body.image_ref,
        stream_id=body.stream_id,
        zone=body.zone,
        ts=body.ts,
        items=body.items,
        source=body.source,
        model=body.model,
        image_url=image_url,
    )
    store = runtime.hub.get_store(sid)
    event = store.add_event(
        {
            "event_type": "vlm_waste_estimate",
            "source": result["source"],
            "level": "info",
            "message": (
                f"VLM 废料识别 {len(result['items'])} 项"
                f" · {result['source']}"
            ),
            "metadata": {
                **result,
                "ref_type": "waste_estimate",
                "ref_id": body.image_ref or body.stream_id or "edge-inferred",
            },
        }
    )

    # ── 新图片字段（image_data + image_mime）：存入 Gallery 可扫描的目录 ──
    if body.image_data:
        try:
            ext = body.image_mime.split("/")[-1] if body.image_mime else "jpg"
            zone = body.zone or "unknown"
            zone_dir = _IMAGES_DIR / sid / zone
            zone_dir.mkdir(parents=True, exist_ok=True)
            event_id = event.get("event_id", "unknown")
            fname = f"{event_id}.{ext}"
            img_path = zone_dir / fname
            img_path.write_bytes(base64.b64decode(body.image_data))
            image_url = f"{_HUB_BASE_URL}/static/images/{sid}/{zone}/{fname}"
            result["image_url"] = image_url
        except Exception:
            pass  # 图片解码失败不影响主流程

    cost = store.cost_stats or {"store_id": sid, "items": []}
    features = build_loss_features(cost, store_id=sid)
    features["waste_evidence"] = result["items"]
    features["waste_source"] = result["source"]
    persist_loss_features(store, features)

    return {
        "ok": True,
        "event_id": event.get("event_id"),
        "generated_at": utc_now_iso(),
        **result,
    }


@router.get("/v1/vlm/images/{event_id}")
def get_waste_image(event_id: str):
    """返回废料识别对应的原始图片。先查新目录（static/images/{store}/{zone}/），再查旧目录（demo/data/images/）。"""
    # 新路径：递归搜索 static/images/
    for ext in ("jpg", "jpeg", "png"):
        fname = f"{event_id}.{ext}"
        for fp in _IMAGES_DIR.rglob(fname):
            return FileResponse(str(fp), media_type=f"image/{ext}")
    # 旧路径兼容：demo/data/images/
    _OLD_DIR = Path(__file__).resolve().parents[3] / "demo" / "data" / "images"
    for ext in ("jpg", "jpeg", "png"):
        fp = _OLD_DIR / f"{event_id}.{ext}"
        if fp.exists():
            return FileResponse(str(fp), media_type=f"image/{ext}")
    raise HTTPException(status_code=404, detail="图片不存在")
