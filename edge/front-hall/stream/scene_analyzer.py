#!/usr/bin/env python3
"""
每桌场景分析器 — YOLO 规则 + CLIP 语义（Plan A v2 混合策略）

策略：
  - YOLO 检测人头 → 硬判决 occupancy
  - 没人 + 少餐具 → empty
  - 没人 + 多餐具(≥3) → needs_cleaning
  - 有人 → CLIP 子进程做语义细分（桌态/服务/顾客行为）

CLIP 通过独立子进程运行（cwd=/tmp 绕开 platform/ 污染），
stdin/stdout JSON 行协议通信，模型常驻内存。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import cv2
import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[3]

# ── YOLO COCO 类映射 ──
CLASS_NAMES = {
    0:  "person",      39: "bottle",    41: "cup",
    44: "spoon",       45: "bowl",      47: "apple",
    48: "sandwich",    49: "orange",    50: "broccoli",
    51: "carrot",      52: "hot dog",   53: "pizza",
    54: "donut",       55: "cake",      60: "dining table",
    67: "cell phone",  73: "book",
}

FOOD_CLASSES     = {47, 48, 49, 50, 51, 52, 53, 54, 55}
DRINK_CLASSES    = {39, 40, 41}
TABLEWARE_CLASSES = {44, 45, 60}


# ══════════════════════════════════════════════════════════════════════
# CLIP 子进程客户端
# ══════════════════════════════════════════════════════════════════════

class ClipClient:
    """管理 CLIP 子进程生命周期，通过 stdin/stdout JSON 行协议通信。"""

    def __init__(self):
        self._proc: Optional[subprocess.Popen] = None
        self._server_path = str(Path(__file__).resolve().parent / "clip_server.py")

    def _ensure_started(self):
        if self._proc is not None and self._proc.poll() is None:
            return  # 已经在运行

        # 从 /tmp 启动以避开 hotpot platform/ 污染
        self._proc = subprocess.Popen(
            [sys.executable, self._server_path],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd="/tmp",
            text=True,
        )
        # 等就绪信号
        line = self._proc.stdout.readline()
        ready = json.loads(line)
        if not ready.get("ready"):
            raise RuntimeError(f"CLIP server failed to start: {line}")

    def classify(self, image_path: str) -> Dict[str, Any]:
        self._ensure_started()
        self._proc.stdin.write(json.dumps({"image_path": image_path}) + "\n")
        self._proc.stdin.flush()
        line = self._proc.stdout.readline()
        return json.loads(line)

    def close(self):
        if self._proc and self._proc.poll() is None:
            self._proc.stdin.close()
            self._proc.terminate()
            self._proc.wait(timeout=5)
            self._proc = None


# ══════════════════════════════════════════════════════════════════════
# 场景分析器
# ══════════════════════════════════════════════════════════════════════

class SceneAnalyzer:
    """每桌场景分析器，支持 plan_b (纯YOLO) 和 plan_a (YOLO+CLIP) 两种模式。"""

    def __init__(self, mode: str = "plan_b"):
        """
        Args:
            mode: "plan_b" = 纯 YOLO 规则（默认，40ms）
                  "plan_a" = YOLO 硬判决 + CLIP 语义（有人时 ~400ms）
        """
        self.mode = mode
        self._yolo = None
        self._clip: Optional[ClipClient] = None

    def _get_yolo(self):
        if self._yolo is None:
            import importlib

            # ── 强制恢复 stdlib platform ──
            _need_fix = ("platform" in sys.modules
                         and not hasattr(sys.modules["platform"], "system"))
            if _need_fix:
                del sys.modules["platform"]
                importlib.invalidate_caches()

            # 主动导入 stdlib platform 并验证
            _saved_path = list(sys.path)
            sys.path = [p for p in sys.path if "hotpot" not in str(p)]
            import platform as _chk
            assert hasattr(_chk, "system"), f"stdlib platform broken! file={_chk.__file__}"
            sys.path[:] = _saved_path

            # 加载 YOLO 模块
            spec = importlib.util.spec_from_file_location(
                "real_yolo",
                PROJECT_ROOT / "edge" / "shared" / "detector" / "real_yolo.py",
            )
            mod = importlib.util.module_from_spec(spec)

            sys.path = [p for p in sys.path if "hotpot" not in str(p)]
            spec.loader.exec_module(mod)
            sys.path[:] = _saved_path

            self._yolo = mod.RealYoloDetector(conf=0.2)
        return self._yolo

    def _get_clip(self) -> ClipClient:
        if self._clip is None:
            self._clip = ClipClient()
        return self._clip

    # ── YOLO 检测计数 ──

    def _count_detections(self, detections: List[Dict]) -> Dict[str, int]:
        person = food = drink = tableware = 0
        has_phone = False

        for d in detections:
            cid = d.get("class_id", -1)
            if cid == 0:
                person += 1
            elif cid in FOOD_CLASSES:
                food += 1
            elif cid in DRINK_CLASSES:
                drink += 1
            elif cid in TABLEWARE_CLASSES:
                tableware += 1
            elif cid == 67:
                has_phone = True

        return {
            "person": person, "food": food, "drink": drink,
            "tableware": tableware, "has_phone": has_phone,
        }

    # ── Plan B：纯 YOLO 规则推断 ──

    def _analyze_plan_b(
        self, counts: Dict[str, int], table_id: str, yolo_ms: float,
        ndet: int,
    ) -> Dict[str, Any]:
        p, f, d, t = counts["person"], counts["food"], counts["drink"], counts["tableware"]
        has_phone = counts["has_phone"]

        # 桌态
        if p == 0 and f == 0 and t == 0:
            status = "empty"
        elif p == 0 and t >= 3:
            status = "needs_cleaning"
        elif p == 0 and t <= 2 and f == 0:
            status = "ready"
        elif p >= 1:
            status = "dining"
        else:
            status = "unknown"

        # 告警
        alerts: List[str] = []
        if status == "dining":
            if t >= 3 and f <= 1:
                alerts.append(f"empty_plate_count:{t}")
            if p >= 2 and d <= 1:
                alerts.append("low_drinks")
        if status == "needs_cleaning":
            alerts.append("needs_cleaning")
        if has_phone and status == "dining":
            alerts.append("customer_ready_to_pay")

        # 顾客行为
        if has_phone and p >= 1:
            customer_behavior = "ready_to_pay"
        elif p >= 1:
            customer_behavior = "normal_dining"
        else:
            customer_behavior = "none"

        return self._build_result(
            status=status, alerts=alerts,
            customer_behavior=customer_behavior,
            table_id=table_id, counts=counts,
            yolo_ms=yolo_ms, ndet=ndet,
            mode="plan_b_yolo_only",
            clip_info=None,
        )

    # ── Plan A：YOLO 硬判决 + CLIP 语义 ──

    def _analyze_plan_a(
        self, counts: Dict[str, int], table_id: str, yolo_ms: float,
        ndet: int, image_path: str,
    ) -> Dict[str, Any]:
        p, t = counts["person"], counts["tableware"]
        has_phone = counts["has_phone"]

        clip_info = None

        if p == 0:
            # YOLO 硬判决：没人
            if t >= 3:
                status = "needs_cleaning"
            else:
                status = "empty"
            customer_behavior = "none"
            alerts = [status] if status == "needs_cleaning" else []
        else:
            # 有人 → CLIP 语义细分
            try:
                clip_info = self._get_clip().classify(image_path)
                status = clip_info.get("table", "unknown")
                alerts = []
                # 服务推促
                if clip_info.get("service") == "clearing" and status == "dining":
                    alerts.append("suggest_clearing")
                if clip_info.get("customer") == "calling_waiter":
                    alerts.append("customer_calling")
                if clip_info.get("customer") == "paying":
                    alerts.append("customer_ready_to_pay")
                if has_phone:
                    alerts.append("customer_ready_to_pay")

                customer_behavior = clip_info.get("customer", "normal_dining")
            except Exception as e:
                # CLIP 不可用 → 降级为规则
                status = "dining" if p >= 1 else "unknown"
                customer_behavior = "normal_dining"
                alerts = []
                clip_info = {"error": str(e), "fallback": "rule"}

        return self._build_result(
            status=status, alerts=alerts,
            customer_behavior=customer_behavior,
            table_id=table_id, counts=counts,
            yolo_ms=yolo_ms, ndet=ndet,
            mode="plan_a_yolo_clip",
            clip_info=clip_info,
        )

    # ── 构建输出 ──

    def _build_result(
        self, *, status, alerts, customer_behavior, table_id, counts,
        yolo_ms, ndet, mode, clip_info,
    ) -> Dict[str, Any]:
        # 优先级
        priority_map = {
            "needs_cleaning": "high", "empty": "low",
            "dining": "medium", "ready": "medium",
        }
        priority = priority_map.get(status, "medium")
        if "customer_ready_to_pay" in alerts:
            priority = "high"

        # 推荐
        tid = table_id or "该桌"
        if status == "needs_cleaning":
            recommendation = f"推促清洁人员到 {tid}：需收拾清理"
        elif status == "dining":
            parts = [f"推促服务员关注 {tid}"]
            if "low_drinks" in alerts:
                parts.append("加饮品")
            if any(a.startswith("empty_plate_count") for a in alerts):
                parts.append("收空盘")
            if "customer_calling" in alerts:
                parts.append("顾客呼叫")
            if "customer_ready_to_pay" in alerts:
                parts.append("准备结账")
            recommendation = (
                "：".join([parts[0], "、".join(parts[1:])])
                if len(parts) > 1 else parts[0]
            )
        elif status == "ready":
            recommendation = f"{tid} 翻台就绪，可引导新客入座"
        elif status == "empty":
            recommendation = f"{tid} 空桌可用"
        else:
            recommendation = f"关注 {tid}"

        return {
            "table_id": table_id or "unknown",
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "status": status,
            "customer_count": counts["person"],
            "alerts": alerts,
            "service": {
                "waiter_present": False,
                "last_service_sec": -1,
            },
            "customer_behavior": customer_behavior,
            "priority": priority,
            "recommendation": recommendation,
            "_diagnostics": {
                "mode": mode,
                "yolo_ms": round(yolo_ms, 1),
                "total_ms": -1,  # 由 analyze_table 填入
                "detections": ndet,
                "person": counts["person"],
                "food": counts["food"],
                "drink": counts["drink"],
                "tableware": counts["tableware"],
                "phone": counts["has_phone"],
                "clip": clip_info,
            },
        }

    # ── 统一入口 ──

    def analyze_table(
        self, image: np.ndarray, table_id: str = "",
        image_path: str = "",
    ) -> Dict[str, Any]:
        t_start = time.perf_counter()

        # 1. YOLO 检测（所有模式共用）
        detector = self._get_yolo()
        result = detector.detect(image, zone="front")
        detections = result.get("detections", [])
        yolo_ms = result.get("inference_ms", 0)
        counts = self._count_detections(detections)

        # 2. 模式分发
        if self.mode == "plan_a" and image_path:
            output = self._analyze_plan_a(
                counts, table_id, yolo_ms, len(detections), image_path,
            )
        else:
            output = self._analyze_plan_b(
                counts, table_id, yolo_ms, len(detections),
            )

        total_ms = (time.perf_counter() - t_start) * 1000
        output["_diagnostics"]["total_ms"] = round(total_ms, 1)
        return output

    def close(self):
        if self._clip:
            self._clip.close()
            self._clip = None


# ══════════════════════════════════════════════════════════════════════
# 单例
# ══════════════════════════════════════════════════════════════════════

_analyzers: Dict[str, SceneAnalyzer] = {}

def get_analyzer(mode: str = "plan_b") -> SceneAnalyzer:
    if mode not in _analyzers:
        _analyzers[mode] = SceneAnalyzer(mode=mode)
    return _analyzers[mode]

def analyze_table_image(
    image: np.ndarray, table_id: str = "",
    image_path: str = "", mode: str = "plan_b",
) -> Dict[str, Any]:
    return get_analyzer(mode).analyze_table(image, table_id, image_path)
