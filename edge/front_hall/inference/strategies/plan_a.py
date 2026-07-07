#!/usr/bin/env python3
"""
Plan A — YOLO 硬判决 + CLIP 语义细分

有人时调用 CLIP 做三组分类（桌态/服务/顾客行为），
没人时直接用 YOLO 硬判决（餐具 ≥3 → needs_cleaning）。
CLIP 故障时自动降级为规则推断。
"""

from __future__ import annotations

from typing import Any, Dict

from .base import BaseStrategy


class PlanAStrategy(BaseStrategy):
    strategy_name = "plan_a"
    strategy_mode = "plan_a_yolo_clip"

    def analyze(
        self, engine_provider, counts: Dict[str, int],
        table_id: str, yolo_ms: float, ndet: int,
        image_path: str = "",
    ) -> Dict[str, Any]:
        p, t = counts["person"], counts["tableware"]
        has_phone = counts["has_phone"]

        if p == 0:
            # YOLO 硬判决：没人 → 看餐具量
            if t >= 3:
                status = "needs_cleaning"
            else:
                status = "empty"
            customer_behavior = "none"
            alerts = [status] if status == "needs_cleaning" else []
            clip_info = None
        else:
            # 有人 → CLIP 语义细分
            try:
                clip = engine_provider("clip")
                clip_info = clip.classify(image_path)
                status = clip_info.get("table", "unknown")
                alerts = []

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

        return self.build_result(
            status=status, alerts=alerts,
            customer_behavior=customer_behavior,
            table_id=table_id, counts=counts,
            yolo_ms=yolo_ms, ndet=ndet,
            mode=self.strategy_mode,
            clip_info=clip_info,
        )
