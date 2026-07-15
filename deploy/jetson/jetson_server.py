"""后厨推理 API — YOLO (ultralytics) + VLM (Ostrakon-VL) 三级过滤

Jetson Orin Docker · llama-server 常驻模型（CPU/GPU 自适应）
管道：图片 → YOLO (~50ms) → 图片压缩(640px) → 规则判断 → VLM → Hub

环境变量：
  LLAMA_NGL           GPU 层数，0=纯CPU，999=全部GPU（默认 0，安全起见）
  LLAMA_BIN           llama-server 路径（默认 /opt/hotpot-infer/bin/llama-server）
  VLM_IMAGE_MAX_SIZE  图片压缩最大边长 px（默认 640）
  VLM_MAX_TOKENS      最大生成 token（默认 256）
  VLM_TIMEOUT         VLM 超时秒数（默认 300）
"""

import base64, json, os, subprocess, time
from pathlib import Path

import cv2, httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from edge.kitchen.inference.defect_measurement import (
    DEFAULT_THRESHOLDS,
    decide_action,
    estimate_bbox_size_mm,
    measure_defect,
    pixels_to_mm,
)

# ── 配置 ──
LLAMA_SERVER      = os.environ.get("LLAMA_SERVER", "http://localhost:8080")
LLAMA_BIN         = os.environ.get("LLAMA_BIN", "/opt/hotpot-infer/bin/llama-server")
LLAMA_NGL         = int(os.environ.get("LLAMA_NGL", "0"))       # GPU 层数，0=纯CPU
LLAMA_MODEL       = os.environ.get("LLAMA_MODEL", "/models/ostrakon-vl-8b/Ostrakon-VL-8B.IQ4_XS.gguf")
LLAMA_MMPROJ      = os.environ.get("LLAMA_MMPROJ", "/models/ostrakon-vl-8b/Ostrakon-VL-8B.mmproj-Q8_0.gguf")
YOLO_MODEL        = os.environ.get("YOLO_MODEL", "/models/yolo26l.pt")
HUB_URL           = os.environ.get("HOTPOT_HUB_URL", "http://192.168.2.85:8098")
STORE_ID          = os.environ.get("HOTPOT_STORE_ID", "store_yuhuan")
ZONE              = os.environ.get("HOTPOT_ZONE", "kitchen")
IMAGES_DIR        = Path(os.environ.get("HOTPOT_IMAGES_DIR", "/images"))
VLM_IMAGE_MAX_SIZE = int(os.environ.get("VLM_IMAGE_MAX_SIZE", "640"))
VLM_MAX_TOKENS    = int(os.environ.get("VLM_MAX_TOKENS", "256"))
VLM_TIMEOUT       = int(os.environ.get("VLM_TIMEOUT", "300"))

BACKEND = "cuda" if LLAMA_NGL > 0 else "cpu"

app = FastAPI(title="hotpot-kitchen-yolo-vlm")

# ── 启动时拉起 llama-server ──
@app.on_event("startup")
def _start_llama_server():
    cmd = [
        LLAMA_BIN,
        "-m", LLAMA_MODEL,
        "--mmproj", LLAMA_MMPROJ,
        "--host", "127.0.0.1",
        "--port", "8080",
        "--no-webui",
    ]
    if LLAMA_NGL > 0:
        cmd.extend(["-ngl", str(LLAMA_NGL)])
    subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    print(f"[startup] llama-server ({BACKEND} ngl={LLAMA_NGL}): {' '.join(cmd)}")

# ── YOLO 懒加载 ──
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

# ── 厨房可疑检测规则 ──
# COCO class IDs: 0=person, 39=bottle, 41=cup, 45=bowl, 47-55=foods
def _defect_calib_mm_per_px() -> float:
    try:
        calib = float(os.environ.get("DEFECT_CALIB_MM_PER_PX", "0.05"))
    except ValueError:
        calib = 0.05
    return calib if calib > 0 else 0.05


def _defect_thresholds() -> dict:
    raw = os.environ.get("DEFECT_THRESHOLD_MM", "")
    thresholds = dict(DEFAULT_THRESHOLDS)
    if not raw:
        return thresholds

    try:
        parts = [float(part.strip()) for part in raw.split(",") if part.strip()]
    except ValueError:
        return thresholds

    if len(parts) >= 2:
        thresholds["warn_manual"] = parts[0]
        thresholds["auto_reject"] = parts[1]
    elif len(parts) == 1:
        thresholds["auto_reject"] = parts[0]
    return thresholds


def _clip_bbox(bbox, width: int, height: int) -> list[int]:
    x1, y1, x2, y2 = map(int, bbox)
    return [
        max(0, min(width, x1)),
        max(0, min(height, y1)),
        max(0, min(width, x2)),
        max(0, min(height, y2)),
    ]


def _add_defect_measurements(detections, image):
    calib = _defect_calib_mm_per_px()
    thresholds = _defect_thresholds()

    for detection in detections:
        size_mm = 0.0
        source = "unmeasured"
        bbox = detection.get("bbox", [0, 0, 0, 0])

        if image is not None:
            height, width = image.shape[:2]
            x1, y1, x2, y2 = _clip_bbox(bbox, width, height)
            if x2 > x1 and y2 > y1:
                measurement = measure_defect(image[y1:y2, x1:x2])
                if measurement:
                    size_mm = pixels_to_mm(measurement["diameter_px"], calib)
                    source = "contour"

        if source == "unmeasured":
            size_mm = estimate_bbox_size_mm(bbox, calib)
            source = "bbox_area_estimate"

        detection["defect_size_mm"] = round(size_mm, 3)
        detection["action"] = decide_action(size_mm, thresholds)
        detection["measurement_source"] = source


