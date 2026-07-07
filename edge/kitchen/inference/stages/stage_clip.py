#!/usr/bin/env python3
"""
Stage 2 — CLIP-Adapter 分类

对 YOLO 检测到的每个 ROI 运行 CLIP 分类。
低置信度 ROI 标记为需要 VLM 进一步分析。
"""

import json
import subprocess
import time
from pathlib import Path

from ..rules import CLIP_DEFAULT_CLASSES, CLIP_LOW_CONF_THRESHOLD

STAGE_NAME = "clip"
STAGE_ORDER = 2

SCRIPT = Path(__file__).resolve().parents[1] / "clip_infer.py"
ADAPTER_PATH = "/opt/hotpot-infer/models/adapter_weights.pt"


def run(frame_path: str, ctx: dict) -> dict:
    yolo = ctx.get("yolo_result", {})
    if yolo.get("status") != "ok":
        ctx["clip_results"] = [{"status": "skipped", "reason": "yolo_failed"}]
        return ctx["clip_results"][0]

    detections = yolo.get("detections", [])
    if not detections:
        ctx["clip_results"] = [{"status": "skipped", "reason": "no_detections"}]
        return ctx["clip_results"][0]

    classes = ctx.get("clip_classes", CLIP_DEFAULT_CLASSES)
    clip_results = []
    rois_to_vlm = []

    for i, det in enumerate(detections):
        roi_path = det.get("roi_path", frame_path)

        cmd = [
            "docker", "run", "--rm", "--runtime=nvidia",
            "-v", "/opt/hotpot-infer:/opt/hotpot-infer",
            "-v", "/tmp:/tmp",
            "nvcr.io/nvidia/l4t-pytorch:r34.1.1-pth1.12-py3",
            "python3", str(SCRIPT),
            "--image", roi_path,
            "--classes", classes,
            "--adapter", ADAPTER_PATH,
            "--device", "cuda",
        ]

        t0 = time.time()
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            dt = round((time.time() - t0) * 1000, 1)

            if result.returncode in (0, 1):
                data = json.loads(result.stdout)
            else:
                data = {"status": "error", "error": result.stderr or f"exit={result.returncode}"}

            data["inference_ms"] = dt
            data["det_index"] = i
            clip_results.append(data)

            if data.get("low_confidence", False):
                rois_to_vlm.append({"index": i, "roi_path": roi_path, "clip": data})

        except (subprocess.TimeoutExpired, json.JSONDecodeError) as e:
            clip_results.append({"status": "error", "error": str(e), "det_index": i, "inference_ms": 0})

    ctx["clip_results"] = clip_results
    ctx["rois_to_vlm"] = rois_to_vlm
    return clip_results if clip_results else {"status": "skipped"}
