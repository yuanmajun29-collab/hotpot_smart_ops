"""后厨推理模块 — YOLO 预过滤 + VLM 废弃物识别 (ADR-014 三级过滤)

管道：
  YOLO (8ms) → "有可疑物体?" ──yes──→ VLM (320ms) → Hub
                              ──no───→ 跳过 VLM，返回 YOLO 结果

YOLO 预过滤规则：
  - 检测到 food/bowl/bottle + 人员操作 → 触发 VLM
  - 仅人员/设备/椅子 → 正常后厨场景，跳过 VLM
  - 餐具类 (knife/spoon/fork) + 食材 → 备餐活动，触发 VLM

环境变量：
  HOTPOT_KITCHEN_VLM_ENABLED=1   启用 VLM（默认）
  HOTPOT_KITCHEN_VLM_ENABLED=0   仅 YOLO 模式
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import cv2
import httpx
import numpy as np
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from edge.agent.config import (
    LLAMA_CLI, LLAMA_MODEL, LLAMA_MMPROJ, VLM_TIMEOUT,
    HUB_URL, STORE_ID, API_KEY, PROJECT_ROOT, OUTPUT_DIR,
)

router = APIRouter(prefix="/infer", tags=["kitchen"])

# 由 server.py 在配置驱动下设置
_active = False
_zone = "kitchen"

# ── YOLO 检测器（懒加载，复用 RealYoloDetector） ──
_yolo_detector = None

# ── VLM 开关 ──
VLM_ENABLED = os.environ.get("HOTPOT_KITCHEN_VLM_ENABLED", "1") == "1"

# ── 厨房可疑检测常量 ──
# COCO 类 ID 参考（与 RealYoloDetector.COCO_NAMES 对齐）
_FOOD_IDS = {46, 47, 48, 49, 50, 51, 52, 53, 54, 55}  # banana..cake
_CONTAINER_IDS = {39, 40, 41}     # bottle, wine glass, cup
_TABLEWARE_IDS = {44, 45}         # spoon, bowl
_UTENSIL_IDS = {42, 43}           # fork, knife
_APPLIANCE_IDS = {68, 69, 70, 71, 72}  # microwave, oven, toaster, sink, fridge
_PERSON_ID = 0

# 置信度阈值
_SUSPICIOUS_CONF = 0.25          # 最低检测置信度
_FOOD_TRIGGER_CONF = 0.30        # 食材类触发 VLM 的置信度

# 后厨 VLM prompt
VLM_PROMPT = (
    '你是后厨废弃物识别系统。分析图片中的废弃食材/餐余，输出严格JSON：'
    '{"items":[{"waste_type":"备餐废弃|边角料|过期临界|餐后剩余",'
    '"sku":"食材名","estimated_portion":0.8,"unit":"份",'
    '"confidence":0.82,"reason":"判断依据"}]}'
)

# ── VLM Mock 回退（开发机 / Mac 无 llama-mtmd-cli） ──
def _vlm_mock(detections: List[Dict[str, Any]], label_counts: Dict[str, int]) -> List[Dict[str, Any]]:
    """基于 YOLO 检测结果生成模拟的废料识别输出。

    策略：用 YOLO 检测到的物体类别反向推断可能的废料类型。
    当 llama-mtmd-cli 不可用时作为 mock 回退。
    """
    items: List[Dict[str, Any]] = []
    staff_count = label_counts.get("staff", 0)
    tableware_count = label_counts.get("tableware", 0)
    container_count = label_counts.get("container", 0)
    utensil_count = label_counts.get("utensil", 0)

    # 厨房废料 mock 模板
    waste_templates = [
        {
            "waste_type": "边角料",
            "sku": "牛肉切余料",
            "estimated_portion": 0.25,
            "unit": "份",
            "confidence": 0.88,
            "reason": "砧板区域检测到容器+刀具，推断备餐切割边角料",
        },
        {
            "waste_type": "餐后剩余",
            "sku": "锅底残渣",
            "estimated_portion": 0.40,
            "unit": "份",
            "confidence": 0.82,
            "reason": "多碗+瓶组合，推断餐后回收餐具带锅底残渣",
        },
        {
            "waste_type": "备餐废弃",
            "sku": "蔬菜叶梗",
            "estimated_portion": 0.15,
            "unit": "份",
            "confidence": 0.75,
            "reason": "碗类容器旁边角料，推断洗切蔬菜残余",
        },
        {
            "waste_type": "过期临界",
            "sku": "豆腐",
            "estimated_portion": 0.30,
            "unit": "份",
            "confidence": 0.70,
            "reason": "容器+人员频繁操作，推断临期食材周转",
        },
    ]

    # 根据检测结果筛选相关废料项
    if staff_count >= 1:
        items.append(waste_templates[0])  # 有人在 → 边角料

    if tableware_count >= 3 or container_count >= 3:
        items.append(waste_templates[1])  # 多餐具 → 餐后剩余

    if tableware_count >= 2 and container_count >= 1:
        items.append(waste_templates[2])  # 碗+瓶 → 备餐废弃

    if staff_count >= 2 and container_count >= 3:
        items.append(waste_templates[3])  # 多人+多容器 → 过期临界

    # 至少返回 1 项
    if not items:
        items.append({
            "waste_type": "备餐废弃",
            "sku": "微量残余",
            "estimated_portion": 0.05,
            "unit": "份",
            "confidence": 0.60,
            "reason": "厨房区域有人/物活动但未检测到明显废料堆积",
        })

    return items


def _run_vlm(image_path: Path, detections: List[Dict[str, Any]], label_counts: Dict[str, int]) -> Tuple[List[Dict[str, Any]], str, float]:
    """执行 VLM 推理（真实 CLI 或 mock 回退）。

    Returns:
        (items, source_label, inference_ms)
    """
    vlm_t0 = time.perf_counter()
    items: List[Dict[str, Any]] = []
    source_label = "mock"

    # 优先尝试真实 VLM CLI
    if Path(LLAMA_CLI).exists() and Path(LLAMA_MODEL).exists():
        try:
            cmd = [
                LLAMA_CLI, "-m", LLAMA_MODEL, "--mmproj", LLAMA_MMPROJ,
                "--image", str(image_path), "--image-min-tokens", "1024",
                "-p", VLM_PROMPT, "--temp", "0.1", "-n", "512",
            ]
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=VLM_TIMEOUT)
            out = proc.stdout
            try:
                brace = out.index("{")
                data = json.loads(out[brace:])
                items = data.get("items", [])
                if items:
                    source_label = "ostrakon-vl-8b"
            except (ValueError, json.JSONDecodeError):
                pass
        except (subprocess.TimeoutExpired, FileNotFoundError, Exception):
            pass

    # VLM CLI 不可用或无结果 → mock 回退
    if not items:
        items = _vlm_mock(detections, label_counts)

    vlm_ms = (time.perf_counter() - vlm_t0) * 1000
    return items, source_label, vlm_ms


# ── 推理缓存（简单帧差检测用） ──
_last_yolo_frame: Optional[Dict[str, Any]] = None
_last_frame_time: float = 0.0
FRAME_CACHE_TTL = 5.0  # 5 秒内相同检测结果不重复触发 VLM


class InferRequest(BaseModel):
    image_path: str


def _check_active():
    if not _active:
        raise HTTPException(503, "kitchen 模块未激活（配置中无 kitchen zone）")


def _get_yolo():
    """懒加载 YOLO 检测器，与 front-hall 复用同一 RealYoloDetector。"""
    global _yolo_detector
    if _yolo_detector is None:
        if str(PROJECT_ROOT) not in sys.path:
            sys.path.append(str(PROJECT_ROOT))
        from edge.common.detector.real_yolo import RealYoloDetector, COCO_NAMES
        _yolo_detector = RealYoloDetector(conf=_SUSPICIOUS_CONF)
    return _yolo_detector


def _should_trigger_vlm(
    detections: List[Dict[str, Any]],
    label_counts: Dict[str, int],
) -> Tuple[bool, str]:
    """判断当前帧是否需要触发 VLM 做废料语义分析。

    规则：
    1. 食材类 (food) + 人员 → 有人在处理食材 → 触发
    2. 食材类 + 容器/餐具 → 备餐/餐后场景 → 触发
    3. 仅有人员 + 设备 → 正常工作场景 → 跳过
    4. 无检测或只有设备 → 跳过
    5. 帧差过大（与上一帧显著不同）→ 触发

    Returns:
        (should_trigger, reason)
    """
    has_person = label_counts.get("staff", 0) > 0 or label_counts.get("customer", 0) > 0

    # 收集各类对象
    food_count = sum(
        1 for d in detections
        if d.get("class_id") in _FOOD_IDS and d.get("confidence", 0) >= _FOOD_TRIGGER_CONF
    )
    container_count = sum(
        1 for d in detections
        if d.get("class_id") in _CONTAINER_IDS and d.get("confidence", 0) >= _SUSPICIOUS_CONF
    )
    tableware_count = sum(
        1 for d in detections
        if d.get("class_id") in _TABLEWARE_IDS and d.get("confidence", 0) >= _SUSPICIOUS_CONF
    )
    utensil_count = sum(
        1 for d in detections
        if d.get("class_id") in _UTENSIL_IDS and d.get("confidence", 0) >= _SUSPICIOUS_CONF
    )

    # 规则 1: 食材 + 人员
    if food_count >= 1 and has_person:
        return True, f"food+person: {food_count} foods, staff present"

    # 规则 2: 食材 + 容器/餐具
    if food_count >= 2 and (container_count + tableware_count) >= 2:
        return True, f"food+tableware: {food_count} foods, {container_count + tableware_count} containers/tableware"

    # 规则 3: 人员 + 餐具（备餐活动）
    if has_person and utensil_count >= 1 and (food_count >= 1 or container_count >= 2):
        return True, f"prep-activity: staff + {utensil_count} utensils + {food_count} foods"

    # 规则 4: 大量容器/餐具变化（可能刚结束用餐）
    if container_count >= 4 or tableware_count >= 5:
        return True, f"high-tableware: {container_count + tableware_count} items"

    # 规则 5: 帧差检测
    global _last_yolo_frame, _last_frame_time
    now = time.time()
    if _last_yolo_frame and (now - _last_frame_time) < FRAME_CACHE_TTL:
        prev_counts = _last_yolo_frame.get("label_counts", {})
        # 检测数变化超过 30% 且至少差 3 个
        prev_total = _last_yolo_frame.get("total_detections", 0)
        curr_total = len(detections)
        if prev_total > 0 and abs(curr_total - prev_total) >= 3:
            change_pct = abs(curr_total - prev_total) / prev_total
            if change_pct > 0.3:
                return True, f"frame-delta: {prev_total}→{curr_total} ({change_pct:.0%})"

    # 默认：正常场景，跳过 VLM
    return False, (
        f"normal-kitchen: {food_count}f/{container_count}c/{tableware_count}tw/"
        f"{'staff' if has_person else 'no-person'}"
    )


# ══════════════════════════════════════════════════════════════════════
# API 端点
# ══════════════════════════════════════════════════════════════════════

@router.get("/kitchen/health")
def kitchen_health():
    vlm_cli_ok = Path(LLAMA_CLI).exists()
    vlm_model_ok = Path(LLAMA_MODEL).exists()
    return {
        "module": "kitchen",
        "active": _active,
        "zone": _zone,
        "pipeline": "yolo+vlm" if VLM_ENABLED else "yolo-only",
        "yolo_loaded": _yolo_detector is not None,
        "vlm_enabled": VLM_ENABLED,
        "vlm_cli_exists": vlm_cli_ok,
        "vlm_model_exists": vlm_model_ok,
        "vlm_mode": "real" if (vlm_cli_ok and vlm_model_ok) else "mock",
        "vlm_model": Path(LLAMA_MODEL).name if LLAMA_MODEL else "N/A",
    }


@router.get("/kitchen/yolo")
def kitchen_yolo(
    image_path: str = Query(..., description="图片路径（相对或绝对）"),
    annotate: bool = Query(False, description="是否返回标注图 URL"),
):
    """YOLO-only 检测：不做 VLM，仅返回检测结果（8ms）。"""
    _check_active()

    img_path = Path(image_path)
    if not img_path.is_absolute():
        img_path = PROJECT_ROOT / img_path
    if not img_path.exists():
        raise HTTPException(404, f"图片不存在: {image_path}")

    img = cv2.imread(str(img_path))
    if img is None:
        raise HTTPException(400, f"无法读取图片: {image_path}")

    detector = _get_yolo()
    result = detector.detect(img, zone="kitchen")

    # 判断是否该触发 VLM
    should_vlm, vlm_reason = _should_trigger_vlm(
        result.get("detections", []),
        result.get("label_counts", {}),
    )

    # 缓存帧
    global _last_yolo_frame, _last_frame_time
    _last_yolo_frame = result
    _last_frame_time = time.time()

    response = {
        "ok": True,
        "mode": "yolo-only",
        "zone": "kitchen",
        "image": str(img_path),
        **result,
        "vlm_should_trigger": should_vlm,
        "vlm_reason": vlm_reason,
        "vlm_enabled": VLM_ENABLED,
    }

    # 可选标注图
    if annotate:
        out_name = f"kitchen_yolo_{img_path.stem}.jpg"
        out_path = OUTPUT_DIR / out_name
        annotated, _ = detector.annotate_and_save(img, zone="kitchen", save_path=out_path)
        response["annotated_url"] = f"/output/{out_name}"

    return response


@router.post("/kitchen")
def kitchen_infer(req: InferRequest):
    """后厨完整推理：YOLO 预过滤 → (可选) VLM 废料识别。

    流程：
    1. YOLO 检测（8ms）
    2. 判断是否需触发 VLM
    3. 若触发 + VLM 启用 → llama-mtmd-cli 调用（~320ms）
    4. 推送结果到 Hub
    """
    _check_active()

    img_path = Path(req.image_path)
    if not img_path.is_absolute():
        img_path = PROJECT_ROOT / img_path
    if not img_path.exists():
        raise HTTPException(404, f"图片不存在: {req.image_path}")

    img = cv2.imread(str(img_path))
    if img is None:
        raise HTTPException(400, f"无法读取图片: {req.image_path}")

    # ── 第一步：YOLO 预检测 ──
    t_start = time.perf_counter()
    detector = _get_yolo()
    yolo_result = detector.detect(img, zone="kitchen")

    detections = yolo_result.get("detections", [])
    label_counts = yolo_result.get("label_counts", {})
    yolo_ms = yolo_result.get("inference_ms", 0)

    # ── 第二步：判断是否触发 VLM ──
    should_vlm, vlm_reason = _should_trigger_vlm(detections, label_counts)

    # 缓存帧
    global _last_yolo_frame, _last_frame_time
    _last_yolo_frame = yolo_result
    _last_frame_time = time.time()

    # ── 第三步：VLM（按需触发，真实 CLI 或 mock 回退） ──
    items: List[Dict[str, Any]] = []
    vlm_used = False
    vlm_ms = 0.0
    vlm_source = "none"

    if should_vlm and VLM_ENABLED:
        items, vlm_source, vlm_ms = _run_vlm(img_path, detections, label_counts)
        vlm_used = True

    elif should_vlm and not VLM_ENABLED:
        vlm_reason += " (VLM disabled by HOTPOT_KITCHEN_VLM_ENABLED=0)"

    # ── 第四步：推 Hub ──
    pushed = False
    if items:
        try:
            httpx.post(
                f"{HUB_URL}/v1/vlm/waste-estimate",
                json={
                    "store_id": STORE_ID,
                    "zone": _zone,
                    "source": f"jetson-agent-kitchen:{vlm_source}",
                    "model": "Ostrakon-VL-8B.IQ4_XS" if vlm_source == "ostrakon-vl-8b" else "mock-rule",
                    "pipeline": "yolo+vlm",
                    "yolo_ms": round(yolo_ms, 1),
                    "vlm_ms": round(vlm_ms, 1) if vlm_used else None,
                    "items": items,
                },
                headers={"X-Api-Key": API_KEY},
                timeout=10,
            )
            pushed = True
        except Exception:
            pass

    total_ms = (time.perf_counter() - t_start) * 1000

    # ── 标注图（可选） ──
    out_name = f"kitchen_{img_path.stem}.jpg"
    out_path = OUTPUT_DIR / out_name
    detector.annotate_and_save(img, zone="kitchen", save_path=out_path)

    return {
        "ok": True,
        "pipeline": "yolo+vlm" if vlm_used else "yolo-only",
        "zone": _zone,
        "image": str(img_path),
        "yolo": {
            "total_detections": yolo_result.get("total_detections", 0),
            "label_counts": label_counts,
            "inference_ms": round(yolo_ms, 1),
        },
        "vlm": {
            "triggered": should_vlm,
            "used": vlm_used,
            "source": vlm_source,
            "reason": vlm_reason,
            "inference_ms": round(vlm_ms, 1) if vlm_used else None,
            "items": items,
        },
        "total_ms": round(total_ms, 1),
        "annotated_url": f"/output/{out_name}",
        "pushed_to_hub": pushed,
    }
