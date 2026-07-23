"""
K14: 加汤提醒 — 基于视觉的火锅汤位检测。

检测逻辑：前厅场景推理时，在 YOLO 检测到有人占据桌面后，触发此模块
通过检测火锅锅具边缘和汤面反射判断汤位是否 <1/3。
当汤位 <1/3 且持续 >2min 时，生成加汤提醒事件推送 Hub。

策略：利用 CLIP 语义能力判断汤位状态，规则层做最终决策。
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------

@dataclass
class SoupLevelEvent:
    """加汤提醒事件。"""
    table_id: str
    store_id: str = ""
    device_id: str = ""
    timestamp: float = 0.0
    soup_level: str = "normal"  # normal / low / critically_low
    low_since_ts: Optional[float] = None
    alert_triggered: bool = False


# ---------------------------------------------------------------------------
# Detector
# ---------------------------------------------------------------------------

class SoupLevelDetector:
    """
    火锅汤位检测器。

    利用 CLIP 进行语义判断——对 ROI（锅具区域）做图像-文本匹配：
    - "a hotpot with full soup"
    - "a hotpot with half soup"
    - "a hotpot with almost no soup left"

    规则层：
    - "almost no soup" → critically_low，持续 60s 触发告警
    - "half soup" → low，持续 120s 触发告警
    - "full soup" → normal，清除记时
    """

    THRESHOLD_CRITICAL_SEC = 60
    THRESHOLD_LOW_SEC = 120

    def __init__(self) -> None:
        self._low_start: dict[str, float] = {}
        self._alerted: set[str] = set()

    async def check(
        self,
        table_id: str,
        roi_image,  # np.ndarray or PIL image — 锅具区域裁剪
        clip_client=None,  # CLIP client with classify(image, labels) -> label
    ) -> SoupLevelEvent:
        """
        对给定桌面的锅具区域做汤位检测。

        Args:
            table_id: 桌号
            roi_image: 锅具区域图像（已有前厅推理检出桌面后可进一步裁剪）
            clip_client: CLIP 子进程客户端的分类能力

        Returns:
            SoupLevelEvent with soup_level and alert_triggered
        """
        event = SoupLevelEvent(
            table_id=table_id,
            timestamp=time.time(),
        )

        # 尝试 CLIP 分类
        label = "normal"
        if clip_client is not None:
            try:
                label = await clip_client.classify(
                    roi_image,
                    [
                        "a hotpot with full soup",
                        "a hotpot with half soup",
                        "a hotpot with almost no soup left",
                    ],
                )
            except Exception:
                logger.warning("CLIP分类失败，默认normal", exc_info=True)

        # 映射 CLIP label → 汤位等级
        if "almost no" in label or "no soup" in label:
            event.soup_level = "critically_low"
        elif "half" in label:
            event.soup_level = "low"
        else:
            event.soup_level = "normal"

        # 记时与告警
        return self._evaluate_alert(table_id, event)

    def _evaluate_alert(self, table_id: str, event: SoupLevelEvent) -> SoupLevelEvent:
        now = time.time()

        if event.soup_level == "normal":
            self._low_start.pop(table_id, None)
            self._alerted.discard(table_id)
            return event

        # 首次低汤位 → 记录时间
        if table_id not in self._low_start:
            self._low_start[table_id] = now
            return event

        elapsed = now - self._low_start[table_id]
        event.low_since_ts = self._low_start[table_id]

        threshold = (
            self.THRESHOLD_CRITICAL_SEC if event.soup_level == "critically_low"
            else self.THRESHOLD_LOW_SEC
        )

        if elapsed >= threshold and table_id not in self._alerted:
            event.alert_triggered = True
            self._alerted.add(table_id)
            logger.info("加汤告警 table=%s level=%s elapsed=%.0fs", table_id, event.soup_level, elapsed)

        return event

    def reset_table(self, table_id: str) -> None:
        """重置某桌状态（换桌后用）。"""
        self._low_start.pop(table_id, None)
        self._alerted.discard(table_id)
