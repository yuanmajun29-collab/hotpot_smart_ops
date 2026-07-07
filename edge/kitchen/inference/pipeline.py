#!/usr/bin/env python3
"""
后厨推理管线调度器 — 基于注册表的可插拔架构

推理规则（阈值/类别/降级策略）→ rules.py
推理引擎（YOLO/CLIP/VLM 子进程）→ yolo_infer / clip_infer / vlm_infer.py（独立脚本）
管线级（每级一个文件）→ stages/

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

from .stages import STAGES
from .rules import DEGRADATION_MATRIX, CLIP_DEFAULT_CLASSES

# ── 路径 / Hub 配置 ──
HUB_URL = os.environ.get("HOTPOT_HUB_URL", "http://192.168.2.85:8098")
STORE_ID = os.environ.get("HOTPOT_STORE_ID", "store_yuhuan")
ZONE = os.environ.get("HOTPOT_ZONE", "备餐废弃区")


def run_pipeline(frame_path: str, skip_vlm: bool = False, clip_classes: str = None) -> dict:
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

    # 从 VLM 收集 items
    for vlm in vlm_results:
        if vlm.get("items"):
            det_idx = vlm.get("det_index", 0)
            clip = clip_results[det_idx] if det_idx < len(clip_results) else {}
            for item in vlm["items"]:
                item["source"] = clip.get("top_class", "unknown")
                pipeline_result["items"].append(item)

    # 从 CLIP 高置信度结果聚合
    for clip in clip_results:
        if clip.get("status") == "ok" and not clip.get("low_confidence", False):
            pipeline_result["items"].append({
                "waste_type": "备餐废弃",
                "sku": clip.get("top_class", "unknown"),
                "confidence": clip.get("top_confidence", 0),
                "reason": f"CLIP-Adapter: {clip.get('top_class', 'unknown')}",
            })

    pipeline_result["status"] = "ok"
    pipeline_result["item_count"] = len(pipeline_result["items"])

    return pipeline_result


def post_to_hub(result: dict, hub_url: str = HUB_URL) -> dict:
    """POST pipeline result to Mac Hub."""
    import urllib.request

    payload = json.dumps(result).encode("utf-8")
    url = f"{hub_url}/v1/vlm/waste-estimate"

    try:
        req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            return {"status": "ok", "event_id": json.loads(resp.read()).get("event_id", "")}
    except Exception as e:
        return {"status": "error", "error": str(e)}


def main():
    parser = argparse.ArgumentParser(description="Hotpot Kitchen Inference Pipeline")
    parser.add_argument("--frame", required=True, help="Input frame path")
    parser.add_argument("--output", default="-", help="Output path (- for stdout)")
    parser.add_argument("--skip-vlm", action="store_true", help="Skip VLM stage")
    parser.add_argument("--clip-classes", help="Custom CLIP classes (comma-separated)")
    parser.add_argument("--hub", help="Hub URL for result posting (optional)")
    parser.add_argument("--list-stages", action="store_true", help="List available stages and exit")
    args = parser.parse_args()

    if args.list_stages:
        from .stages import list_stages
        print("Available stages:", list_stages())
        return

    t0 = time.time()
    result = run_pipeline(args.frame, args.skip_vlm, args.clip_classes)
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
