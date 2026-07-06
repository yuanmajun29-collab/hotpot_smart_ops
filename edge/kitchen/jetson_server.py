"""后厨推理 API — YOLO (ultralytics) + VLM (Ostrakon-VL) 三级过滤

Jetson Orin Docker · 替换旧版 VLM-only
管道：图片 → YOLO (ultralytics, ~50ms) → 可疑帧? → VLM → Hub
"""
import json, os, sys, time, subprocess
from pathlib import Path

import cv2, httpx
import numpy as np
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

# ── 路径 ──
LLAMA_CLI  = os.environ.get("LLAMA_CLI",  "/opt/hotpot-infer/bin/llama-mtmd-cli")
MODEL_PATH = os.environ.get("LLAMA_MODEL", "/models/ostrakon-vl-8b/Ostrakon-VL-8B.IQ4_XS.gguf")
MMPROJ     = os.environ.get("LLAMA_MMPROJ", "/models/ostrakon-vl-8b/Ostrakon-VL-8B.mmproj-Q8_0.gguf")
YOLO_MODEL = os.environ.get("YOLO_MODEL", "/models/yolo26l.pt")
HUB_URL    = os.environ.get("HOTPOT_HUB_URL", "http://192.168.2.85:8098")
STORE_ID   = os.environ.get("HOTPOT_STORE_ID", "store_yuhuan")
ZONE       = os.environ.get("HOTPOT_ZONE", "kitchen")
IMAGES_DIR = Path(os.environ.get("HOTPOT_IMAGES_DIR", "/images"))

app = FastAPI(title="hotpot-kitchen-yolo-vlm")

# ── YOLO 懒加载 (ultralytics) ──
_detector = None

def _get_yolo():
    global _detector
    if _detector is None:
        from ultralytics import YOLO
        _detector = YOLO(YOLO_MODEL)
    return _detector

# ── VLM prompt ──
PROMPT = (
    '你是一个后厨废弃物识别系统。请严格分析这张后厨图片，找出所有废弃的食材或餐余，'
    '输出 JSON：{"items": [{"waste_type": "边角料|备餐废弃|过期临界|餐后剩余", '
    '"sku": "食材名称", "estimated_portion": 0.8, "unit": "份", '
    '"confidence": 0.85, "reason": "判断依据"}]}。'
    '如果没有发现明显的废料，返回 {"items": []}。'
    '只输出 JSON，不要其他文字。'
)

# ── 厨房可疑检测 ──
def _is_suspicious(detections):
    if not detections:
        return False, "no-objects"
    persons = sum(1 for d in detections if d.get("cls") == 0 and d.get("conf",0) >= 0.4)
    bowls   = sum(1 for d in detections if d.get("cls") == 45 and d.get("conf",0) >= 0.3)
    bottles = sum(1 for d in detections if d.get("cls") in (39,41) and d.get("conf",0) >= 0.3)
    foods   = sum(1 for d in detections if d.get("cls") in range(47,56) and d.get("conf",0) >= 0.3)
    if persons >= 1 and (bowls + bottles) >= 3:
        return True, f"staff+tableware: {persons}p/{bowls}b/{bottles}bt"
    if bowls >= 5 or bottles >= 4:
        return True, f"high-tableware: {bowls}b/{bottles}bt"
    if foods >= 2:
        return True, f"food: {foods}"
    if persons >= 2 and (bowls + bottles) >= 1:
        return True, f"staff: {persons}p"
    return False, f"normal: {persons}p/{bowls}b/{bottles}bt/{foods}f"

class InferRequest(BaseModel):
    image_path: str

@app.get("/health")
def health():
    return {
        "status": "ok", "service": "kitchen-yolo-vlm",
        "pipeline": "yolo+vlm",
        "model": os.path.basename(MODEL_PATH),
        "yolo_model": YOLO_MODEL,
        "vlm_cli": os.path.exists(LLAMA_CLI),
        "hub": HUB_URL,
    }

@app.post("/infer")
def infer(req: InferRequest):
    t0 = time.perf_counter()
    img_path = Path(req.image_path)
    if not img_path.is_absolute():
        img_path = IMAGES_DIR / img_path
    if not img_path.exists():
        raise HTTPException(404, f"图片不存在: {img_path}")

    img = cv2.imread(str(img_path))
    if img is None:
        raise HTTPException(400, "无法读取图片")

    # ── 1. YOLO ──
    yolo_t0 = time.perf_counter()
    results = _get_yolo()(img, conf=0.25, iou=0.45, verbose=False)
    yolo_ms = (time.perf_counter() - yolo_t0) * 1000

    detections = []
    if results and results[0].boxes is not None:
        boxes = results[0].boxes
        for i in range(len(boxes)):
            x1,y1,x2,y2 = boxes.xyxy[i].tolist()
            detections.append({
                "cls": int(boxes.cls[i]),
                "conf": round(float(boxes.conf[i]), 3),
                "bbox": [int(x1),int(y1),int(x2),int(y2)],
                "label": results[0].names.get(int(boxes.cls[i]), "?"),
            })

    # ── 2. 可疑判断 ──
    suspicious, reason = _is_suspicious(detections)

    # ── 3. VLM ──
    items = []
    vlm_used = False
    vlm_ms = 0.0
    if suspicious:
        vlm_t0 = time.perf_counter()
        try:
            cmd = [LLAMA_CLI, "-m", MODEL_PATH, "--mmproj", MMPROJ,
                   "--image", str(img_path), "--image-min-tokens", "1024",
                   "-p", PROMPT, "--temp", "0.1", "-n", "512"]
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            out = proc.stdout
            try:
                brace = out.index("{")
                data = json.loads(out[brace:])
                items = data.get("items", [])
            except (ValueError, json.JSONDecodeError):
                pass
        except Exception:
            pass
        vlm_ms = (time.perf_counter() - vlm_t0) * 1000
        vlm_used = True

    # ── 4. 推 Hub ──
    pushed = False
    if items:
        try:
            httpx.post(f"{HUB_URL}/v1/vlm/waste-estimate", json={
                "store_id": STORE_ID, "zone": ZONE,
                "source": "jetson-orin-kitchen",
                "model": "Ostrakon-VL-8B.IQ4_XS",
                "pipeline": "yolo+vlm",
                "yolo_ms": round(yolo_ms,1),
                "vlm_ms": round(vlm_ms,1) if vlm_used else None,
                "items": items,
            }, headers={"X-Api-Key": "test-key"}, timeout=10)
            pushed = True
        except Exception:
            pass

    total_ms = (time.perf_counter() - t0) * 1000
    return {
        "ok": True,
        "pipeline": "yolo+vlm" if vlm_used else "yolo-only",
        "image": str(img_path),
        "yolo": {
            "detections": len(detections),
            "objects": detections,
            "ms": round(yolo_ms, 1),
        },
        "vlm": {
            "triggered": suspicious,
            "used": vlm_used,
            "reason": reason,
            "ms": round(vlm_ms, 1) if vlm_used else None,
            "items": items,
        },
        "total_ms": round(total_ms, 1),
        "pushed_to_hub": pushed,
    }
