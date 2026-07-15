#!/usr/bin/env python3
"""
Stage 1 — YOLO TensorRT 检测 + Kalman 跟踪

调用 yolo_infer.py 子进程，返回检测结果。
可选择启用 Kalman 跟踪器平滑检测框。
"""

import json
import subprocess
import time
from pathlib import Path
from typing import Optional

from ..rules import YOLO_IOU_THRESH, YOLO_CONF_THRESH
from ..kalman_tracker import KalmanTracker

STAGE_NAME = "yolo"
STAGE_ORDER = 1

SCRIPT = Path(__file__).resolve().parents[1] / "yolo_infer.py"
MODEL_DIR = "/opt/hotpot-infer/models"
YOLO_ONNX = f"{MODEL_DIR}/yolo26l.onnx"

# 全局跟踪器实例 (跨帧保持)
_TRACKER: Optional[KalmanTracker] = None


def _get_tracker() -> KalmanTracker:
    """获取或创建 Kalman 跟踪器 (延迟初始化)."""
    global _TRACKER
    if _TRACKER is None:
        _TRACKER = KalmanTracker(
            max_age=5,          # 5 帧后丢弃
            min_hits=2,         # 2 次确认后输出
            iou_thresh=0.25,    # IoU 匹配阈值
        )
    return _TRACKER


def run(frame_path: str, ctx: dict) -> dict:
    """运行 YOLO 检测 + 可选 Kalman 跟踪."""
    if not Path(YOLO_ONNX).exists():
        err = f"YOLO model not found: {YOLO_ONNX}"
        ctx["yolo_result"] = {"status": "error", "error": err}
        return ctx["yolo_result"]

    enable_kalman = ctx.get("enable_kalman", True)

    t0 = time.time()
    try:
        result = subprocess.run(
            ["python3", str(SCRIPT), frame_path],
            capture_output=True, text=True, timeout=60,
        )
        dt = (time.time() - t0) * 1000

        if result.returncode != 0:
            ctx["yolo_result"] = {"status": "error", "error": result.stderr, "inference_ms": round(dt, 1)}
        else:
            data = json.loads(result.stdout)
            detections = data if isinstance(data, list) else []

            # ── Kalman 跟踪 (可选) ──
            kalman_ms = 0
            if enable_kalman and len(detections) > 0:
                tk_t0 = time.time()
                try:
                    tracker = _get_tracker()
                    tracked = tracker.update(detections)
                    # 用平滑后的 bbox 替换
                    for i, t in enumerate(tracked):
                        if t.get("tracker_id", -1) >= 0 and "smoothed_bbox" in t:
                            detections[i]["bbox"] = t["smoothed_bbox"]
                            detections[i]["tracker_id"] = t["tracker_id"]
                    kalman_ms = round((time.time() - tk_t0) * 1000, 1)
                except Exception:
                    pass  # Kalman 失败时回退到原始检测

            ctx["yolo_result"] = {
                "detections": detections,
                "count": len(detections),
                "inference_ms": round(dt, 1),
                "kalman_ms": kalman_ms,
                "status": "ok",
            }
    except subprocess.TimeoutExpired:
        dt = 60 * 1000
        ctx["yolo_result"] = {"status": "error", "error": "YOLO timeout (60s)", "inference_ms": round(dt, 1)}
    except Exception as e:
        ctx["yolo_result"] = {"status": "error", "error": str(e), "inference_ms": 0}

    return ctx["yolo_result"]
