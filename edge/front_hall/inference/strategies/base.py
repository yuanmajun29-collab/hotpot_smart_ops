#!/usr/bin/env python3
"""
策略基类 + 结果构建器

所有策略继承 BaseStrategy，只需实现 analyze()。
新增策略 = 在 strategies/ 下丢一个文件，导出 STRATEGY_NAME + 继承 BaseStrategy 的类。
"""

from __future__ import annotations

import time
from typing import Any, Dict, List

from ..rules import compute_priority, build_recommendation


class BaseStrategy:
    """策略基类。子类必须设置 strategy_name 并实现 analyze()。"""

    strategy_name: str = ""
    strategy_mode: str = ""   # 诊断用 label

    def build_result(
        self, *, status, alerts, customer_behavior, table_id, counts,
        yolo_ms, ndet, mode, clip_info=None,
    ) -> Dict[str, Any]:
        """构建统一的输出结构（所有策略共用）。"""
        priority = compute_priority(status, alerts)
        recommendation = build_recommendation(status, alerts, table_id)

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
                "total_ms": -1,  # pipeline 填入
                "detections": ndet,
                "person": counts["person"],
                "food": counts["food"],
                "drink": counts["drink"],
                "tableware": counts["tableware"],
                "phone": counts["has_phone"],
                "clip": clip_info,
            },
        }

    def analyze(
        self, engine_provider, counts: Dict[str, int],
        table_id: str, yolo_ms: float, ndet: int,
        image_path: str = "",
    ) -> Dict[str, Any]:
        """子类实现：接收 YOLO 计数 + 引擎提供者，返回结果 dict。"""
        raise NotImplementedError
