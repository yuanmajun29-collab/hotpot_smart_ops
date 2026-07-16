#!/usr/bin/env python3
"""
后厨推理管线调度器 — 基于注册表的可插拔架构

推理规则（阈值/类别/降级策略）→ rules.py
推理引擎（YOLO/CLIP/VLM 子进程）→ yolo_infer / clip_infer / vlm_infer.py（独立脚本）
管线级（每级一个文件）→ stages/

4 阶段管线: YOLO → CLIP → VLM → Count
  Stage 1: YOLO TensorRT 检测 + Kalman 跟踪
  Stage 2: CLIP-Adapter 分类
  Stage 3: VLM 语义分析（Ostrakon-VL，仅低置信度 ROI）
  Stage 4: 废料计数（Jetson :8100 计数 API）

新增管线级 = 在 stages/ 丢一个 stage_xxx.py，自动注册。
新增规则 = 在 rules.py 追加。
新增引擎 = 新增脚本 + 新增 stage 文件调用。

调用方式:
    python3 pipeline.py --frame /tmp/ipc_frames/latest.jpg --output /tmp/pipeline_result.json
"""

import argparse
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

from typing import Optional

from .stages import STAGES
from .rules import DEGRADATION_MATRIX, CLIP_DEFAULT_CLASSES, ENABLE_KALMAN, YOLO_MODEL_VERSION

# ── 路径 / Hub 配置 ──
HUB_URL = os.environ.get("HOTPOT_HUB_URL", "http://192.168.2.85:8098")
STORE_ID = os.environ.get("HOTPOT_STORE_ID", "store_yuhuan")
ZONE = os.environ.get("HOTPOT_ZONE", "备餐废弃区")
COUNT_API_URL = os.environ.get("HOTPOT_COUNT_API_URL", "http://127.0.0.1:8100")


def run_pipeline(frame_path: str, skip_vlm: bool = False, clip_classes: Optional[str] = None, count_api_url: Optional[str] = None) -> dict:
    """
    按 stages/ 注册表顺序执行管线。

    ctx 作为共享上下文在各级间传递：
      frame_path, zone, store_id, yolo_result, clip_results, vlm_results, items, rois_to_vlm
    """
    ctx = {
        "frame_path": frame_path,
        "zone": ZONE,
        "store_id": STORE_ID,
        "clip_classes": clip_classes or CLIP_DEFAULT_CLASSES,
        "skip_vlm": skip_vlm,
        "enable_kalman": ENABLE_KALMAN,
        "yolo_model": YOLO_MODEL_VERSION,
        "count_api_url": count_api_url or COUNT_API_URL,
    }

    pipeline_result = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "store_id": STORE_ID,
        "zone": ZONE,
        "frame": frame_path,
        "source": "vlm-shadow",
        "pipeline_version": "2.0",
        "stages": {},
        "items": [],
    }

    # ── 按注册表顺序执行各级 ──
    for stage in STAGES:
        name = stage["name"]

        # VLM 可通过 skip_vlm 跳过
        if name == "vlm" and skip_vlm:
            pipeline_result["stages"]["vlm"] = {"status": "skipped", "reason": "skip_vlm_flag"}
            continue

        result = stage["run"](frame_path, ctx)
        pipeline_result["stages"][name] = result

        # ── 降级检查 ──
        if name == "yolo" and result.get("status") == "error":
            pipeline_result["status"] = "degraded"
            pipeline_result["error"] = f"YOLO failed: {result.get('error', 'unknown')}"
            return pipeline_result

        if name == "yolo" and not ctx.get("yolo_result", {}).get("detections"):
            pipeline_result["status"] = "ok"
            pipeline_result["reason"] = "no_detections"
            return pipeline_result

    # ── 聚合结果 ──
    clip_results = ctx.get("clip_results", [])
    vlm_results = ctx.get("vlm_results", [])
    count_results = ctx.get("count_results", {})

    # 从 count_results 构建 det_index → count 映射
    count_map = {}
    for d in count_results.get("details", []):
        idx = d.get("det_index")
        if idx is not None:
            count_map[idx] = d.get("count", 0)

    # 从 VLM 收集 items
    for vlm in vlm_results:
        if vlm.get("items"):
            det_idx = vlm.get("det_index", 0)
            clip = clip_results[det_idx] if det_idx < len(clip_results) else {}
            for item in vlm["items"]:
                item["source"] = clip.get("top_class", "unknown")
                # ── 注入计数 ──
                if det_idx in count_map:
                    item["count"] = count_map[det_idx]
                pipeline_result["items"].append(item)

    # 从 CLIP 高置信度结果聚合
    for clip in clip_results:
        if clip.get("status") == "ok" and not clip.get("low_confidence", False):
            item = {
                "waste_type": "备餐废弃",
                "sku": clip.get("top_class", "unknown"),
                "confidence": clip.get("top_confidence", 0),
                "reason": f"CLIP-Adapter: {clip.get('top_class', 'unknown')}",
            }
            # ── 注入计数 ──
            det_idx = clip.get("det_index")
            if det_idx is not None and det_idx in count_map:
                item["count"] = count_map[det_idx]
            pipeline_result["items"].append(item)

    # ── 总计数汇总 ──
    if count_results.get("status") in ("ok", "partial"):
        pipeline_result["total_waste_count"] = count_results.get("total_count", 0)

    # ── 保留 count stage 的降级状态，不无条件覆写为 "ok" ──
    if pipeline_result.get("status") is None:
        pipeline_result["status"] = count_results.get("status", "ok")
    elif count_results.get("status") in ("partial", "degraded", "error"):
        pipeline_result["status"] = count_results["status"]
    else:
        pipeline_result["status"] = "ok"
    pipeline_result["item_count"] = len(pipeline_result["items"])

    return pipeline_result


