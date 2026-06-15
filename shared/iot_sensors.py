"""IoT sensor registry for hotpot kitchen ingredient lifecycle."""

from __future__ import annotations

from typing import Any, Dict, List

# Lifecycle: receiving -> storage -> processing
LIFECYCLE_STAGES = ("receiving", "storage", "processing")

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
