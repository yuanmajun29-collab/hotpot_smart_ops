"""SOP 视觉合规推理模块 — FastAPI router for Edge Agent.

提供 POST /infer/sop 端点，接收摄像头帧 → YOLO + PPE检测 → 状态机 → Hub推送。

集成到 Edge Agent 的 server.py _MODULE_REGISTRY 中。
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import cv2
import numpy as np
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from edge.agent.config import PROJECT_ROOT, HUB_URL, STORE_ID, API_KEY, OUTPUT_DIR

router = APIRouter(prefix="/infer", tags=["sop"])

# 由 server.py 在配置驱动下设置
_active = False
_zone = "sop"

# ── 7 工位定义 ──
STATION_IDS = [
    "sop_broth", "sop_cutting", "sop_plating",
    "sop_sauce", "sop_washing", "sop_serving", "sop_cold_storage",
]

STATION_NAMES = {
    "sop_broth": "汤底",
    "sop_cutting": "切配",
    "sop_plating": "摆盘",
    "sop_sauce": "蘸料",
    "sop_washing": "洗消",
    "sop_serving": "传菜",
    "sop_cold_storage": "冷库",
}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


class SopInferRequest(BaseModel):
    """SOP 视觉合规检测请求。"""
    image_path: Optional[str] = None
    station_id: str = "sop_broth"
    frame_base64: Optional[str] = None


class SopVisionResult(BaseModel):
    """SOP 视觉合规单帧检测结果。"""
    station_id: str
    compliant: bool
    violations: List[Dict[str, str]]
    person_count: int
    timestamp: str


def _check_active():
    if not _active:
        raise HTTPException(503, "sop 模块未激活（配置中无 sop zone）")


def _decode_base64_frame(b64: str) -> np.ndarray:
    """解码 base64 摄像头帧为 numpy 数组。"""
    import base64
    if b64.startswith("data:image"):
        b64 = b64.split(",", 1)[1]
    raw = base64.b64decode(b64)
    arr = np.frombuffer(raw, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("无法解码 base64 图片")
    return img


def run_sop_vision_inference(
    image_path: str,
    station_id: str = "sop_broth",
) -> SopVisionResult:
    """执行 SOP 视觉合规检测：读帧 → YOLO + PPE → 结果。

    调用 stage_sop.run() 进行 PPE 检测。
    """
    from edge.kitchen.inference.stages.stage_sop import run as sop_stage_run

    ctx = {
        "station_id": station_id,
        "zone": "kitchen",
    }

    # 先尝试用 RealYoloDetector 预检
    try:
        from edge.common.detector.real_yolo import RealYoloDetector
        img = cv2.imread(image_path)
        if img is not None:
            detector = RealYoloDetector(conf=0.25)
            yolo_result = detector.detect(img, zone="kitchen")
            ctx["yolo_result"] = yolo_result
    except Exception:
        pass

    result = sop_stage_run(image_path, ctx)

    return SopVisionResult(
        station_id=station_id,
        compliant=result.get("compliant", False),
        violations=result.get("violations", []),
        person_count=result.get("person_count", 0),
        timestamp=utc_now_iso(),
    )


def push_sop_result_to_hub(result: SopVisionResult) -> Dict[str, Any]:
    """将 SOP 检测结果推送到 Hub POST /v1/sop/compliance。"""
    import httpx

    payload = {
        "store_id": STORE_ID,
        "device_id": os.environ.get("HOTPOT_DEVICE_ID", "jetson-sop-01"),
        "timestamp": result.timestamp,
        "stations": [{
            "station_id": result.station_id,
            "name": STATION_NAMES.get(result.station_id, result.station_id),
            "status": "running" if result.compliant else "warning",
            "readings": {
                "vision_violations": [v["type"] for v in result.violations],
                "person_count": result.person_count,
            },
            "message": "视觉合规通过" if result.compliant else f"视觉违规: {len(result.violations)}项",
            "updated_at": result.timestamp,
        }],
        "summary": {
            "total": 1,
            "running": 1 if result.compliant else 0,
            "warning": 0 if result.compliant else 1,
            "violation": 0,
            "compliance_rate": 100.0 if result.compliant else 0.0,
        },
    }

    try:
        resp = httpx.post(
            f"{HUB_URL}/v1/sop/compliance",
            json=payload,
            headers={"X-Api-Key": API_KEY, "Content-Type": "application/json"},
            timeout=10.0,
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ═══════════════════════════════════════════════════════════════
# API 端点
# ═══════════════════════════════════════════════════════════════


@router.get("/sop/health")
def sop_health():
    """SOP 模块健康检查。"""
    try:
        from edge.kitchen.inference.stages.stage_sop import STAGE_NAME
        stage_available = True
    except ImportError:
        stage_available = False
    return {
        "module": "sop",
        "active": _active,
        "zone": _zone,
        "stage_sop_available": stage_available,
        "stations": list(STATION_NAMES.values()),
    }


@router.post("/sop")
def sop_infer(req: SopInferRequest):
    """SOP 视觉合规检测端点。

    接收图片路径或 base64 帧 → YOLO+PPE检测 → 返回合规结果。
    """
    _check_active()

    if req.station_id not in STATION_IDS:
        raise HTTPException(400, f"无效工位ID: {req.station_id}，可选: {STATION_IDS}")

    # 处理图片
    img_path = ""
    if req.frame_base64:
        import tempfile
        frame = _decode_base64_frame(req.frame_base64)
        fd, tmp_path = tempfile.mkstemp(suffix=".jpg", prefix="hotpot_sop_")
        os.close(fd)
        cv2.imwrite(tmp_path, frame)
        img_path = tmp_path
    elif req.image_path:
        img_path = req.image_path
    else:
        raise HTTPException(400, "请提供 image_path 或 frame_base64")

    # 校验图片存在
    p = Path(img_path)
    if not p.is_absolute():
        p = PROJECT_ROOT / p
    if not p.exists():
        raise HTTPException(404, f"图片不存在: {img_path}")

    # 执行推理
    t0 = time.perf_counter()
    result = run_sop_vision_inference(str(p), req.station_id)
    total_ms = round((time.perf_counter() - t0) * 1000, 1)

    # 推送到 Hub（best-effort）
    hub_result = push_sop_result_to_hub(result)

    return {
        "ok": True,
        "mode": "vision",
        "station_id": result.station_id,
        "station_name": STATION_NAMES.get(result.station_id, result.station_id),
        "compliant": result.compliant,
        "violations": result.violations,
        "person_count": result.person_count,
        "timestamp": result.timestamp,
        "inference_ms": total_ms,
        "hub_pushed": hub_result.get("ok", False),
    }


@router.get("/sop/stations")
def sop_stations_list():
    """列出所有 SOP 工位。"""
    return {
        "stations": [
            {"id": sid, "name": STATION_NAMES[sid]}
            for sid in STATION_IDS
        ],
    }