def post_to_hub(result: dict, hub_url: str = HUB_URL, max_retries: int = 3) -> dict:
    """POST pipeline result to Hub with retry."""
    import httpx

    payload = json.dumps(result).encode("utf-8")
    url = f"{hub_url}/api/v1/vlm/waste-estimate"

    last_error = ""
    for attempt in range(max_retries):
        try:
            resp = httpx.post(
                url, content=payload,
                headers={"Content-Type": "application/json", "X-Api-Key": os.environ.get("HOTPOT_API_KEY", "")},
                timeout=15,
            )
            resp.raise_for_status()
            return {"status": "ok", "event_id": resp.json().get("event_id", "")}
        except Exception as e:
            last_error = str(e)
            time.sleep(1)
    return {"status": "error", "error": last_error}


def main():
    parser = argparse.ArgumentParser(description="Hotpot Kitchen Inference Pipeline")
    parser.add_argument("--frame", required=True, help="Input frame path")
    parser.add_argument("--output", default="-", help="Output path (- for stdout)")
    parser.add_argument("--skip-vlm", action="store_true", help="Skip VLM stage")
    parser.add_argument("--clip-classes", help="Custom CLIP classes (comma-separated)")
    parser.add_argument("--hub", help="Hub URL for result posting (optional)")
    parser.add_argument("--count-api", help="Jetson count API URL (default http://127.0.0.1:8100)")
    parser.add_argument("--list-stages", action="store_true", help="List available stages and exit")
    args = parser.parse_args()

    if args.list_stages:
        from .stages import list_stages
        print("Available stages:", list_stages())
        return

    t0 = time.time()
    result = run_pipeline(args.frame, args.skip_vlm, args.clip_classes, args.count_api)
    result["total_ms"] = round((time.time() - t0) * 1000, 1)

    output = json.dumps(result, ensure_ascii=False, indent=2)

    if args.output == "-":
        print(output)
    else:
        Path(args.output).write_text(output)
        print(f"Saved to {args.output}")

    if args.hub:
        post_result = post_to_hub(result, args.hub)
        print(f"Hub: {json.dumps(post_result, ensure_ascii=False)}")

    if result["status"] == "error":
        import sys
        sys.exit(1)


if __name__ == "__main__":
    main()
