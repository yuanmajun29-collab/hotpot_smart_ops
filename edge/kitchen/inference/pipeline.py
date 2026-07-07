#!/usr/bin/env python3
"""推理流水线调度器 — 三级过滤: YOLO → CLIP-Adapter → Ostrakon-VL

调用方式:
    python3 inference_pipeline.py --frame /tmp/ipc_frames/latest.jpg --output /tmp/pipeline_result.json

降级矩阵:
    YOLO 故障 → 跳过推理, 记录错误
    CLIP 故障 → 跳过二级, 所有 ROI 直接 VLM
    VLM 故障 → 仅 YOLO + CLIP, 标记 vlm_unavailable
"""

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# ===== 路径配置 =====
BASE_DIR = Path(os.environ.get("HOTPOT_INFER_HOME", "/opt/hotpot-infer"))
PIPELINE_DIR = BASE_DIR / "pipeline"
MODEL_DIR = Path(os.environ.get("MODEL_DIR", str(BASE_DIR / "models")))
CONFIG_DIR = Path(os.environ.get("CONFIG_DIR", str(BASE_DIR / "config")))

YOLO_SCRIPT = PIPELINE_DIR / "yolo_infer.py"
CLIP_SCRIPT = PIPELINE_DIR / "clip_infer.py"
VLM_SCRIPT = PIPELINE_DIR / "vlm_infer.py"

ADAPTER_PATH = MODEL_DIR / "adapter_weights.pt"
YOLO_ONNX = MODEL_DIR / "yolo26l.onnx"

# Hub 配置 (可从配置文件覆盖)
HUB_URL = os.environ.get("HOTPOT_HUB_URL", "http://192.168.2.85:8098")
STORE_ID = os.environ.get("HOTPOT_STORE_ID", "store_yuhuan")
ZONE = os.environ.get("HOTPOT_ZONE", "备餐废弃区")

# CLIP 类别 (对应后厨场景)
CLIP_CLASSES = "clean_kitchen,dirty_surface,food_waste,cluttered,dangerous_object"


def run_cmd(cmd: list, timeout: int = 120) -> tuple:
    """Run subprocess, return (exit_code, stdout, stderr, elapsed_ms)."""
    t0 = time.time()
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        dt = (time.time() - t0) * 1000
        return result.returncode, result.stdout.strip(), result.stderr.strip(), round(dt, 1)
    except subprocess.TimeoutExpired:
        dt = timeout * 1000
        return -1, "", f"Timeout after {timeout}s", round(dt, 1)
    except FileNotFoundError as e:
        return -2, "", str(e), 0


# ===== Stage 1: YOLO 目标检测 =====
def stage_yolo(frame_path: str) -> dict:
    """Run YOLO TensorRT inference. Returns detections or error."""
    if not Path(YOLO_ONNX).exists():
        return {"status": "error", "error": f"YOLO model not found: {YOLO_ONNX}"}
    if not Path(YOLO_SCRIPT).exists():
        return {"status": "error", "error": f"YOLO script not found: {YOLO_SCRIPT}"}

    exit_code, stdout, stderr, dt = run_cmd(
        ["python3", str(YOLO_SCRIPT), frame_path],
        timeout=60,
    )

    if exit_code != 0:
        return {"status": "error", "error": stderr or f"exit={exit_code}", "inference_ms": dt}

    try:
        data = json.loads(stdout)
        data["inference_ms"] = dt
        data["status"] = "ok"
        return data
    except json.JSONDecodeError:
        return {"status": "error", "error": "YOLO output parse error", "raw": stdout[:200], "inference_ms": dt}


# ===== Stage 2: CLIP-Adapter 分类 =====
def stage_clip(image_path: str, classes: str = CLIP_CLASSES) -> dict:
    """Run CLIP-Adapter inside Docker. Returns classification result."""
    if not Path(CLIP_SCRIPT).exists():
        return {"status": "skipped", "reason": "CLIP script not found"}

    cmd = [
        "docker", "run", "--rm", "--runtime=nvidia",
        "-v", f"{BASE_DIR}:{BASE_DIR}",
        "-v", "/tmp:/tmp",
        "nvcr.io/nvidia/l4t-pytorch:r34.1.1-pth1.12-py3",
        "python3", str(CLIP_SCRIPT),
        "--image", image_path,
        "--classes", classes,
        "--adapter", str(ADAPTER_PATH),
        "--device", "cuda",
    ]

    exit_code, stdout, stderr, dt = run_cmd(cmd, timeout=120)

    if exit_code not in (0, 1):  # 0=high_conf, 1=low_conf, other=error
        return {"status": "error", "error": stderr or f"exit={exit_code}", "inference_ms": dt}

    try:
        data = json.loads(stdout)
        data["status"] = "ok"
        data["inference_ms"] = dt
        return data
    except json.JSONDecodeError:
        return {"status": "error", "error": "CLIP output parse error", "inference_ms": dt}


