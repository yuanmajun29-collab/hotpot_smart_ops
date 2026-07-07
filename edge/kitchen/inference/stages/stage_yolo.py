#!/usr/bin/env python3
"""
Stage 1 — YOLO TensorRT 检测

调用 yolo_infer.py 子进程，返回检测结果。
"""

import json
import subprocess
import time
from pathlib import Path

from ..rules import YOLO_IOU_THRESH, YOLO_CONF_THRESH

STAGE_NAME = "yolo"
STAGE_ORDER = 1

SCRIPT = Path(__file__).resolve().parents[1] / "yolo_infer.py"
MODEL_DIR = "/opt/hotpot-infer/models"
YOLO_ONNX = f"{MODEL_DIR}/yolo26l.onnx"


def run(frame_path: str, ctx: dict) -> dict:
    if not Path(YOLO_ONNX).exists():
        err = f"YOLO model not found: {YOLO_ONNX}"
        ctx["yolo_result"] = {"status": "error", "error": err}
        return ctx["yolo_result"]

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
            data["inference_ms"] = round(dt, 1)
            data["status"] = "ok"
            ctx["yolo_result"] = data
    except subprocess.TimeoutExpired:
        dt = 60 * 1000
        ctx["yolo_result"] = {"status": "error", "error": "YOLO timeout (60s)", "inference_ms": round(dt, 1)}
    except Exception as e:
        ctx["yolo_result"] = {"status": "error", "error": str(e), "inference_ms": 0}

    return ctx["yolo_result"]
