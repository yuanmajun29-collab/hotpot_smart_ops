#!/usr/bin/env python3
"""
Stage 2 — CLIP-Adapter 分类（常驻子进程，不再每次 docker run）

对 YOLO 检测到的每个 ROI 运行 CLIP 分类。
低置信度 ROI 标记为需要 VLM 进一步分析。

子进程在首次调用时启动，后续复用 stdin/stdout JSON 行协议。
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..rules import CLIP_DEFAULT_CLASSES, CLIP_LOW_CONF_THRESHOLD

STAGE_NAME = "clip"
STAGE_ORDER = 2

SCRIPT = Path(__file__).resolve().parents[1] / "clip_infer.py"
ADAPTER_PATH = "/opt/hotpot-infer/models/adapter_weights.pt"

# ─── 常驻子进程 ───
_proc: Optional[subprocess.Popen] = None


def _ensure_clip_worker():
    """启动或复用 CLIP 子进程（stdin/stdout JSON 行协议）。"""
    global _proc
    if _proc is not None and _proc.poll() is None:
        return  # 已经在运行

    _proc = subprocess.Popen(
        [sys.executable, str(SCRIPT), "--adapter", ADAPTER_PATH, "--device", "cuda", "--server"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    # 等待就绪信号
    line = _proc.stdout.readline()
    try:
        data = json.loads(line)
        if not data.get("ready"):
            raise RuntimeError(f"CLIP worker 启动失败: {line.strip()}")
    except json.JSONDecodeError:
        raise RuntimeError(f"CLIP worker 异常输出: {line.strip()}")


def _clip_classify(image_path: str, classes: str) -> Dict[str, Any]:
    """通过常驻子进程执行 CLIP 分类。"""
    _ensure_clip_worker()
    _proc.stdin.write(json.dumps({"image": image_path, "classes": classes}) + "\n")
    _proc.stdin.flush()
    line = _proc.stdout.readline()
    return json.loads(line)


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
    clip_results: List[Dict[str, Any]] = []
    rois_to_vlm: List[dict] = []

    for i, det in enumerate(detections):
        roi_path = det.get("roi_path", frame_path)

        t0 = time.perf_counter()
        try:
            data = _clip_classify(roi_path, classes)
            dt = round((time.perf_counter() - t0) * 1000, 1)
        except (ConnectionError, subprocess.TimeoutExpired, RuntimeError) as e:
            clip_results.append({"status": "error", "error": str(e), "det_index": i, "inference_ms": 0})
            continue

        data["inference_ms"] = dt
        data["det_index"] = i
        clip_results.append(data)

        if data.get("low_confidence", False):
            rois_to_vlm.append({"index": i, "roi_path": roi_path, "clip": data})

    ctx["clip_results"] = clip_results
    ctx["rois_to_vlm"] = rois_to_vlm
    return clip_results if clip_results else {"status": "skipped"}
