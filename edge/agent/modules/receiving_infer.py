"""Receiving inference router for Edge Agent.

Combines electronic-scale readings and ingredient quality inspection behind:
  - POST /infer/receiving
  - GET /status/receiving
"""

from __future__ import annotations

import base64
import os
import time
from pathlib import Path
from typing import Any, Dict, Optional

import cv2
import numpy as np
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from edge.agent.config import PROJECT_ROOT, STORE_ID
from edge.receiving.ingredient_quality import IngredientQualityInspector
from edge.receiving.ingredient_scale import IngredientScaleDriver

router = APIRouter(prefix="/infer", tags=["receiving"])

_active = False
_scale_driver: Optional[IngredientScaleDriver] = None
_quality_inspector: Optional[IngredientQualityInspector] = None
_last_session: Dict[str, Any] = {
    "status": "idle",
    "last_result": None,
    "last_error": None,
}


class ReceivingInferRequest(BaseModel):
    """Receiving check request containing optional image and PO weight."""

    image_path: Optional[str] = None
    frame_base64: Optional[str] = None
    expected_weight_kg: Optional[float] = None
    batch_ref: Optional[str] = None
    sku: Optional[str] = None
    tare: bool = False
    push_to_hub: bool = True
    quality_threshold: Optional[int] = None


def _check_active() -> None:
    if not _active:
        raise HTTPException(503, "receiving 模块未激活（配置中无 receiving module）")


def _get_scale_driver() -> IngredientScaleDriver:
    """Lazy-load receiving scale driver."""
    global _scale_driver
    if _scale_driver is None:
        _scale_driver = IngredientScaleDriver()
    return _scale_driver


def _get_quality_inspector(threshold: Optional[int] = None) -> IngredientQualityInspector:
    """Lazy-load quality inspector, recreating when threshold changes."""
    global _quality_inspector
    if _quality_inspector is None or (threshold is not None and _quality_inspector.threshold != threshold):
        _quality_inspector = IngredientQualityInspector(threshold=threshold or int(os.environ.get("RECEIVING_QUALITY_THRESHOLD", "75")))
    return _quality_inspector


def _decode_base64_frame(b64: str) -> np.ndarray:
    """Decode base64 image frame to OpenCV BGR array."""
    if b64.startswith("data:image"):
        b64 = b64.split(",", 1)[1]
    raw = base64.b64decode(b64)
    arr = np.frombuffer(raw, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("无法解码 base64 图片")
    return img


def _load_frame(req: ReceivingInferRequest) -> Any:
    if req.frame_base64:
        return _decode_base64_frame(req.frame_base64), ""
    if req.image_path:
        p = Path(req.image_path)
        if not p.is_absolute():
            p = PROJECT_ROOT / p
        if not p.exists():
            raise HTTPException(404, f"图片不存在: {req.image_path}")
        frame = cv2.imread(str(p))
        if frame is None:
            raise HTTPException(400, f"无法读取图片: {req.image_path}")
        return frame, str(p)
    return None, ""


@router.post("/receiving")
async def receiving_infer(req: ReceivingInferRequest) -> Dict[str, Any]:
    """Run one receiving check: scale weight + optional quality inspection."""
    _check_active()
    _last_session.update({"status": "running", "last_error": None})
    t0 = time.perf_counter()

    try:
        scale = _get_scale_driver()
        if req.tare:
            current = await scale.read_weight()
            scale.tare(current.gross_weight_kg)

        weight_result = await scale.read_and_compare(req.expected_weight_kg)
        reading = weight_result["reading"]
        comparison = weight_result["comparison"]

        frame, image_ref = _load_frame(req)
        quality_result = None
        if frame is not None:
            inspector = _get_quality_inspector(req.quality_threshold)
            quality_result = inspector.inspect(frame, image_ref=image_ref).to_dict()

        hub_result = {"ok": False, "skipped": True}
        if req.push_to_hub:
            from edge.receiving.ingredient_scale import ScaleReading
            hub_result = await scale.post_weight_event(
                reading=ScaleReading(
                    scale_id=reading["scale_id"],
                    gross_weight_kg=reading["gross_weight_kg"],
                    net_weight_kg=reading["net_weight_kg"],
                    tare_kg=reading["tare_kg"],
                    stable=reading["stable"],
                    timestamp=reading["timestamp"],
                    source=reading["source"],
                    unit=reading.get("unit", "kg"),
                    raw=reading.get("raw", {}),
                ),
                expected_weight_kg=req.expected_weight_kg,
                batch_ref=req.batch_ref,
                sku=req.sku,
            )

        alerts = []
        if comparison.get("deviation_flag"):
            alerts.append({
                "type": "weight_deviation",
                "severity": "critical",
                "message": f"重量偏差 {comparison.get('deviation_pct')}%，超过 {comparison.get('threshold_pct')}%",
            })
        if quality_result and quality_result.get("alert"):
            alerts.append({
                "type": "quality_score_low",
                "severity": "warning",
                "message": f"品质评分 {quality_result.get('quality_score')} 低于阈值 {quality_result.get('threshold')}",
            })

        result = {
            "ok": True,
            "store_id": STORE_ID,
            "batch_ref": req.batch_ref,
            "sku": req.sku,
            "weight": weight_result,
            "quality": quality_result,
            "alerts": alerts,
            "hub_pushed": hub_result.get("ok", False),
            "hub_response": hub_result,
            "total_ms": round((time.perf_counter() - t0) * 1000, 1),
        }
        _last_session.update({"status": "ok", "last_result": result})
        return result
    except HTTPException:
        _last_session.update({"status": "error", "last_error": "http_error"})
        raise
    except Exception as exc:
        _last_session.update({"status": "error", "last_error": str(exc)})
        raise HTTPException(500, f"receiving 检测失败: {exc}") from exc


@router.get("/receiving/health")
def receiving_health() -> Dict[str, Any]:
    """Receiving module health check."""
    return {
        "module": "receiving",
        "active": _active,
        "scale_source": os.environ.get("SCALE_SOURCE", "mock" if os.environ.get("MOCK_SCALE") == "1" else "mock"),
        "mock_scale": os.environ.get("MOCK_SCALE") == "1",
        "mock_quality": os.environ.get("MOCK_QUALITY") == "1" or os.environ.get("HOTPOT_DEV_MODE") == "1",
        "capabilities": ["weight_tare", "weight_deviation", "discoloration", "wilting", "foreign_objects"],
    }


status_router = APIRouter(tags=["receiving"])


@status_router.get("/status/receiving")
def receiving_status() -> Dict[str, Any]:
    """Return current receiving session status."""
    return {
        "module": "receiving",
        "active": _active,
        **_last_session,
    }
