#!/usr/bin/env python3
"""
Stage — SOP 视觉合规检测（后厨 YOLO 穿戴检测）

基于 YOLO 检测 → 5 项 PPE 规则判断 → 输出 compliance 结果。
用于管线式推理和 Edge Agent 的 sop_infer 模块。

检测项:
  - 帽子 (hat): 人头顶部区域颜色比 → 是否佩戴厨师帽
  - 口罩 (mask): 人脸下部区域颜色比 → 是否佩戴口罩
  - 围裙 (apron): 人体下部区域颜色比 → 是否穿围裙
  - 手套 (gloves): 手部区域颜色比 → 是否戴手套
  - 人员 (person): 是否有人在工作

输出:
  {station_id, compliant: bool, violations: [{type, severity}], timestamp}
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

import numpy as np

STAGE_NAME = "sop"
STAGE_ORDER = 99  # 独立使用，不作为管线默认阶段

# ── COCO 类别映射 ──
PERSON_CLASS_ID = 0

# ── PPE 颜色比阈值（参考 staff_behavior/detector.py）──
PPE_HAT_COLOR_RATIO = 0.15       # 帽子区域 vs 身体颜色比
PPE_MASK_COLOR_RATIO = 0.12      # 口罩区域 vs 面部颜色比
PPE_APRON_COLOR_RATIO = 0.18     # 围裙区域 vs 上身颜色比
PPE_GLOVE_COLOR_RATIO = 0.20     # 手套区域 vs 手臂颜色比

# ── 违规模板 ──
VIOLATION_TYPES = {
    "no_hat": "未佩戴厨师帽",
    "no_mask": "未佩戴口罩",
    "no_apron": "未穿围裙",
    "no_gloves": "未戴手套",
    "no_person": "工位无人",
}


def _extract_person_roi(frame: np.ndarray, bbox: list) -> Optional[np.ndarray]:
    """从检测框提取人员 ROI。"""
    try:
        h, w = frame.shape[:2]
        x1, y1, x2, y2 = [max(0, int(v)) for v in bbox[:4]]
        x2, y2 = min(w, x2), min(h, y2)
        if x2 <= x1 or y2 <= y1:
            return None
        return frame[y1:y2, x1:x2]
    except Exception:
        return None


def _check_ppe_hat(person_roi: np.ndarray) -> bool:
    """检测帽子：头顶 22% 区域 vs 身体其他区域颜色比。"""
    try:
        h, w = person_roi.shape[:2]
        if h < 20 or w < 10:
            return False

        head_h = max(1, int(h * 0.22))
        head_region = person_roi[:head_h, :]
        body_region = person_roi[head_h:, :]

        if head_region.size == 0 or body_region.size == 0:
            return False

        head_mean = np.mean(head_region)
        body_mean = np.mean(body_region)
        if body_mean < 1:
            return False
        ratio = abs(head_mean - body_mean) / body_mean
        return ratio > PPE_HAT_COLOR_RATIO
    except Exception:
        return False


def _check_ppe_mask(person_roi: np.ndarray) -> bool:
    """检测口罩：面部下部 15-35% 区域颜色比。"""
    try:
        h, w = person_roi.shape[:2]
        if h < 30 or w < 10:
            return False

        # 面部区域在人体上部的 15%-40%
        face_start = int(h * 0.15)
        face_end = int(h * 0.40)
        face_region = person_roi[face_start:face_end, :]

        # 口罩区域在面部下半部
        mask_start = int((face_end - face_start) * 0.55)
        mask_region = person_roi[face_start + mask_start:face_end, :]
        upper_face = person_roi[face_start:face_start + mask_start, :]

        if mask_region.size == 0 or upper_face.size == 0:
            return False

        mask_mean = np.mean(mask_region)
        upper_mean = np.mean(upper_face)
        if upper_mean < 1:
            return False
        ratio = abs(mask_mean - upper_mean) / upper_mean
        return ratio > PPE_MASK_COLOR_RATIO
    except Exception:
        return False


def _check_ppe_apron(person_roi: np.ndarray) -> bool:
    """检测围裙：人体下部 55%-100% 区域颜色比。"""
    try:
        h, w = person_roi.shape[:2]
        if h < 40 or w < 10:
            return False

        upper_start = int(h * 0.30)
        upper_end = int(h * 0.55)
        apron_start = int(h * 0.55)

        upper_region = person_roi[upper_start:upper_end, :]
        apron_region = person_roi[apron_start:, :]

        if upper_region.size == 0 or apron_region.size == 0:
            return False

        apron_mean = np.mean(apron_region)
        upper_mean = np.mean(upper_region)
        if upper_mean < 1:
            return False
        ratio = abs(apron_mean - upper_mean) / upper_mean
        return ratio > PPE_APRON_COLOR_RATIO
    except Exception:
        return False


def _check_ppe_gloves(person_roi: np.ndarray) -> bool:
    """检测手套：手部区域（人体最下部 10%）颜色比。"""
    try:
        h, w = person_roi.shape[:2]
        if h < 30 or w < 10:
            return False

        hand_start = int(h * 0.88)
        arm_start = int(h * 0.70)
        hand_region = person_roi[hand_start:, :]
        arm_region = person_roi[arm_start:hand_start, :]

        if hand_region.size == 0 or arm_region.size == 0:
            return False

        hand_mean = np.mean(hand_region)
        arm_mean = np.mean(arm_region)
        if arm_mean < 1:
            return False
        ratio = abs(hand_mean - arm_mean) / arm_mean
        return ratio > PPE_GLOVE_COLOR_RATIO
    except Exception:
        return False


def run(frame_path: str, ctx: dict) -> dict:
    """运行 SOP 视觉合规检测。

    从 ctx 获取 YOLO 检测结果（或自行检测），对每个人进行 PPE 检查。

    Args:
        frame_path: 图片路径
        ctx: 管线上下文，预期含 yolo_result 或 frame numpy 数组

    Returns:
        {
            "status": "ok",
            "station_id": ctx.get("station_id", "unknown"),
            "compliant": bool,
            "violations": [{type: str, severity: str}],
            "person_count": int,
            "ppe_details": [...],
            "inference_ms": float,
        }
    """
    import cv2

    t0 = time.time()
    station_id = ctx.get("station_id", "unknown")

    # ── 获取图片 ──
    frame = None
    img = cv2.imread(frame_path) if frame_path else None

    # ── YOLO 检测人员 ──
    detections = []
    yolo_result = ctx.get("yolo_result", {})

    if yolo_result.get("detections"):
        # 复用管线 YOLO 结果
        detections = yolo_result["detections"]
    else:
        # 自行检测
        try:
            from edge.common.detector.real_yolo import RealYoloDetector
            detector = RealYoloDetector(conf=0.25)
            result = detector.detect(img, zone="kitchen")
            detections = result.get("detections", [])
        except Exception:
            # 无 YOLO 可用时返回空检测
            pass

    # ── 筛选人员检测 ──
    person_dets = [
        d for d in detections
        if d.get("class_id") == PERSON_CLASS_ID and d.get("confidence", 0) >= 0.25
    ]

    # ── 对每个人员进行 PPE 检查 ──
    ppe_details = []
    violation_set: Dict[str, bool] = {}

    for det in person_dets:
        person_roi = _extract_person_roi(img, det.get("bbox", []))
        if person_roi is None:
            continue

        detail = {
            "bbox": det.get("bbox", []),
            "confidence": det.get("confidence", 0),
            "ppe_hat": _check_ppe_hat(person_roi),
            "ppe_mask": _check_ppe_mask(person_roi),
            "ppe_apron": _check_ppe_apron(person_roi),
            "ppe_gloves": _check_ppe_gloves(person_roi),
        }

        # 记录违规项
        if not detail["ppe_hat"]:
            violation_set["no_hat"] = True
        if not detail["ppe_mask"]:
            violation_set["no_mask"] = True
        if not detail["ppe_apron"]:
            violation_set["no_apron"] = True
        if not detail["ppe_gloves"]:
            violation_set["no_gloves"] = True

        ppe_details.append(detail)

    # 无人检测也算违规
    if len(person_dets) == 0:
        violation_set["no_person"] = True

    # ── 构建违规列表 ──
    violations = [
        {"type": vtype, "severity": "warning", "message": VIOLATION_TYPES.get(vtype, vtype)}
        for vtype in violation_set
    ]

    compliant = len(violations) == 0

    inference_ms = round((time.time() - t0) * 1000, 1)

    return {
        "status": "ok",
        "station_id": station_id,
        "compliant": compliant,
        "violations": violations,
        "person_count": len(person_dets),
        "ppe_details": ppe_details,
        "inference_ms": inference_ms,
    }
