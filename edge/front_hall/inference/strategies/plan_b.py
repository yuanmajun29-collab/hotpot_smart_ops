#!/usr/bin/env python3
"""
Plan B — 纯 YOLO 规则推断

最快策略（~40ms），只做 YOLO 检测计数 → 规则引擎判断。
不依赖 CLIP/VLM 等大模型。
"""

from __future__ import annotations

from typing import Any, Dict

from ..rules import plan_b_status, plan_b_alerts, plan_b_behavior
from .base import BaseStrategy


class PlanBStrategy(BaseStrategy):
    strategy_name = "plan_b"
    strategy_mode = "plan_b_yolo_only"

    def analyze(
        self, engine_provider, counts: Dict[str, int],
        table_id: str, yolo_ms: float, ndet: int,
        image_path: str = "",
    ) -> Dict[str, Any]:
        p, f, t = counts["person"], counts["food"], counts["tableware"]

        status = plan_b_status(p, f, t)
        alerts = plan_b_alerts(status, **counts)
        customer_behavior = plan_b_behavior(counts["person"], counts["has_phone"])

        return self.build_result(
            status=status, alerts=alerts,
            customer_behavior=customer_behavior,
            table_id=table_id, counts=counts,
            yolo_ms=yolo_ms, ndet=ndet,
            mode=self.strategy_mode,
            clip_info=None,
        )
