#!/usr/bin/env python3
"""
Stage 3 — VLM 语义分析（Ostrakon-VL）

仅对 CLIP 低置信度 ROI 触发，调用 llama.cpp 做细粒度废弃物识别。
"""

import json
import subprocess
import time
from pathlib import Path

from ..rules import VLM_TIMEOUT_SEC

STAGE_NAME = "vlm"
STAGE_ORDER = 3

SCRIPT = Path(__file__).resolve().parents[1] / "vlm_infer.py"


def run(frame_path: str, ctx: dict) -> dict:
    rois = ctx.get("rois_to_vlm", [])
    if not rois:
        ctx["vlm_results"] = [{"status": "skipped", "reason": "no_low_confidence_rois"}]
        return ctx["vlm_results"][0]

    vlm_results = []
    for roi in rois:
        cmd = [
            "python3", str(SCRIPT),
            "--image", roi["roi_path"],
            "--zone", ctx.get("zone", "备餐废弃区"),
        ]

        t0 = time.time()
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=VLM_TIMEOUT_SEC)
            dt = round((time.time() - t0) * 1000, 1)

            if result.returncode == 0:
                data = json.loads(result.stdout)
            else:
                data = {"status": "error", "error": result.stderr or f"exit={result.returncode}"}

            data["inference_ms"] = dt
            data["det_index"] = roi["index"]
            vlm_results.append(data)

        except (subprocess.TimeoutExpired, json.JSONDecodeError) as e:
            vlm_results.append({"status": "error", "error": str(e), "det_index": roi["index"]})

    ctx["vlm_results"] = vlm_results
    return vlm_results
