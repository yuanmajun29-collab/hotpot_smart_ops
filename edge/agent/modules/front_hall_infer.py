"""前厅 YOLO 推理模块 — 实时检测 + 标注图

移自 edge/front_hall/server.py。通过 _active 标志由 server.py 按 zone 激活。
"""

from __future__ import annotations

import base64
import importlib.util
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import cv2
import numpy as np
from fastapi import APIRouter, File, Query, UploadFile
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from edge.agent.config import PROJECT_ROOT, OUTPUT_DIR

router = APIRouter(tags=["front-hall"])

# 由 server.py 在配置驱动下设置
_active = False
_detector = None

INFERENCE_LOG: List[Dict[str, Any]] = []
MAX_LOG = 50

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def _check_active():
    if not _active:
        return JSONResponse(
            {"error": "front-hall 模块未激活（配置中无 front_hall zone）"},
            status_code=503,
        )


def _get_detector():
    global _detector
    if _detector is None:
        if str(PROJECT_ROOT) not in sys.path:
            sys.path.append(str(PROJECT_ROOT))  # 放末尾避免遮蔽 stdlib platform
        from edge.common.detector.real_yolo import RealYoloDetector
        _detector = RealYoloDetector(conf=0.2)
    return _detector


@router.get("/health/front-hall")
def front_hall_health():
    return {
        "module": "front-hall",
        "active": _active,
        "detector": "yolov8n",
        "backend": "real",
    }


@router.get("/api/infer")
def infer(
    zone: str = Query("front"),
    image: str = Query("real_kitchen.jpg"),
):
    if not _active:
        return JSONResponse(
            {"error": "front-hall 模块未激活"}, status_code=503
        )

    detector = _get_detector()

    image_path = PROJECT_ROOT / "demo" / "data" / image
    if not image_path.exists():
        return JSONResponse(
            {"error": f"Image not found: {image_path}"}, status_code=404
        )

    img = cv2.imread(str(image_path))
    if img is None:
        return JSONResponse(
            {"error": f"Failed to read: {image_path}"}, status_code=400
        )

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

    INFERENCE_LOG.insert(
        0,
        {
            "timestamp": time.strftime("%H:%M:%S"),
            "zone": zone,
            "image": image,
            "detections": result["total_detections"],
            "inference_ms": result["inference_ms"],
        },
    )
    if len(INFERENCE_LOG) > MAX_LOG:
        INFERENCE_LOG.pop()

    return result


@router.get("/api/infer/all")
def infer_all():
    if not _active:
        return JSONResponse(
            {"error": "front-hall 模块未激活"}, status_code=503
        )

    detector = _get_detector()

    demo_dir = PROJECT_ROOT / "demo" / "data"
    images = [
        p
        for p in list(demo_dir.glob("*.jpg")) + list(demo_dir.glob("*.jpeg"))
        if not p.name.startswith(".")
    ]

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
            json.dumps(result, ensure_ascii=False, indent=2)
        )
        result["annotated_url"] = f"/output/{out_name}"
        result["image"] = img_path.name
        results.append(result)

    return {"total_images": len(results), "results": results}


@router.get("/api/log")
def inference_log(limit: int = Query(20, ge=1, le=100)):
    return {"count": len(INFERENCE_LOG), "entries": INFERENCE_LOG[:limit]}


# ── 每桌场景分析 (YOLO + CLIP 双模式) ──

import tempfile

_scene_analyzers: Dict[str, Any] = {}

