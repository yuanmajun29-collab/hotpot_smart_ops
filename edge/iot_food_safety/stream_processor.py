"""
IoT 流处理层 — 窗口·趋势·状态机

确定性计算在前，模型推理在后。
不把原始读数直接扔给 Agent，先把消息整理成有业务意义的变化。

架构位置: MQTT → 本层 → 状态快照 → 上下文组装 → Agent
"""

from __future__ import annotations

import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

# ── 趋势方向 ──
class Trend:
    RISING = "rising"
    FALLING = "falling"
    STABLE = "stable"
    VOLATILE = "volatile"  # 剧烈波动


# ── 单传感器窗口 ──
@dataclass
class SensorWindow:
    """维护单个传感器的滚动窗口，计算趋势和基线。"""
    sensor_id: str
    window_sec: float = 600  # 默认 10 分钟窗口
    _readings: List[Tuple[float, float]] = field(default_factory=list)  # [(timestamp, value)]

    def add(self, value: float, ts: Optional[float] = None) -> None:
        ts = ts or time.monotonic()
        self._readings.append((ts, value))
        self._prune(ts)

    def _prune(self, now: float) -> None:
        cutoff = now - self.window_sec
        self._readings = [(t, v) for t, v in self._readings if t >= cutoff]

    @property
    def count(self) -> int:
        return len(self._readings)

    @property
    def latest(self) -> Optional[float]:
        return self._readings[-1][1] if self._readings else None

    @property
    def min_val(self) -> Optional[float]:
        return min(v for _, v in self._readings) if self._readings else None

    @property
    def max_val(self) -> Optional[float]:
        return max(v for _, v in self._readings) if self._readings else None

    @property
    def avg(self) -> Optional[float]:
        if not self._readings:
            return None
        return sum(v for _, v in self._readings) / len(self._readings)

    @property
    def delta(self) -> Optional[float]:
        """窗口内首尾差值（正=上升，负=下降）。"""
        if len(self._readings) < 2:
            return None
        return self._readings[-1][1] - self._readings[0][1]

    def trend(self, min_samples: int = 3, change_threshold: float = 0.3) -> str:
        """判断趋势方向。"""
        if len(self._readings) < min_samples:
            return Trend.STABLE
        d = self.delta
        if d is None:
            return Trend.STABLE
        # 检查波动性
        if len(self._readings) >= 5:
            values = [v for _, v in self._readings]
            mean_v = sum(values) / len(values)
            variance = sum((v - mean_v) ** 2 for v in values) / len(values)
            if variance > (change_threshold * 3):
                return Trend.VOLATILE
        if d > change_threshold:
            return Trend.RISING
        elif d < -change_threshold:
            return Trend.FALLING
        return Trend.STABLE

    def consecutive_above(self, threshold: float, min_count: int = 3) -> bool:
        """检查最近 N 个读数是否连续高于阈值。"""
        recent = [v for _, v in self._readings[-min_count:]]
        return len(recent) >= min_count and all(v > threshold for v in recent)

    def consecutive_below(self, threshold: float, min_count: int = 3) -> bool:
        recent = [v for _, v in self._readings[-min_count:]]
        return len(recent) >= min_count and all(v < threshold for v in recent)


# ── 状态机 ──
class DeviceStateMachine:
    """设备状态机: normal → warning → critical → recovering"""

    NORMAL = "normal"
    WARNING = "warning"
    CRITICAL = "critical"
    RECOVERING = "recovering"

    def __init__(self, device_id: str):
        self.device_id = device_id
        self.state = self.NORMAL
        self.state_since: Optional[float] = None
        self.transition_history: List[Dict[str, Any]] = []

    def _transition(self, new_state: str, reason: str, evidence: Dict[str, Any]) -> None:
        old = self.state
        self.state = new_state
        now = time.monotonic()
        self.state_since = now
        self.transition_history.append({
            "from": old, "to": new_state, "reason": reason,
            "timestamp": now, "evidence": evidence,
        })

    def evaluate(self, window: SensorWindow, thresholds: Dict[str, Any]) -> Dict[str, Any]:
        """根据窗口数据评估状态变化。返回事件（如有）。"""
        event = None
        hi = thresholds.get("critical_high", 8)
        lo = thresholds.get("critical_low", -22)
        warn_hi = thresholds.get("warn_high", 4)
        consecutive_min = thresholds.get("consecutive_min", 3)

        if window.consecutive_above(hi, consecutive_min):
            if self.state != self.CRITICAL:
                self._transition(self.CRITICAL, "连续超临界阈值",
                                 {"latest": window.latest, "avg": window.avg, "trend": window.trend()})
                event = {"type": "state_change", "from": self.transition_history[-2]["from"] if len(self.transition_history) > 1 else self.NORMAL, "to": self.CRITICAL}
        elif window.consecutive_above(warn_hi, consecutive_min):
            if self.state not in (self.WARNING, self.CRITICAL):
                self._transition(self.WARNING, "连续超告警阈值",
                                 {"latest": window.latest, "avg": window.avg, "trend": window.trend()})
                event = {"type": "state_change", "from": self.NORMAL, "to": self.WARNING}
        elif window.consecutive_below(warn_hi, consecutive_min):
            if self.state in (self.WARNING, self.CRITICAL):
                self._transition(self.RECOVERING, "读数恢复到正常范围",
                                 {"latest": window.latest, "avg": window.avg})
                event = {"type": "state_change", "from": self.WARNING, "to": self.RECOVERING}
            if self.state == self.RECOVERING and window.consecutive_below(warn_hi, consecutive_min * 2):
                self._transition(self.NORMAL, "持续正常，恢复完成", {})
                event = {"type": "state_change", "from": self.RECOVERING, "to": self.NORMAL}

        return {
            "device_id": self.device_id,
            "state": self.state,
            "state_since": self.state_since,
            "triggered_event": event,
            "transition_count": len(self.transition_history),
        }


# ── 同区域关联检测 ──
class ZoneCorrelationDetector:
    """检测同一区域内多个传感器是否同时异常（关联告警）。"""

    def __init__(self, zone_id: str):
        self.zone_id = zone_id
        self._sensor_states: Dict[str, str] = {}

    def update(self, sensor_id: str, state: str) -> Optional[Dict[str, Any]]:
        self._sensor_states[sensor_id] = state
        abnormal = [sid for sid, s in self._sensor_states.items() if s in (DeviceStateMachine.WARNING, DeviceStateMachine.CRITICAL)]
        if len(abnormal) >= 2:
            return {
                "type": "zone_correlation_alert",
                "zone_id": self.zone_id,
                "abnormal_sensors": abnormal,
                "message": f"区域 {self.zone_id} 内 {len(abnormal)} 个传感器同时异常: {abnormal}",
            }
        return None
