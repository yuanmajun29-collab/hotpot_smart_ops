"""员工行为推理模块 — FastAPI router for Edge Agent.

封装 StaffBehaviorDetector，提供 POST /infer/staff 端点。
集成到 Edge Agent 的 server.py _MODULE_REGISTRY 中。

检测能力:
  - PPE 穿戴合规：帽子、围裙、口罩
  - 异常行为：徘徊 (loitering)、私语 (whispering)、区域入侵
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import cv2
import numpy as np
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from edge.agent.config import PROJECT_ROOT, HUB_URL, STORE_ID, API_KEY

router = APIRouter(prefix="/infer", tags=["staff_behavior"])

# 由 server.py 在配置驱动下设置
_active = False
_detector = None


def _check_active():
    if not _active:
        raise HTTPException(503, "staff_behavior 模块未激活（配置中无 staff_behavior zone）")


def _get_detector():
    """懒加载 StaffBehaviorDetector。"""
    global _detector
    if _detector is None:
        from edge.staff_behavior.detector import StaffBehaviorDetector
        _detector = StaffBehaviorDetector()
    return _detector


class StaffInferRequest(BaseModel):
    """员工行为推理请求。"""
    image_path: Optional[str] = None
    frame_base64: Optional[str] = None
    camera_id: str = "cam_staff_01"
    zone: str = "kitchen"


class StaffInferResponse(BaseModel):
    """员工行为推理响应。"""
    ok: bool
    frame_id: str
    timestamp: str
    person_count: int
    ppe_compliance_rate: float
    whispering_pairs: int
    loitering_count: int
    alerts: List[Dict[str, Any]]
    total_ms: float


def _decode_base64_frame(b64: str) -> np.ndarray:
    """解码 base64 摄像头帧。"""
    import base64
    if b64.startswith("data:image"):
        b64 = b64.split(",", 1)[1]
    raw = base64.b64decode(b64)
    arr = np.frombuffer(raw, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("无法解码 base64 图片")
    return img


# ═══════════════════════════════════════════════════════════════
# API 端点
# ═══════════════════════════════════════════════════════════════


@router.get("/staff/health")
def staff_health():
    """员工行为模块健康检查。"""
    return {
        "module": "staff_behavior",
        "active": _active,
        "detector": "StaffBehaviorDetector",
        "capabilities": ["ppe_compliance", "loitering", "whispering", "zone_intrusion"],
    }


@router.post("/staff")
def staff_infer(req: StaffInferRequest):
    """员工行为检测端点。

    接收图片 → YOLO人员检测 → PPE合规 + 徘徊/私语/区域入侵 → 返回结果。

    **请求体**:
    ```json
    {
      "image_path": "path/to/staff_image.jpg",
      "camera_id": "cam_staff_01",
      "zone": "kitchen"
    }
    ```

    **响应示例**:
    ```json
    {
      "ok": true,
      "frame_id": "abc123...",
      "person_count": 3,
      "ppe_compliance_rate": 66.7,
      "whispering_pairs": 2,
      "loitering_count": 1,
      "alerts": [
        {"type": "loitering", "severity": "warning"},
        {"type": "whispering", "severity": "info"}
      ],
      "total_ms": 145.3
    }
    ```
    """
    _check_active()

    # 获取图片
    frame = None
    if req.frame_base64:
        frame = _decode_base64_frame(req.frame_base64)
    elif req.image_path:
        img_path = Path(req.image_path)
        if not img_path.is_absolute():
            img_path = PROJECT_ROOT / img_path
        if not img_path.exists():
            raise HTTPException(404, f"图片不存在: {req.image_path}")
        frame = cv2.imread(str(img_path))
        if frame is None:
            raise HTTPException(400, f"无法读取图片: {req.image_path}")
    else:
        raise HTTPException(400, "请提供 image_path 或 frame_base64")

    # 执行检测
    detector = _get_detector()
    t0 = time.perf_counter()

    try:
        result = detector.detect(frame, camera_id=req.camera_id, zone=req.zone)
    except Exception as e:
        raise HTTPException(500, f"检测失败: {e}")

    total_ms = round((time.perf_counter() - t0) * 1000, 1)

    return {
        "ok": True,
        "frame_id": result.frame_id,
        "timestamp": result.timestamp,
        "store_id": STORE_ID,
        "zone": result.zone,
        "camera_id": result.camera_id,
        "person_count": result.person_count,
        "ppe_compliance_rate": result.ppe_compliance_rate,
        "whispering_pairs": result.whispering_pairs,
        "loitering_count": result.loitering_count,
        "alerts": result.alerts,
        "total_ms": total_ms,
    }
