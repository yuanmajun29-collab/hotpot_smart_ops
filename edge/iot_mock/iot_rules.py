"""IoT alert rules — door open timeout (DEV-413 / BL-02)."""

from __future__ import annotations

import time
from typing import Any, Dict, Optional

from shared.schemas import EventLevel, EventSource, utc_now_iso

DEFAULT_DOOR_TIMEOUT_SEC = 180


def parse_door_open(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return int(value) == 1
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "open", "opened", "on")
    return bool(value)


class DoorTimeoutTracker:
    """Track door sensors; emit alert when open longer than threshold."""

    def __init__(self, timeout_sec: float = DEFAULT_DOOR_TIMEOUT_SEC) -> None:
        self.timeout_sec = timeout_sec
        self._open_since: Dict[str, float] = {}
        self._alerted: Dict[str, bool] = {}

    def reset(self, sensor_id: Optional[str] = None) -> None:
        if sensor_id:
            self._open_since.pop(sensor_id, None)
            self._alerted.pop(sensor_id, None)
        else:
            self._open_since.clear()
            self._alerted.clear()

    def on_reading(
        self,
        sensor_id: str,
        value: Any,
        *,
        store_id: str,
        zone: str = "kitchen",
    ) -> Optional[Dict[str, Any]]:
        is_open = parse_door_open(value)
        now = time.monotonic()

        if not is_open:
            self._open_since.pop(sensor_id, None)
            self._alerted.pop(sensor_id, None)
            return None

        if sensor_id not in self._open_since:
            self._open_since[sensor_id] = now
            self._alerted[sensor_id] = False
            return None

        elapsed = now - self._open_since[sensor_id]
        if not self._alerted.get(sensor_id) and elapsed >= self.timeout_sec:
            self._alerted[sensor_id] = True
            return {
                "event_type": "iot_door_open_timeout",
                "source": EventSource.IOT.value,
                "level": EventLevel.WARN.value,
                "store_id": store_id,
                "zone": zone,
                "message": f"门磁 {sensor_id} 开启超过 {int(self.timeout_sec)}s 未关闭",
                "timestamp": utc_now_iso(),
                "metadata": {
                    "sensor_id": sensor_id,
                    "open_seconds": round(elapsed, 1),
                    "threshold_sec": self.timeout_sec,
                },
            }
        return None


def level_for_sensor(
    sensor_type: str,
    value: Any,
    thresholds: Dict[str, Any],
) -> str:
    if sensor_type == "door":
        return EventLevel.INFO.value
    try:
        num = float(value)
    except (TypeError, ValueError):
        return EventLevel.INFO.value

    if sensor_type == "temperature":
        lo = thresholds.get("cold_storage_min_c", -22)
        hi = thresholds.get("cold_storage_max_c", -15)
        if num > hi + 3 or num < lo - 3:
            return EventLevel.CRITICAL.value
        if num > hi or num < lo:
            return EventLevel.WARN.value
    if sensor_type == "gas":
        warn = thresholds.get("gas_ppm_warn", 50)
        if num >= warn * 2:
            return EventLevel.CRITICAL.value
        if num >= warn:
            return EventLevel.WARN.value
    return EventLevel.INFO.value
