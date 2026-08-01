"""
IoT传感器 API
GET    /api/v1/iot/sensors          传感器列表
POST   /api/v1/iot/sensors          添加传感器
GET    /api/v1/iot/sensors/{id}     传感器详情(含当前读数)
PUT    /api/v1/iot/sensors/{id}     更新传感器配置(阈值等)
DELETE /api/v1/iot/sensors/{id}     删除传感器
GET    /api/v1/iot/sensors/{id}/history 传感器历史数据
"""

import json
import time
from pathlib import Path
from typing import List, Optional
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel

# L2 PIN 认证依赖 (Step 5)
from middleware import get_current_session

router = APIRouter()

CONF_DIR = Path(__file__).parent.parent / "conf"
SENSORS_FILE = CONF_DIR / "iot_sensors.json"


class SensorCreate(BaseModel):
    id: str
    name: str
    type: str  # temperature / humidity / weight / door_state / rfid_scan
    unit: str
    zone: str  # warehouse / kitchen / front_hall
    threshold_low: Optional[float] = None
    threshold_high: Optional[float] = None
    enabled: bool = True


class SensorReading(BaseModel):
    value: float
    status: str  # normal / warning / critical
    timestamp: str


def _load_sensors() -> List[dict]:
    if SENSORS_FILE.exists():
        return json.loads(SENSORS_FILE.read_text(encoding="utf-8")).get("sensors", [])
    return []


def _save_sensors(sensors: List[dict]):
    CONF_DIR.mkdir(parents=True, exist_ok=True)
    SENSORS_FILE.write_text(json.dumps({"sensors": sensors}, ensure_ascii=False, indent=2), encoding="utf-8")


@router.get("/iot/sensors")
async def list_sensors(_=Depends(get_current_session)):
    """传感器列表 + 当前读数(MVP模拟)"""
    sensors = _load_sensors()
    # 为每个传感器生成模拟读数
    for s in sensors:
        s_type = s.get("type", "")
        if s_type == "temperature":
            s["reading"] = {"value": -18.5 + __import__("random").uniform(-2, 2), "unit": "°C"}
        elif s_type == "humidity":
            s["reading"] = {"value": 60 + __import__("random").uniform(-10, 20), "unit": "%RH"}
        elif s_type == "power":
            s["reading"] = {"value": 1800 + __import__("random").uniform(-100, 100), "unit": "W"}
    return sensors


@router.post("/iot/sensors", status_code=201)
async def create_sensor(sensor: SensorCreate, _=Depends(get_current_session)):
    """添加传感器"""
    sensors = _load_sensors()
    new_sensor = sensor.dict()
    new_sensor["created_at"] = time.strftime('%Y-%m-%dT%H:%M:%S+08:00')
    sensors.append(new_sensor)
    _save_sensors(sensors)
    return {"code": 0, "message": f"传感器已添加: {sensor.name}", "sensor_id": sensor.id}


@router.get("/iot/sensors/{sensor_id}")
async def get_sensor(sensor_id: str, _=Depends(get_current_session)):
    """传感器详情"""
    sensors = _load_sensors()
    for s in sensors:
        if s.get("id") == sensor_id:
            return s
    raise HTTPException(status_code=404, detail=f"传感器不存在: {sensor_id}")


@router.put("/iot/sensors/{sensor_id}")
async def update_sensor(sensor_id: str, updates: dict, _=Depends(get_current_session)):
    """更新传感器配置(阈值等)"""
    sensors = _load_sensors()
    for i, s in enumerate(sensors):
        if s.get("id") == sensor_id:
            s.update(updates)
            s.pop("id", None)  # 不允许修改ID
            _save_sensors(sensors)
            return {"code": 0, "message": "传感器配置已更新"}
    raise HTTPException(status_code=404, detail=f"传感器不存在: {sensor_id}")


@router.delete("/iot/sensors/{sensor_id}")
async def delete_sensor(sensor_id: str, _=Depends(get_current_session)):
    """删除传感器"""
    sensors = _load_sensors()
    for i, s in enumerate(sensors):
        if s.get("id") == sensor_id:
            removed = sensors.pop(i)
            _save_sensors(sensors)
            return {"code": 0, "message": f"传感器已删除: {removed.get('name', '')}"}
    raise HTTPException(status_code=404, detail=f"传感器不存在: {sensor_id}")


@router.get("/iot/sensors/{sensor_id}/history")
async def get_sensor_history(sensor_id: str, hours: int = 24, _=Depends(get_current_session)):
    """传感器历史数据(MVP模拟)"""
    # TODO: 从时序DB或文件读取真实历史
    import random
    history = []
    for i in range(min(hours * 6, 100)):  # 每10分钟一个点
        history.append({
            "time": time.strftime('%Y-%m-%dT%H:%M:%S+08:00', time.localtime(time.time() - i * 600)),
            "value": round(random.uniform(-22, -14), 1),
        })
    return {"sensor_id": sensor_id, "hours": hours, "data": history}