def _get_scene_analyzer(mode: str = "plan_b"):
    """获取场景分析器实例（按 mode 缓存，plan_b 默认）。"""
    if mode not in _scene_analyzers:
        module_path = str(
            PROJECT_ROOT / "edge" / "front_hall" / "inference" / "scene_analyzer.py"
        )
        spec = importlib.util.spec_from_file_location(
            f"hotpot_scene_analyzer_{mode}", module_path
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _scene_analyzers[mode] = module.SceneAnalyzer(mode=mode)
    return _scene_analyzers[mode]

def _save_temp_image(img: np.ndarray) -> str:
    """将 numpy 图片写入临时文件，返回路径（供 CLIP 子进程读取）"""
    fd, path = tempfile.mkstemp(suffix=".jpg", prefix="hotpot_scene_")
    os.close(fd)
    cv2.imwrite(path, img)
    return path


def _decode_image(data_b64: str) -> np.ndarray:
    """Base64 → BGR numpy 图片。"""
    if data_b64.startswith("data:image"):
        # data:image/jpeg;base64,xxxx
        data_b64 = data_b64.split(",", 1)[1]
    raw = base64.b64decode(data_b64)
    arr = np.frombuffer(raw, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("无法解码图片")
    return img


@router.post("/api/scene/analyze")
async def scene_analyze(
    table_id: str = Query("", description="桌号，如 T12"),
    mode: str = Query("plan_b", description="plan_b(YOLO规则) 或 plan_a(YOLO+CLIP)"),
    image_base64: Optional[str] = Query(None, description="Base64 编码的图片"),
    image_file: Optional[UploadFile] = File(None),
):
    """单张图片场景分析 — YOLO 检测 + 可选 CLIP 语义分类。

    模式：
    - plan_b（默认）: 纯 YOLO 规则推断，40ms，无外部依赖
    - plan_a: YOLO 硬判决 + CLIP 语义，有人时 ~190ms，无人时 40ms

    两种传图方式（二选一）：
    - image_base64: base64 编码的图片（适合 API 调用）
    - image_file: multipart 文件上传（适合 Swagger 调试）
    """
    if not _active:
        return JSONResponse(
            {"error": "front-hall 模块未激活"}, status_code=503
        )

    if mode not in ("plan_a", "plan_b"):
        return JSONResponse(
            {"error": f"不支持的模式: {mode}，可选 plan_a / plan_b"}, status_code=400
        )

    # 获取图片 + 文件路径（plan_a 需要传文件路径给 CLIP 子进程）
    image_path = ""
    img = None
    try:
        if image_file is not None:
            contents = await image_file.read()
            arr = np.frombuffer(contents, dtype=np.uint8)
            img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
            if img is None:
                return JSONResponse({"error": "无法解码上传文件"}, status_code=400)
        elif image_base64 is not None:
            img = _decode_image(image_base64)
        else:
            # 默认用 demo 图片
            demo_path = PROJECT_ROOT / "demo" / "data" / "front_hall.jpg"
            if not demo_path.exists():
                return JSONResponse(
                    {"error": "请提供 image_base64 或 image_file", "hint": "也支持 multipart upload"},
                    status_code=400,
                )
            img = cv2.imread(str(demo_path))
            image_path = str(demo_path)
            if img is None:
                return JSONResponse({"error": f"无法读取默认图片 {demo_path}"}, status_code=400)

        # plan_a 需要文件路径（非文件来源的图片写临时文件）
        if mode == "plan_a" and not image_path and img is not None:
            image_path = _save_temp_image(img)

    except Exception as e:
        return JSONResponse({"error": f"图片解码失败: {e}"}, status_code=400)

    # 分析
    try:
        analyzer = _get_scene_analyzer(mode)
        result = analyzer.analyze_table(img, table_id=table_id, image_path=image_path)
        return result
    except Exception as e:
        return JSONResponse({"error": f"场景分析失败: {e}"}, status_code=500)


@router.get("/api/scene/batch")
def scene_batch(
    table_prefix: str = Query("T", description="桌号前缀"),
    mode: str = Query("plan_b", description="plan_b(YOLO规则) 或 plan_a(YOLO+CLIP)"),
):
    """批量分析 demo/data 下所有图片，返回每桌场景分析结果。"""
    if not _active:
        return JSONResponse(
            {"error": "front-hall 模块未激活"}, status_code=503
        )

    analyzer = _get_scene_analyzer(mode)

    demo_dir = PROJECT_ROOT / "demo" / "data"
    extensions = ("*.jpg", "*.jpeg", "*.png")
    images: List[Path] = []
    for ext in extensions:
        images.extend(p for p in demo_dir.glob(ext) if not p.name.startswith("."))

    if not images:
        return {"total_tables": 0, "results": [], "note": "demo/data 目录无图片"}

    results = []
    for idx, img_path in enumerate(images):
        img = cv2.imread(str(img_path))
        if img is None:
            continue
        tid = f"{table_prefix}{idx + 1:02d}"
        try:
            r = analyzer.analyze_table(img, table_id=tid, image_path=str(img_path))
            r["source_image"] = img_path.name
            results.append(r)
        except Exception as e:
            results.append({
                "table_id": tid,
                "error": str(e),
                "source_image": img_path.name,
            })

    return {
        "total_tables": len(results),
        "results": results,
    }


# ── 静态文件挂载 ──
def mount_static(app):
    app.mount("/output", StaticFiles(directory=str(OUTPUT_DIR)), name="output")
