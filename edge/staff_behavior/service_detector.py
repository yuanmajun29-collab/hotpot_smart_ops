"""
K26: 服务响应检测 — 检测顾客召唤后服务员的响应时间。

逻辑：
1. 前厅推理已有桌面状态（dining/needs_cleaning/empty）
2. 在 dining 状态下，检测顾客举手/招手动作 → 记录召唤时间
3. 检测服务员靠近该桌 → 记录响应时间
4. 如响应时间 >3min → 生成告警事件推 Hub

检测手段：
- YOLO 检测 person 类别，结合 CLIP 判断手部姿态（举手 vs 正常用餐）
- 或简化版：依赖前厅已有的 dining 状态 + 桌面人头数变化来判断
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class ServiceResponseEvent:
    table_id: str
    store_id: str = ""
    timestamp: float = 0.0
    summon_detected: bool = False
    summon_at: Optional[float] = None
    responded_at: Optional[float] = None
    response_seconds: Optional[float] = None
    alert_triggered: bool = False
    alert_level: str = ""  # "warning" (>3min) / "critical" (>5min)


# ---------------------------------------------------------------------------
# Detector
# ---------------------------------------------------------------------------

class ServiceResponseDetector:
    """
    服务响应检测器。

    使用规则推断（不依赖额外模型）：
    - 通过探测 dining 场景中的人体关键点来识别举手动作
    - 简化方案：监控桌位 dining 持续时间 + 店员出现事件
    """

    ALERT_SLOW_SEC = 180    # 3 分钟
    ALERT_CRITICAL_SEC = 300  # 5 分钟

    def __init__(self) -> None:
        self._summons: dict[str, float] = {}   # table_id → summon_time
        self._alerted_tables: set[str] = set()

    async def report_summon(self, table_id: str) -> ServiceResponseEvent:
        """
        前端检测到顾客召唤（举手/招手/按钮）。

        可由前厅推理的 YOLO+CLIP 或额外的关键点检测触发。
        """
        now = time.time()
        if table_id not in self._summons:
            self._summons[table_id] = now

        return ServiceResponseEvent(
            table_id=table_id,
            timestamp=now,
            summon_detected=True,
            summon_at=self._summons[table_id],
        )

    async def report_responded(self, table_id: str) -> ServiceResponseEvent:
        """
        检测到服务员到达该桌后调用。
        """
        now = time.time()
        summon_at = self._summons.pop(table_id, None)

        if summon_at is None:
            # 没有记录召唤——可能是服务员主动巡台，不算延迟
            return ServiceResponseEvent(table_id=table_id, timestamp=now)

        elapsed = now - summon_at
        event = ServiceResponseEvent(
            table_id=table_id,
            timestamp=now,
            summon_at=summon_at,
            responded_at=now,
            response_seconds=elapsed,
        )

        if elapsed >= self.ALERT_CRITICAL_SEC:
            event.alert_triggered = True
            event.alert_level = "critical"
            self._alerted_tables.add(table_id)
            logger.warning("服务响应超时 critical table=%s elapsed=%.0fs", table_id, elapsed)
        elif elapsed >= self.ALERT_SLOW_SEC:
            event.alert_triggered = True
            event.alert_level = "warning"
            self._alerted_tables.add(table_id)
            logger.info("服务响应偏慢 warning table=%s elapsed=%.0fs", table_id, elapsed)

        return event

    def get_pending_summons(self) -> dict[str, float]:
        """获取所有等待响应的召唤（原始时间戳）。"""
        return dict(self._summons)

    def reset_table(self, table_id: str) -> None:
        self._summons.pop(table_id, None)
        self._alerted_tables.discard(table_id)
