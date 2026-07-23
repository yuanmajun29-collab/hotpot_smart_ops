"""
K30: 微笑/服务态度识别 — 基于视觉的正向行为反馈。

设计理念（非负向监控）：
- 识别微笑和服务规范动作，生成正向积分
- 不做惩罚性检测（不标记"没笑"）
- 默认开启"正向反馈"，关闭"负向评分"

检测手段：
- CLIP 语义判断：smile vs neutral vs frown
- YOLO 检测人像 ROI → CLIP 细分类
- 结果聚合为日/周服务态度积分
"""
from __future__ import annotations

import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class SmileEvent:
    """单次微笑检测事件。"""
    person_id: str = ""
    timestamp: float = 0.0
    expression: str = "neutral"  # smile / neutral / frown
    confidence: float = 0.0
    score_impact: int = 0  # +1 for smile, 0 for neutral, -1 for frown (opt-in)


@dataclass
class ServiceAttitudeReport:
    """服务态度日报。"""
    store_id: str = ""
    date: str = ""
    total_detections: int = 0
    smile_count: int = 0
    neutral_count: int = 0
    frown_count: int = 0
    smile_ratio: float = 0.0
    attitude_score: int = 0  # 50 基线 ± smile/frown 偏差


# ---------------------------------------------------------------------------
# Detector
# ---------------------------------------------------------------------------

class SmileDetector:
    """
    微笑/表情检测器。

    使用 CLIP 对人员面部 ROI 做表情分类。
    仅做正向反馈——记录微笑、中性、皱眉的比例，不单独告警。
    """

    def __init__(self) -> None:
        self._daily_events: list[SmileEvent] = []
        self._person_states: dict[str, dict] = {}  # person_id → {last_detect, state}
        self.COOLDOWN_SEC = 30  # 同一人 30s 内不重复记录

    async def detect(
        self,
        person_id: str,
        face_roi,  # np.ndarray — 人员面部裁剪区域
        clip_client=None,  # CLIP client
    ) -> Optional[SmileEvent]:
        """
        对单个人员做表情检测。

        Returns SmileEvent with expression label and score_impact.
        如果人员在冷却期内则返回 None（不重复计数）。
        """
        now = time.time()

        # 冷却检查
        if person_id in self._person_states:
            last = self._person_states[person_id].get("last_detect", 0)
            if now - last < self.COOLDOWN_SEC:
                return None

        # CLIP 分类
        expression = "neutral"
        confidence = 0.0
        if clip_client is not None:
            try:
                expression = await clip_client.classify(
                    face_roi,
                    ["a smiling person", "a person with neutral expression", "a frowning person"],
                )
                confidence = 0.7  # CLIP 不提供置信度，用固定值
            except Exception:
                logger.warning("CLIP表情分类失败", exc_info=True)

        # 映射 label
        if "smiling" in expression:
            expr_label = "smile"
            score_impact = 1
        elif "frowning" in expression:
            expr_label = "frown"
            score_impact = -1
        else:
            expr_label = "neutral"
            score_impact = 0

        event = SmileEvent(
            person_id=person_id,
            timestamp=now,
            expression=expr_label,
            confidence=confidence,
            score_impact=score_impact,
        )

        # 记录
        self._person_states[person_id] = {"last_detect": now, "state": expr_label}
        self._daily_events.append(event)

        return event

    def get_daily_report(self, store_id: str = "", date: str = "") -> ServiceAttitudeReport:
        """生成当日服务态度报告。"""
        report = ServiceAttitudeReport(
            store_id=store_id,
            date=date or time.strftime("%Y-%m-%d"),
        )

        for ev in self._daily_events:
            report.total_detections += 1
            if ev.expression == "smile":
                report.smile_count += 1
            elif ev.expression == "frown":
                report.frown_count += 1
            else:
                report.neutral_count += 1

        report.smile_ratio = (
            report.smile_count / report.total_detections
            if report.total_detections > 0
            else 0.0
        )

        # 态度评分：基线 50，每个 smile +2，每个 frown -3（更敏感）
        report.attitude_score = max(0, min(100,
            50 + report.smile_count * 2 - report.frown_count * 3
        ))

        return report

    def reset_daily(self) -> None:
        """新一天清空缓存。"""
        self._daily_events.clear()
        self._person_states.clear()
