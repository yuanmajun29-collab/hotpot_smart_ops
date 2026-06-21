"""IoT sensor registry for hotpot kitchen ingredient lifecycle."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

# Lifecycle: receiving -> storage -> processing
LIFECYCLE_STAGES = ("receiving", "storage", "processing")

P1A_REQUIRED_SENSOR_IDS = (
    "receiving_scale",
    "receiving_probe_temp",
    "cold_storage_1",
    "cold_storage_2",
    "freezer_door_1",
)

_TYPE_PROFILE_DEFAULTS: Dict[str, Dict[str, Any]] = {
    "weight": {
        "protocol": "modbus_rtu",
        "sample_interval_sec": 5,
        "health_max_age_sec": 300,
        "calibration": {"method": "standard_weight", "tolerance_pct": 0.2, "interval_days": 30},
    },
    "temperature": {
        "protocol": "modbus_rtu",
        "sample_interval_sec": 60,
        "health_max_age_sec": 300,
        "calibration": {"method": "ice_water_probe", "tolerance_c": 0.5, "interval_days": 90},
    },
    "humidity": {
        "protocol": "modbus_rtu",
        "sample_interval_sec": 60,
        "health_max_age_sec": 300,
        "calibration": {"method": "salt_solution", "tolerance_rh": 5, "interval_days": 180},
    },
    "door": {
        "protocol": "digital_input",
        "sample_interval_sec": 10,
        "health_max_age_sec": 300,
        "calibration": {"method": "open_close_check", "interval_days": 30},
    },
    "rfid": {
        "protocol": "mqtt",
        "sample_interval_sec": 300,
        "health_max_age_sec": 900,
        "calibration": {"method": "tag_scan_check", "interval_days": 30},
    },
    "duration": {
        "protocol": "mqtt",
        "sample_interval_sec": 60,
        "health_max_age_sec": 300,
        "calibration": {"method": "timer_self_check", "interval_days": 90},
    },
    "gas": {
        "protocol": "modbus_rtu",
        "sample_interval_sec": 30,
        "health_max_age_sec": 300,
        "calibration": {"method": "gas_span_check", "interval_days": 180},
    },
}

IOT_SENSORS: Dict[str, Dict[str, Any]] = {
    # --- 来料收货 ---
    "receiving_scale": {
        "stage": "receiving",
        "type": "weight",
        "unit": "kg",
        "sop_checkpoint": "receiving_weight_match",
        "description": "收货智能秤（数量把控）",
    },
    "receiving_probe_temp": {
        "stage": "receiving",
        "type": "temperature",
        "unit": "C",
        "normal_range": (-25, 4),
        "sop_checkpoint": "receiving_temp_check",
        "description": "到货探针测温（品质）",
    },
    "receiving_humidity": {
        "stage": "receiving",
        "type": "humidity",
        "unit": "%RH",
        "normal_range": (40, 75),
        "sop_checkpoint": "receiving_env_ok",
        "description": "卸货区湿度",
    },
    "receiving_rfid_gate": {
        "stage": "receiving",
        "type": "rfid",
        "unit": "count",
        "sop_checkpoint": "receiving_rfid_logged",
        "description": "RFID 批次入库扫描",
    },
    # --- 保存 ---
    "cold_storage_1": {
        "stage": "storage",
        "type": "temperature",
        "unit": "C",
        "normal_range": (-22, -15),
        "sop_checkpoint": "cold_chain_ok",
        "description": "冷冻库温（荤料）",
    },
    "cold_storage_2": {
        "stage": "storage",
        "type": "temperature",
        "unit": "C",
        "normal_range": (0, 4),
        "sop_checkpoint": "cold_chain_ok",
        "description": "冷藏库温（素菜/底料）",
    },
    "freezer_door_1": {
        "stage": "storage",
        "type": "door",
        "unit": "state",
        "normal_range": (0, 1),  # 0=closed
        "sop_checkpoint": "storage_door_closed",
        "description": "冷库门磁（超时不关告警）",
    },
    "storage_humidity": {
        "stage": "storage",
        "type": "humidity",
        "unit": "%RH",
        "normal_range": (35, 65),
        "sop_checkpoint": "storage_humidity_ok",
        "description": "冷库湿度",
    },
    "rfid_shelf_zone_a": {
        "stage": "storage",
        "type": "rfid",
        "unit": "tag",
        "sop_checkpoint": "storage_fefo_ok",
        "description": "RFID 货位/FEFO 先进先出",
    },
    # --- 加工 ---
    "prep_scale_raw": {
        "stage": "processing",
        "type": "weight",
        "unit": "kg",
        "sop_checkpoint": "prep_input_weight",
        "description": "改刀前称重（领料）",
    },
    "prep_scale_usable": {
        "stage": "processing",
        "type": "weight",
        "unit": "kg",
        "sop_checkpoint": "prep_yield_logged",
        "description": "改刀后可用重量（出成率 IoT 自动登记）",
    },
    "thaw_pool_temp": {
        "stage": "processing",
        "type": "temperature",
        "unit": "C",
        "normal_range": (0, 4),
        "sop_checkpoint": "prep_thaw_temp_ok",
        "description": "解冻池水温",
    },
    "prep_area_temp": {
        "stage": "processing",
        "type": "temperature",
        "unit": "C",
        "normal_range": (15, 25),
        "sop_checkpoint": "prep_area_env_ok",
        "description": "改刀间环境温度",
    },
    "prep_timer_thaw": {
        "stage": "processing",
        "type": "duration",
        "unit": "min",
        "normal_range": (0, 240),
        "sop_checkpoint": "prep_thaw_time_ok",
        "description": "解冻时长计时器",
    },
    "broth_temp_hold": {
        "stage": "processing",
        "type": "temperature",
        "unit": "C",
        "normal_range": (85, 98),
        "sop_checkpoint": "broth_temp_hold",
        "description": "锅底保温温度",
    },
    # --- 通用安全 ---
    "gas_main": {
        "stage": "storage",
        "type": "gas",
        "unit": "ppm",
        "normal_range": (0, 50),
        "sop_checkpoint": "closing_gas_off",
        "description": "燃气浓度",
    },
}

IOT_EVENT_TYPES = {
    "weight": ("iot_weight_mismatch", "iot_weight_short"),
    "temperature": ("cold_chain_high", "cold_chain_low", "iot_temp_abnormal"),
    "humidity": ("iot_humidity_abnormal",),
    "door": ("iot_door_open_timeout",),
    "rfid": ("iot_rfid_missing", "iot_fefo_violation"),
    "duration": ("iot_thaw_overtime",),
    "gas": ("gas_leak",),
}


def sensors_by_stage(stage: str) -> List[str]:
    return [sid for sid, cfg in IOT_SENSORS.items() if cfg.get("stage") == stage]


def checkpoint_to_sensor(checkpoint_id: str) -> str | None:
    for sid, cfg in IOT_SENSORS.items():
        if cfg.get("sop_checkpoint") == checkpoint_id:
            return sid
    return None


def sensor_profile(sensor_id: str, store_id: Optional[str] = None) -> Dict[str, Any]:
    """Return a normalized device profile with protocol, calibration, topic, and health SLA."""
    if sensor_id not in IOT_SENSORS:
        raise KeyError(f"unknown sensor_id: {sensor_id}")
    cfg = dict(IOT_SENSORS[sensor_id])
    defaults = dict(_TYPE_PROFILE_DEFAULTS.get(cfg.get("type"), {}))
    calibration = {**defaults.pop("calibration", {}), **dict(cfg.get("calibration", {}))}
    profile = {**defaults, **cfg, "sensor_id": sensor_id, "calibration": calibration}
    profile["required_p1a"] = sensor_id in P1A_REQUIRED_SENSOR_IDS
    if store_id:
        profile["store_id"] = store_id
        profile["topic"] = f"hotpot/{store_id}/sensors/{sensor_id}"
    return profile


def sensor_profiles(store_id: Optional[str] = None, *, required_only: bool = False) -> List[Dict[str, Any]]:
    ids = P1A_REQUIRED_SENSOR_IDS if required_only else tuple(IOT_SENSORS.keys())
    return [sensor_profile(sid, store_id) for sid in ids]


def _parse_ts(value: Any) -> Optional[datetime]:
    if not value:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        try:
            dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def evaluate_sensor_health(
    profile: Dict[str, Any],
    latest_reading: Optional[Dict[str, Any]],
    *,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Classify a registered sensor as online/offline/out_of_range from its latest reading."""
    now_dt = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    max_age = int(profile.get("health_max_age_sec", 300))
    health: Dict[str, Any] = {
        "status": "offline",
        "reason": "missing_reading",
        "max_age_sec": max_age,
        "age_sec": None,
        "in_range": None,
    }
    if not latest_reading:
        return health

    recorded_at = _parse_ts(latest_reading.get("recorded_at"))
    if not recorded_at:
        health.update({"reason": "invalid_timestamp"})
        return health
    age_sec = max(0, int((now_dt - recorded_at).total_seconds()))
    health["age_sec"] = age_sec
    if age_sec > max_age:
        health.update({"reason": "stale_reading"})
        return health

    in_range = True
    rng = profile.get("normal_range")
    value = latest_reading.get("value")
    if rng and value is not None:
        lo, hi = rng
        in_range = float(lo) <= float(value) <= float(hi)
    health["in_range"] = in_range
    if not in_range:
        health.update({"status": "out_of_range", "reason": "value_out_of_range"})
        return health
    health.update({"status": "online", "reason": "ok"})
    return health
