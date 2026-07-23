"""Pluggable registry for IoT food-safety sensor drivers."""

from __future__ import annotations

import os
from typing import Any, Callable, Dict, Iterable, List

from edge.iot_food_safety.sensor_driver import (
    BluetoothTempSensor,
    RFIDExpiryTracker,
    SensorDriver,
    TempHumiditySensor,
)


SensorFactory = Callable[..., SensorDriver]

_DRIVER_REGISTRY: Dict[str, SensorFactory] = {
    "bluetooth_temp": BluetoothTempSensor,
    "temp_humidity": TempHumiditySensor,
    "rfid_expiry": RFIDExpiryTracker,
}


def register_driver(name: str, factory: SensorFactory) -> None:
    """Register or replace a sensor driver factory."""
    if not name:
        raise ValueError("driver name is required")
    _DRIVER_REGISTRY[name] = factory


def get_driver(name: str) -> SensorFactory:
    """Return a registered sensor driver factory."""
    try:
        return _DRIVER_REGISTRY[name]
    except KeyError as exc:
        raise KeyError(f"unknown IoT food-safety driver: {name}") from exc


def available_drivers() -> List[str]:
    """List registered driver names."""
    return sorted(_DRIVER_REGISTRY)


def build_sensors(configs: Iterable[Dict[str, Any]]) -> List[SensorDriver]:
    """Instantiate sensors from config dictionaries."""
    sensors: List[SensorDriver] = []
    for cfg in configs:
        cfg = dict(cfg)
        driver_name = cfg.pop("driver", cfg.pop("type", ""))
        sensor_id = cfg.pop("sensor_id", cfg.pop("id", ""))
        if not driver_name or not sensor_id:
            raise ValueError(f"invalid sensor config: {cfg}")
        factory = get_driver(driver_name)
        sensors.append(factory(sensor_id=sensor_id, **cfg))
    return sensors


def default_sensors() -> List[SensorDriver]:
    """Build a small default sensor set for local development and demos."""
    mock = os.environ.get("MOCK_SENSORS", "1").strip().lower() in ("1", "true", "yes", "on")
    return [
        BluetoothTempSensor("bt_cold_storage_01", location="cold_storage", mock=mock),
        TempHumiditySensor("th_prep_area_01", location="prep_area", mock=mock),
        RFIDExpiryTracker("rfid_storage_01", location="storage", mock=mock),
    ]


__all__ = [
    "BluetoothTempSensor",
    "RFIDExpiryTracker",
    "SensorDriver",
    "TempHumiditySensor",
    "available_drivers",
    "build_sensors",
    "default_sensors",
    "get_driver",
    "register_driver",
]