def _is_suspicious(detections, image=None):
    _add_defect_measurements(detections, image)

    if not detections:
        return False, "no-objects"
    persons = sum(1 for d in detections if d["cls"] == 0 and d["conf"] >= 0.4)
    bowls   = sum(1 for d in detections if d["cls"] == 45 and d["conf"] >= 0.3)
    bottles = sum(1 for d in detections if d["cls"] in (39, 41) and d["conf"] >= 0.3)
    foods   = sum(1 for d in detections if d["cls"] in range(47, 56) and d["conf"] >= 0.3)

    if persons >= 1 and (bowls + bottles) >= 3:
        return True, f"staff+tableware:{persons}p/{bowls}b/{bottles}bt"
    if bowls >= 5 or bottles >= 4:
        return True, f"high-tableware:{bowls}b/{bottles}bt"
    if foods >= 2:
        return True, f"food:{foods}"
    if persons >= 2 and (bowls + bottles) >= 1:
        return True, f"staff:{persons}p"
    return False, f"normal:{persons}p/{bowls}b/{bottles}bt/{foods}f"

# ── 图片预处理 ──
def _prep_image(image_path: str, max_size: int = 0) -> bytes:
    """压缩图片到 max_size px 以内，返回 JPEG bytes。大幅减少 VLM 编码耗时。"""
    if max_size <= 0:
        max_size = VLM_IMAGE_MAX_SIZE
    img = cv2.imread(image_path)
    if img is None:
        with open(image_path, "rb") as f:
            return f.read()
    h, w = img.shape[:2]
    scale = min(max_size / max(h, w), 1.0)
    if scale < 1.0:
        new_w, new_h = int(w * scale), int(h * scale)
        img = cv2.resize(img, (new_w, new_h), interpolation=cv2.INTER_AREA)
    _, jpg = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 75])
    return jpg.tobytes()

# ── VLM 调用 ──
def _call_vlm(image_path: str) -> dict:
    """通过 llama-server OpenAI-compatible API 调用 VLM。"""
    img_bytes = _prep_image(image_path)
    img_b64 = base64.b64encode(img_bytes).decode()

    payload = {
        "messages": [{
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}},
                {"type": "text", "text": PROMPT},
            ]
        }],
        "temperature": 0.1,
        "max_tokens": VLM_MAX_TOKENS,
        "stream": False,
    }

    resp = httpx.post(
        f"{LLAMA_SERVER}/v1/chat/completions",
        json=payload,
        timeout=VLM_TIMEOUT,
    )
    resp.raise_for_status()
    data = resp.json()

    raw = data["choices"][0]["message"]["content"]
    items = []
    error = ""
    try:
        brace = raw.index("{")
        items = json.loads(raw[brace:]).get("items", [])
    except (ValueError, json.JSONDecodeError) as e:
        error = str(e)

    return {"items": items, "raw": raw[:500], "error": error}


# ── API ──

class InferRequest(BaseModel):
    image_path: str

@app.get("/health")
def health():
    return {
        "status": "ok",
        "service": "kitchen-yolo-vlm",
        "backend": BACKEND,
        "ngl": LLAMA_NGL,
        "llama_server": LLAMA_SERVER,
        "yolo_model": YOLO_MODEL,
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

    # 1. YOLO 检测
    yolo_t0 = time.perf_counter()
    results = _get_yolo()(img, conf=0.25, iou=0.45, verbose=False)
    yolo_ms = (time.perf_counter() - yolo_t0) * 1000

    detections = []
    if results and results[0].boxes is not None:
        boxes = results[0].boxes
        names = results[0].names
        for i in range(len(boxes)):
            x1, y1, x2, y2 = boxes.xyxy[i].tolist()
            detections.append({
                "cls": int(boxes.cls[i]),
                "conf": round(float(boxes.conf[i]), 3),
                "bbox": [int(x1), int(y1), int(x2), int(y2)],
                "label": names.get(int(boxes.cls[i]), "?"),
            })

    # 2. 规则判断
    suspicious, reason = _is_suspicious(detections, img)

    # 3. VLM (仅可疑帧)
    items = []
    vlm_used = False
    vlm_ms = 0.0
    vlm_raw = ""
    vlm_error = ""
    if suspicious:
        vlm_t0 = time.perf_counter()
        try:
            result = _call_vlm(str(img_path))
            items = result["items"]
            vlm_raw = result["raw"]
            vlm_error = result["error"]
        except Exception as e:
            vlm_error = str(e)
        vlm_ms = (time.perf_counter() - vlm_t0) * 1000
        vlm_used = True

    # 4. 推 Hub
    pushed = False
    if items:
        try:
            httpx.post(
                f"{HUB_URL}/v1/vlm/waste-estimate",
                json={
                    "store_id": STORE_ID,
                    "zone": ZONE,
                    "source": "jetson-orin-kitchen",
                    "model": "Ostrakon-VL-8B.IQ4_XS",
                    "backend": BACKEND,
                    "pipeline": f"yolo+{BACKEND}-vlm",
                    "yolo_ms": round(yolo_ms, 1),
                    "vlm_ms": round(vlm_ms, 1) if vlm_used else None,
                    "items": items,
                },
                headers={"X-Api-Key": "test-key"},
                timeout=10,
            )
            pushed = True
        except Exception:
            pass

    total_ms = (time.perf_counter() - t0) * 1000
    return {
        "ok": True,
        "pipeline": f"yolo+{BACKEND}-vlm" if vlm_used else "yolo-only",
        "backend": BACKEND,
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
            "raw": vlm_raw,
            "error": vlm_error,
        },
        "total_ms": round(total_ms, 1),
        "pushed_to_hub": pushed,
    }
