"""IoT food-safety alert rules.

The rule engine is intentionally small and dependency-free so it can run on
Jetson edge boxes without blocking sensor collection.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional


DEFAULT_THRESHOLDS: Dict[str, Any] = {
    "cold_storage_min_c": -22.0,
    "cold_storage_max_c": -15.0,
    "refrigerated_min_c": 0.0,
    "refrigerated_max_c": 4.0,
    "prep_area_max_c": 12.0,
    "humidity_min_pct": 30.0,
    "humidity_max_pct": 75.0,
    "critical_temp_delta_c": 3.0,
    "expiry_warning_days": 3,
    "expiry_critical_days": 1,
    "alert_cooldown_sec": 300.0,
}


def utc_now_iso() -> str:
    """Return a UTC ISO-8601 timestamp without microseconds."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


class AlertCooldown:
    """Suppress repeated alerts by alert key for a fixed time window."""

    def __init__(self, cooldown_sec: float = 300.0) -> None:
        self.cooldown_sec = float(cooldown_sec)
        self._last_sent: Dict[str, float] = {}

    def allow(self, key: str) -> bool:
        """Return True when an alert with ``key`` can be emitted now."""
        now = time.monotonic()
        previous = self._last_sent.get(key)
        if previous is not None and now - previous < self.cooldown_sec:
            return False
        self._last_sent[key] = now
        return True

    def reset(self, key: Optional[str] = None) -> None:
        """Clear cooldown state for one key or all keys."""
        if key is None:
            self._last_sent.clear()
        else:
            self._last_sent.pop(key, None)


def merge_thresholds(overrides: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Merge caller-provided threshold overrides onto defaults."""
    thresholds = dict(DEFAULT_THRESHOLDS)
    if overrides:
        thresholds.update({k: v for k, v in overrides.items() if v is not None})
    return thresholds


def _temperature_bounds(reading: Dict[str, Any], thresholds: Dict[str, Any]) -> tuple:
    zone = str(reading.get("zone") or reading.get("location") or "").lower()
    if "fridge" in zone or "refriger" in zone or "冷藏" in zone:
        return thresholds["refrigerated_min_c"], thresholds["refrigerated_max_c"]
    if "prep" in zone or "processing" in zone or "加工" in zone:
        return None, thresholds["prep_area_max_c"]
    return thresholds["cold_storage_min_c"], thresholds["cold_storage_max_c"]


def evaluate_temperature(reading: Dict[str, Any], thresholds: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Build an alert when a temperature reading is outside configured bounds."""
    try:
        value = float(reading["value"])
    except (KeyError, TypeError, ValueError):
        return None

    lo, hi = _temperature_bounds(reading, thresholds)
    delta = float(thresholds["critical_temp_delta_c"])
    level = None
    direction = ""
    if hi is not None and value > hi:
        level = "critical" if value > hi + delta else "warn"
        direction = "超温"
    elif lo is not None and value < lo:
        level = "critical" if value < lo - delta else "warn"
        direction = "低温"
    if level is None:
        return None

    sensor_id = reading.get("sensor_id", "unknown")
    return {
        "alert_type": "iot_temperature_abnormal",
        "level": level,
        "message": f"食安温度传感器 {sensor_id} {direction}: {value:.1f}°C",
        "metadata": {"reading": reading, "min_c": lo, "max_c": hi},
        "key": f"temperature:{sensor_id}:{direction}",
    }


def evaluate_humidity(reading: Dict[str, Any], thresholds: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Build an alert when humidity is outside configured bounds."""
    try:
        value = float(reading["humidity"])
    except (KeyError, TypeError, ValueError):
        try:
            value = float(reading["value"])
        except (KeyError, TypeError, ValueError):
            return None

    lo = float(thresholds["humidity_min_pct"])
    hi = float(thresholds["humidity_max_pct"])
    if lo <= value <= hi:
        return None
    sensor_id = reading.get("sensor_id", "unknown")
    return {
        "alert_type": "iot_humidity_abnormal",
        "level": "warn",
        "message": f"食安湿度传感器 {sensor_id} 异常: {value:.1f}%RH",
        "metadata": {"reading": reading, "min_pct": lo, "max_pct": hi},
        "key": f"humidity:{sensor_id}",
    }


def expiry_level(days_remaining: int, thresholds: Dict[str, Any]) -> str:
    """Return expiry status level for a remaining-day count."""
    if days_remaining < 0:
        return "critical"
    if days_remaining <= int(thresholds["expiry_critical_days"]):
        return "critical"
    if days_remaining <= int(thresholds["expiry_warning_days"]):
        return "warn"
    return "info"


def evaluate_expiry(reading: Dict[str, Any], thresholds: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Build an expiry alert for RFID batch readings nearing expiry."""
    if "days_remaining" not in reading:
        return None
    try:
        days_remaining = int(reading["days_remaining"])
    except (TypeError, ValueError):
        return None

    level = expiry_level(days_remaining, thresholds)
    if level == "info":
        return None

    batch_id = reading.get("batch_id") or reading.get("tag_id") or "unknown"
    sku = reading.get("sku", "未知食材")
    return {
        "alert_type": "iot_expiry_warning",
        "level": level,
        "message": f"RFID 食材 {sku} 批次 {batch_id} 距过期 {days_remaining} 天",
        "metadata": {"reading": reading, "days_remaining": days_remaining},
        "key": f"expiry:{batch_id}",
    }


def evaluate_readings(
    readings: Iterable[Dict[str, Any]],
    thresholds: Optional[Dict[str, Any]] = None,
    cooldown: Optional[AlertCooldown] = None,
) -> List[Dict[str, Any]]:
    """Evaluate readings and return cooldown-filtered alert dictionaries."""
    cfg = merge_thresholds(thresholds)
    alerts: List[Dict[str, Any]] = []
    for reading in readings:
        sensor_type = reading.get("type")
        candidates = []
        if sensor_type == "temperature":
            candidates.append(evaluate_temperature(reading, cfg))
        elif sensor_type == "temp_humidity":
            candidates.append(evaluate_temperature(reading, cfg))
            candidates.append(evaluate_humidity(reading, cfg))
        elif sensor_type == "rfid_expiry":
            candidates.append(evaluate_expiry(reading, cfg))

        for alert in candidates:
            if not alert:
                continue
            key = str(alert.pop("key"))
            if cooldown and not cooldown.allow(key):
                continue
            alert.setdefault("timestamp", utc_now_iso())
            alerts.append(alert)
    return alerts
