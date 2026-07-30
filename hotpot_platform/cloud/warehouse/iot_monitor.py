"""
火瞳 · 仓库 IoT — IoT 监控引擎 (WH02 + WH06)

对应 PRD:
  WH02: 温湿度实时监控
  WH06: IoT 设备管理与阈值配置
架构规范: 详细架构 v1.1 §1.8.3
模块路径: hotpot_platform.cloud.warehouse.iot_monitor

数据源:
  MQTT (warehouse/sensor/{store_id}/{device_id}/telemetry)
设备类型:
  DS18B20(温度) / SHT30(温湿度) / AM2302(环境) / RFID Gateway
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any

from hotpot_platform.cloud.warehouse.models import (
    IoTReading,
    IngestResult,
    DeviceStatus,
    DeviceThresholdConfig,
    TemperatureTimeline,
    TemperaturePoint,
)

logger = logging.getLogger(__name__)

# 默认阈值配置（按区域）
DEFAULT_THRESHOLDS: Dict[str, Dict[str, Any]] = {
    "cold_room": {
        "temp_min_c": 0.0, "temp_max_c": 4.0,
        "humidity_min_pct": 75.0, "humidity_max_pct": 90.0,
        "alarm_duration_sec": 900,
    },
    "freezer": {
        "temp_min_c": -22.0, "temp_max_c": -16.0,
        "humidity_min_pct": None, "humidity_max_pct": None,
        "alarm_duration_sec": 900,
    },
    "warehouse": {
        "temp_min_c": 15.0, "temp_max_c": 28.0,
        "humidity_min_pct": 40.0, "humidity_max_pct": 70.0,
        "alarm_duration_sec": 1800,
    },
    "kitchen": {
        "temp_min_c": 18.0, "temp_max_c": 30.0,
        "humidity_min_pct": 40.0, "humidity_max_pct": 70.0,
        "alarm_duration_sec": 1800,
    },
}

# 设备类型映射
DEVICE_TYPE_MAP = {
    "ds18b20": "temperature_sensor",
    "sht30": "combined",
    "am2302": "combined",
    "dht22": "combined",
    "rfid_gateway": "rfid_gateway",
}


class IoTMonitor:
    """仓库 IoT 监控引擎 — 对接 PRD WH02 + WH06

    负责:
      1. 接收并持久化 IoT 遥测数据
      2. 阈值检查与超限告警
      3. 设备状态查询
      4. 温湿度时间线查询（冷链合规报告）
      5. 设备阈值配置管理
    """

    def __init__(
        self,
        db_session,
        mqtt_client=None,       # Optional[MQTTClient]
        alert_gateway=None,     # Optional[AlertGateway]
    ) -> None:
        self._db = db_session
        self._mqtt = mqtt_client
        self._alerts = alert_gateway

    # ---- 核心方法 ----

    def ingest_telemetry(
        self,
        store_id: str,
        device_id: str,
        readings: List[IoTReading],
    ) -> IngestResult:
        """接收 IoT 遥测数据并写入数据库。

        同时执行阈值检查，超限即触发告警。

        Args:
            store_id: 门店标识
            device_id: 设备标识
            readings: 遥测数据列表

        Returns:
            IngestResult 含写入数、告警触发数、错误列表
        """
        received = len(readings)
        stored = 0
        alerts_triggered = 0
        errors: List[str] = []

        # 获取设备阈值配置
        threshold = self._get_device_threshold(device_id)

        for reading in readings:
            try:
                # 1. 写入遥测原始数据
                self._write_telemetry(store_id, device_id, reading)
                stored += 1

                # 2. 更新设备最后状态
                self._update_device_status(store_id, device_id, reading)

                # 3. 阈值检查
                violation = self._check_threshold(
                    reading, threshold, store_id, device_id
                )
                if violation:
                    self._emit_iot_alert(
                        store_id=store_id,
                        device_id=device_id,
                        violation=violation,
                    )
                    alerts_triggered += 1

            except Exception as e:
                errors.append(f"device={device_id} error={e}")
                logger.error("遥测写入失败 device=%s: %s", device_id, e)

        result = IngestResult(
            readings_received=received,
            readings_stored=stored,
            alerts_triggered=alerts_triggered,
            errors=errors,
        )

        logger.info(
            "IoT遥测入库 store=%s device=%s received=%d stored=%d alerts=%d",
            store_id, device_id, received, stored, alerts_triggered,
        )
        return result

    def get_device_status(
        self,
        store_id: str,
        device_id: Optional[str] = None,
    ) -> List[DeviceStatus]:
        """返回设备状态列表。

        Args:
            store_id: 门店标识
            device_id: 可选，指定设备；None=返回全店所有设备

        Returns:
            List[DeviceStatus] 含最新读数、在线状态、阈值配置
        """
        if device_id:
            rows = self._query_device(store_id, device_id)
        else:
            rows = self._query_all_devices(store_id)

        result: List[DeviceStatus] = []
        for row in rows:
            did = row.get("device_id", "")
            threshold = self._get_device_threshold(did)
            last_reading = self._get_latest_reading(store_id, did)

            # 判断在线状态：5分钟内有数据为 online
            is_online = False
            if last_reading and last_reading.reading_at:
                age = datetime.utcnow() - last_reading.reading_at
                is_online = age < timedelta(minutes=5)

            status = "online" if is_online else "offline"
            if threshold and last_reading:
                v = self._check_threshold(last_reading, threshold, store_id, did)
                if v:
                    status = "alarm"

            result.append(DeviceStatus(
                device_id=did,
                device_type=row.get("device_type", "unknown"),
                location=row.get("location", "unknown"),
                last_reading_at=last_reading.reading_at if last_reading else None,
                current_temp_c=last_reading.temperature_c if last_reading else None,
                current_humidity_pct=last_reading.humidity_pct if last_reading else None,
                battery_pct=last_reading.battery_pct if last_reading else None,
                signal_rssi=last_reading.signal_rssi if last_reading else None,
                status=status,
                threshold_config=threshold,
            ))

        return result

    def get_temperature_timeline(
        self,
        store_id: str,
        device_id: str,
        start: datetime,
        end: datetime,
        interval_minutes: int = 5,
    ) -> TemperatureTimeline:
        """获取温湿度时间线（用于冷链合规报告）。

        Args:
            store_id: 门店标识
            device_id: 设备标识
            start: 起始时间
            end: 结束时间
            interval_minutes: 聚合间隔（分钟）

        Returns:
            TemperatureTimeline 含数据点序列和超限次数统计
        """
        rows = self._query_telemetry_range(store_id, device_id, start, end)
        threshold = self._get_device_threshold(device_id)

        points: List[TemperaturePoint] = []
        violations_count = 0

        for row in rows:
            ts = row.get("reading_at")
            temp = row.get("temperature_c")
            hum = row.get("humidity_pct")

            try:
                ts = datetime.fromisoformat(str(ts)) if isinstance(ts, str) else ts
            except (ValueError, TypeError):
                continue

            point = TemperaturePoint(
                timestamp=ts,
                temperature_c=temp,
                humidity_pct=hum,
            )

            # 检查该点是否超限
            if threshold and temp is not None:
                if temp < threshold.temp_min_c or temp > threshold.temp_max_c:
                    violations_count += 1

            points.append(point)

        timeline = TemperatureTimeline(
            device_id=device_id,
            store_id=store_id,
            start=start,
            end=end,
            interval_minutes=interval_minutes,
            points=points,
            violations_count=violations_count,
        )

        logger.info(
            "温湿度时间线查询 store=%s device=%s points=%d violations=%d",
            store_id, device_id, len(points), violations_count,
        )
        return timeline

    def configure_threshold(
        self,
        device_id: str,
        temp_min_c: float,
        temp_max_c: float,
        humidity_min_pct: Optional[float] = None,
        humidity_max_pct: Optional[float] = None,
        alarm_duration_sec: int = 900,
        configured_by: str = "",
    ) -> DeviceThresholdConfig:
        """配置单个设备的监控阈值。"""
        config = DeviceThresholdConfig(
            device_id=device_id,
            temp_min_c=temp_min_c,
            temp_max_c=temp_max_c,
            humidity_min_pct=humidity_min_pct,
            humidity_max_pct=humidity_max_pct,
            alarm_duration_sec=alarm_duration_sec,
            configured_by=configured_by,
            configured_at=datetime.utcnow(),
        )

        # 持久化到 device_registry 或 iot_thresholds 表
        self._save_threshold(config)

        logger.info(
            "设备阈值配置更新 device=%s temp=[%.1f, %.1f] by=%s",
            device_id, temp_min_c, temp_max_c, configured_by or "system",
        )
        return config

    # ---- 内部方法 ----

    def _write_telemetry(
        self, store_id: str, device_id: str, reading: IoTReading
    ) -> None:
        """写入单条遥测数据到 iot_readings 表。"""
        sql = """
            INSERT INTO iot_readings
            (store_id, device_id, sensor_type, temperature_c, humidity_pct,
             battery_pct, signal_rssi, reading_at, raw_payload)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        self._db.execute(sql, (
            store_id,
            device_id,
            reading.sensor_type,
            reading.temperature_c,
            reading.humidity_pct,
            reading.battery_pct,
            reading.signal_rssi,
            reading.reading_at.isoformat(),
            json.dumps(reading.raw_payload or {}, ensure_ascii=False),
        ))
        self._db.commit()

    def _update_device_status(
        self, store_id: str, device_id: str, reading: IoTReading
    ) -> None:
        """更新 device_registry 中设备的最后状态。"""
        payload = json.dumps({
            "last_reading_at": reading.reading_at.isoformat(),
            "last_temp_c": reading.temperature_c,
            "last_humidity_pct": reading.humidity_pct,
            "battery_pct": reading.battery_pct,
            "signal_rssi": reading.signal_rssi,
            "updated_at": datetime.utcnow().isoformat(),
        }, ensure_ascii=False)

        sql = """
            INSERT OR REPLACE INTO device_registry (device_id, payload, updated_at)
            VALUES (?, ?, ?)
        """
        self._db.execute(sql, (device_id, payload, datetime.utcnow().isoformat()))
        self._db.commit()

    def _get_device_threshold(self, device_id: str) -> Optional[DeviceThresholdConfig]:
        """获取设备阈值配置（先查自定义，回退到默认）。"""
        # TODO: 从 iot_thresholds 表查询自定义配置
        # 当前回退到冷藏间默认值
        return DeviceThresholdConfig(
            device_id=device_id,
            **DEFAULT_THRESHOLDS["cold_room"],
        )

    def _save_threshold(self, config: DeviceThresholdConfig) -> None:
        """持久化阈值配置。"""
        sql = """
            INSERT OR REPLACE INTO iot_thresholds
            (device_id, temp_min_c, temp_max_c, humidity_min_pct, humidity_max_pct,
             alarm_duration_sec, configured_by, configured_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """
        self._db.execute(sql, (
            config.device_id,
            config.temp_min_c,
            config.temp_max_c,
            config.humidity_min_pct,
            config.humidity_max_pct,
            config.alarm_duration_sec,
            config.configured_by,
            config.configured_at.isoformat() if config.configured_at else None,
        ))
        self._db.commit()

    def _check_threshold(
        self,
        reading: IoTReading,
        threshold: Optional[DeviceThresholdConfig],
        store_id: str,
        device_id: str,
    ) -> Optional[Dict[str, Any]]:
        """检查单条读数是否超限，返回违规详情或 None。"""
        if not threshold or reading.temperature_c is None:
            return None

        t = reading.temperature_c
        if t >= threshold.temp_min_c and t <= threshold.temp_max_c:
            return None

        return {
            "type": "temperature_exceeded",
            "device_id": device_id,
            "store_id": store_id,
            "value": t,
            "min_threshold": threshold.temp_min_c,
            "max_threshold": threshold.temp_max_c,
            "violated_side": "low" if t < threshold.temp_min_c else "high",
            "reading_at": reading.reading_at.isoformat(),
        }

    def _query_device(self, store_id: str, device_id: str) -> List[Dict]:
        """查询单个设备信息。"""
        sql = """
            SELECT device_id, payload, updated_at FROM device_registry
            WHERE device_id = ?
        """
        cursor = self._db.execute(sql, (device_id,))
        columns = [desc[0] for desc in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]

    def _query_all_devices(self, store_id: str) -> List[Dict]:
        """查询门店所有已注册设备。"""
        sql = """SELECT device_id, payload, updated_at FROM device_registry"""
        cursor = self._db.execute(sql,)
        columns = [desc[0] for desc in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]

    def _get_latest_reading(self, store_id: str, device_id: str) -> Optional[IoTReading]:
        """获取设备最新一条读数。"""
        sql = """
            SELECT * FROM iot_readings
            WHERE store_id = ? AND device_id = ?
            ORDER BY reading_at DESC LIMIT 1
        """
        cursor = self._db.execute(sql, (store_id, device_id))
        row = cursor.fetchone()
        if not row:
            return None
        columns = [desc[0] for desc in cursor.description]
        d = dict(zip(columns, row))
        return IoTReading(
            device_id=d.get("device_id", ""),
            sensor_type=d.get("sensor_type", "temperature"),
            temperature_c=d.get("temperature_c"),
            humidity_pct=d.get("humidity_pct"),
            battery_pct=d.get("battery_pct"),
            signal_rssi=d.get("signal_rssi"),
            reading_at=datetime.fromisoformat(d["reading_at"]) if d.get("reading_at") else None,
        )

    def _query_telemetry_range(
        self, store_id: str, device_id: str, start: datetime, end: datetime
    ) -> List[Dict]:
        """查询时间范围内的遥测数据。"""
        sql = """
            SELECT * FROM iot_readings
            WHERE store_id = ? AND device_id = ?
              AND reading_at >= ? AND reading_at <= ?
            ORDER BY reading_at ASC
        """
        cursor = self._db.execute(sql, (
            store_id, device_id,
            start.isoformat(), end.isoformat(),
        ))
        columns = [desc[0] for desc in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]

    def _emit_iot_alert(
        self, store_id: str, device_id: str, violation: Dict[str, Any]
    ) -> None:
        """发送 IoT 超限告警。"""
        if self._alerts is None:
            return
        try:
            alert_id = str(uuid.uuid4())
            side = violation.get("violated_side", "high")
            level = "critical" if side == "high" else "warn"
            summary = (
                f"设备 {device_id} 温度{'超高' if side == 'high' else '过低'}: "
                f"{violation['value']}°C "
                f"(阈值 [{violation['min_threshold']}, {violation['max_threshold']}])"
            )
            payload = {
                "alert_id": alert_id,
                "alert_type": "temp_exceeded",
                "level": level,
                "source": "iot",
                "store_id": store_id,
                "summary": summary,
                "detail": violation,
                "created_at": datetime.utcnow().isoformat(),
            }
            if hasattr(self._alerts, "emit"):
                self._alerts.emit(payload)
            logger.warning("IoT温度告警: %s", summary)
        except Exception as e:
            logger.error("IoT告警发送失败: %s", e)