# ===== Stage 3: VLM 语义分析 =====
def stage_vlm(image_path: str, zone: str = ZONE) -> dict:
    """Run Ostrakon-VL. Returns waste analysis JSON."""
    if not Path(VLM_SCRIPT).exists():
        return {"status": "skipped", "reason": "VLM script not found"}

    exit_code, stdout, stderr, dt = run_cmd(
        ["python3", str(VLM_SCRIPT), "--image", image_path, "--zone", zone],
        timeout=45,
    )

    if exit_code != 0:
        return {"status": "error", "error": stderr or f"exit={exit_code}", "inference_ms": dt}

    try:
        data = json.loads(stdout)
        data["status"] = "ok"
        return data
    except json.JSONDecodeError:
        return {"status": "error", "error": "VLM output parse error", "inference_ms": dt}


# ===== Hub 上报 =====
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


# ===== 主流水线 =====
def run_pipeline(frame_path: str, skip_vlm: bool = False) -> dict:
    """Execute the full 3-stage inference pipeline."""
    pipeline_result = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "store_id": STORE_ID,
        "zone": ZONE,
        "frame": frame_path,
        "source": "vlm-shadow",
        "pipeline_version": "1.0",
        "stages": {},
        "items": [],
    }

    # --- Stage 1: YOLO ---
    yolo = stage_yolo(frame_path)
    pipeline_result["stages"]["yolo"] = yolo

    if yolo["status"] == "error":
        pipeline_result["status"] = "degraded"
        pipeline_result["error"] = f"YOLO failed: {yolo.get('error', 'unknown')}"
        return pipeline_result

    detections = yolo.get("detections", [])
    if not detections:
        pipeline_result["status"] = "ok"
        pipeline_result["reason"] = "no_detections"
        return pipeline_result

    # --- Stage 2: CLIP for each ROI ---
    clip_results = []
    rois_to_vlm = []

    for i, det in enumerate(detections):
        # Crop ROI (handled by yolo_infer.py)
        roi_path = det.get("roi_path", frame_path)

        clip = stage_clip(roi_path)
        clip["det_index"] = i
        clip_results.append(clip)

        if clip.get("low_confidence", False) and not skip_vlm:
            rois_to_vlm.append({"index": i, "roi_path": roi_path, "clip": clip})

    pipeline_result["stages"]["clip"] = clip_results

    # --- Stage 3: VLM for low-confidence ROIs ---
    if rois_to_vlm:
        vlm_results = []
        for roi in rois_to_vlm:
            vlm = stage_vlm(roi["roi_path"])
            vlm["det_index"] = roi["index"]
            vlm_results.append(vlm)

            if vlm.get("items"):
                for item in vlm["items"]:
                    item["source"] = clip_results[roi["index"]].get("top_class", "unknown")
                    pipeline_result["items"].append(item)

        pipeline_result["stages"]["vlm"] = vlm_results
        pipeline_result["model"] = "ostrakon-vl-8b-iq4xs"
    else:
        pipeline_result["stages"]["vlm"] = {"status": "skipped", "reason": "no_low_confidence_rois"}

    # Aggregate from CLIP high-confidence results
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


def main():
    parser = argparse.ArgumentParser(description="Hotpot Inference Pipeline")
    parser.add_argument("--frame", required=True, help="Input frame path")
    parser.add_argument("--output", default="-", help="Output path (- for stdout)")
    parser.add_argument("--skip-vlm", action="store_true", help="Skip VLM stage")
    parser.add_argument("--hub", help="Hub URL for result posting (optional)")
    args = parser.parse_args()

    t0 = time.time()
    result = run_pipeline(args.frame, args.skip_vlm)
    result["total_ms"] = round((time.time() - t0) * 1000, 1)

    output = json.dumps(result, ensure_ascii=False, indent=2)

    if args.output == "-":
        print(output)
    else:
        Path(args.output).write_text(output)
        print(f"Saved to {args.output}")

    # Optional: post to Hub
    if args.hub:
        post_result = post_to_hub(result, args.hub)
        print(f"Hub: {json.dumps(post_result, ensure_ascii=False)}")

    if result["status"] == "error":
        sys.exit(1)


if __name__ == "__main__":
    main()
