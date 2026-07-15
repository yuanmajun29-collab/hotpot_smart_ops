#!/usr/bin/env python3
"""
Stage 4 — 废料计数（Jetson :8100 计数API）

对 YOLO 检测到的每个废料 ROI，调用 Jetson 计数 API 获取精确计数。
传入废料 crop 图片 → Jetson 返回 count 整数。

API 约定:
    POST {COUNT_API_URL}/count
    Content-Type: multipart/form-data
    参数: image (file), zone (str)
    返回: {"count": N, "status": "ok"}

Jetson API URL 通过 ctx["count_api_url"] 传入，默认 http://127.0.0.1:8100
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx

STAGE_NAME = "count"
STAGE_ORDER = 4

DEFAULT_COUNT_API_URL = "http://127.0.0.1:8100"


def _call_count_api(
    image_path: str,
    api_url: str,
    zone: str,
    timeout: float = 10.0,
) -> Dict[str, Any]:
    """调用 Jetson 计数 API，传入图片，返回计数结果。"""
    try:
        with open(image_path, "rb") as f:
            files = {"image": (Path(image_path).name, f, "image/jpeg")}
            data = {"zone": zone}
            resp = httpx.post(
                f"{api_url}/count",
                files=files,
                data=data,
                timeout=timeout,
            )
        resp.raise_for_status()
        return resp.json()
    except httpx.TimeoutException:
        return {"status": "error", "error": f"count API timeout ({timeout}s)", "count": 0}
    except httpx.HTTPStatusError as e:
        return {"status": "error", "error": f"HTTP {e.response.status_code}", "count": 0}
    except Exception as e:
        return {"status": "error", "error": str(e), "count": 0}


def run(frame_path: str, ctx: dict) -> dict:
    """对每个废料 ROI 调用 Jetson 计数 API，返回计数汇总。"""
    api_url = ctx.get("count_api_url", DEFAULT_COUNT_API_URL)
    zone = ctx.get("zone", "备餐废弃区")

    # ── 收集所有需要计数的 ROI ──
    rois: List[Dict[str, Any]] = []

    # 方式1: 从 CLIP 结果 + YOLO detections 中取 ROI
    yolo_result = ctx.get("yolo_result", {})
    detections = yolo_result.get("detections", [])

    clip_results = ctx.get("clip_results", [])
    vlm_results = ctx.get("vlm_results", [])

    # 收集有 roi_path 的检测
    for i, det in enumerate(detections):
        roi_path = det.get("roi_path")
        if roi_path and Path(roi_path).exists():
            rois.append({"index": i, "roi_path": roi_path, "source": "yolo"})

    # 也收集 VLM 处理的 ROI（避免重复）
    seen_paths = {r["roi_path"] for r in rois}
    for vlm in vlm_results:
        roi_path = vlm.get("roi_path")
        if roi_path and Path(roi_path).exists() and roi_path not in seen_paths:
            rois.append({"index": vlm.get("det_index", -1), "roi_path": roi_path, "source": "vlm"})
            seen_paths.add(roi_path)

    if not rois:
        ctx["count_results"] = {"status": "skipped", "reason": "no_rois_for_count", "total_count": 0, "details": []}
        return ctx["count_results"]

    # ── 逐个调用计数 API ──
    details: List[Dict[str, Any]] = []
    total_count = 0
    api_errors = 0

    # ── 首次调用 120s（模型可能需下载），后续 10s ──
    count_first_call = ctx.get("count_first_call", True)

    for roi in rois:
        t0 = time.time()
        timeout = 120.0 if count_first_call else 10.0
        result = _call_count_api(roi["roi_path"], api_url, zone, timeout=timeout)
        count_first_call = False
        dt = round((time.time() - t0) * 1000, 1)

        count = result.get("count", 0)
        if isinstance(count, (int, float)):
            count = int(count)
        else:
            count = 0

        # ── 截断到 0-200 范围（Spec §2.1 边界约束）──
        if count > 200:
            count = 200
            if result.get("status") == "ok":
                result["status"] = "capped"
        elif count < 0:
            count = 0

        detail = {
            "det_index": roi["index"],
            "roi_path": roi["roi_path"],
            "source": roi["source"],
            "count": count,
            "inference_ms": dt,
            "status": result.get("status", "ok"),
        }
        if result.get("error"):
            detail["error"] = result["error"]
            api_errors += 1

        details.append(detail)
        total_count += count

    count_result = {
        "status": "ok" if api_errors == 0 else "partial",
        "total_count": total_count,
        "api_errors": api_errors,
        "roi_count": len(rois),
        "details": details,
    }

    ctx["count_results"] = count_result

    # ── 将计数注入到 ctx items 中，供 pipeline 聚合使用 ──
    # 构建 det_index → count 映射
    count_map = {d["det_index"]: d["count"] for d in details}

    # 注入到 clip_results
    for clip in clip_results:
        idx = clip.get("det_index")
        if idx is not None and idx in count_map:
            clip["count"] = count_map[idx]

    # 注入到 vlm_results
    for vlm in vlm_results:
        idx = vlm.get("det_index")
        if idx is not None and idx in count_map:
            vlm["count"] = count_map[idx]

    return count_result
