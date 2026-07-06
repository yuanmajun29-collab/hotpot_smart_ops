#!/usr/bin/env python3
"""Edge inference server — real YOLO + annotated image API."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

import cv2
from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from edge.detector.real_yolo import RealYoloDetector

OUTPUT_DIR = PROJECT_ROOT / "demo" / "data" / "edge_output"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="Hotpot Edge Inference", version="1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

detector: RealYoloDetector | None = None
INFERENCE_LOG: List[Dict[str, Any]] = []
MAX_LOG = 50


@app.on_event("startup")
def startup():
    global detector
    print(f"[EdgeInference] Real YOLO detector ready. Output: {OUTPUT_DIR}")
    detector = RealYoloDetector(conf=0.2)


@app.get("/health")
def health():
    return {"status": "ok", "detector": "yolov8n", "backend": "real"}


@app.get("/api/infer")
def infer(
    zone: str = Query("kitchen"),
    image: str = Query("real_kitchen.jpg"),
):
    image_path = PROJECT_ROOT / "demo" / "data" / image
    if not image_path.exists():
        return JSONResponse({"error": f"Image not found: {image_path}"}, status_code=404)

    img = cv2.imread(str(image_path))
    if img is None:
        return JSONResponse({"error": f"Failed to read: {image_path}"}, status_code=400)

    t_start = time.perf_counter()
    annotated, result = detector.annotate_and_save(img, zone)

    out_name = f"{zone}_{image}"
    out_path = OUTPUT_DIR / out_name
    cv2.imwrite(str(out_path), annotated)

    result_json = OUTPUT_DIR / f"{zone}_{Path(image).stem}.json"
    result_json.write_text(json.dumps(result, ensure_ascii=False, indent=2))

    total_ms = (time.perf_counter() - t_start) * 1000
    result["total_ms"] = round(total_ms, 1)
    result["annotated_url"] = f"/output/{out_name}"
    result["image"] = image

    INFERENCE_LOG.insert(0, {
        "timestamp": time.strftime("%H:%M:%S"),
        "zone": zone,
        "image": image,
        "detections": result["total_detections"],
        "inference_ms": result["inference_ms"],
    })
    if len(INFERENCE_LOG) > MAX_LOG:
        INFERENCE_LOG.pop()

    return result


@app.get("/api/infer/all")
def infer_all():
    demo_dir = PROJECT_ROOT / "demo" / "data"
    images = [p for p in list(demo_dir.glob("*.jpg")) + list(demo_dir.glob("*.jpeg"))
              if not p.name.startswith(".")]

    results = []
    for img_path in images:
        zone = "kitchen" if "kitchen" in img_path.name.lower() else "front"
        img = cv2.imread(str(img_path))
        if img is None:
            continue
        annotated, result = detector.annotate_and_save(img, zone)
        out_name = f"{zone}_{img_path.name}"
        cv2.imwrite(str(OUTPUT_DIR / out_name), annotated)
        (OUTPUT_DIR / f"{zone}_{img_path.stem}.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2))
        result["annotated_url"] = f"/output/{out_name}"
        result["image"] = img_path.name
        results.append(result)

    return {"total_images": len(results), "results": results}


@app.get("/api/log")
def inference_log(limit: int = Query(20, ge=1, le=100)):
    return {"count": len(INFERENCE_LOG), "entries": INFERENCE_LOG[:limit]}


app.mount("/output", StaticFiles(directory=str(OUTPUT_DIR)), name="output")


def main():
    parser = argparse.ArgumentParser(description="Edge Inference Server")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8090)
    args = parser.parse_args()
    import uvicorn
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
