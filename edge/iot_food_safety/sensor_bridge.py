"""Collect food-safety sensor readings and forward them to Hub."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import httpx

from edge.front_hall.bridge.store_forward import StoreAndForwardBuffer
from edge.iot_food_safety.rules import AlertCooldown, evaluate_readings, merge_thresholds, utc_now_iso
from edge.iot_food_safety.sensor_driver import SensorDriver


DEFAULT_HUB_ENDPOINT = "/iot"
DEFAULT_ALERT_ENDPOINT = "/events"


class SensorBridge:
    """Collect readings, evaluate alerts, and post snapshots with offline safety."""

    def __init__(
        self,
        sensors: Iterable[SensorDriver],
        store_id: str,
        device_id: str,
        hub_url: str,
        api_key: str = "",
        thresholds: Optional[Dict[str, Any]] = None,
        buffer_path: Optional[Any] = None,
        inference_buffer: Optional[Any] = None,
    ) -> None:
        self.sensors = list(sensors)
        self.store_id = store_id
        self.device_id = device_id
        self.hub_url = hub_url.rstrip("/")
        self.api_key = api_key
        self.thresholds = merge_thresholds(thresholds)
        self.cooldown = AlertCooldown(float(self.thresholds.get("alert_cooldown_sec", 300)))
        default_buffer = Path(os.environ.get("HOTPOT_BUFFER_DIR", "/tmp/hotpot_buffer")) / "iot_food_safety.jsonl"
        self.buffer = StoreAndForwardBuffer(buffer_path or default_buffer)
        self.inference_buffer = inference_buffer
        self.last_readings: List[Dict[str, Any]] = []
        self.last_alerts: List[Dict[str, Any]] = []

    async def collect_once(self) -> Dict[str, Any]:
        """Read all sensors once and return a Hub-ready snapshot payload."""
        readings: List[Dict[str, Any]] = []
        errors: List[Dict[str, str]] = []
        results = await asyncio.gather(*(sensor.read() for sensor in self.sensors), return_exceptions=True)
        for sensor, result in zip(self.sensors, results):
            if isinstance(result, Exception):
                errors.append({"sensor_id": sensor.sensor_id, "error": str(result)})
                continue
            readings.append(result)

        alerts = self.format_alerts(evaluate_readings(readings, self.thresholds, self.cooldown))
        self.last_readings = readings
        self.last_alerts = alerts
        return self._snapshot(readings, alerts, errors)

    def format_alerts(self, alerts: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Convert rule alerts into platform event payloads."""
        formatted: List[Dict[str, Any]] = []
        for alert in alerts:
            formatted.append(
                {
                    "event_type": alert.get("alert_type", "iot_food_safety_alert"),
                    "source": "iot",
                    "level": alert.get("level", "warn"),
                    "store_id": self.store_id,
                    "device_id": self.device_id,
                    "zone": "kitchen",
                    "message": alert.get("message", "食安 IoT 告警"),
                    "timestamp": alert.get("timestamp", utc_now_iso()),
                    "metadata": alert.get("metadata", {}),
                }
            )
        return formatted

    async def collect_and_forward(self) -> Dict[str, Any]:
        """Collect one batch, enqueue/post snapshot and alerts, then replay buffered data."""
        snapshot = await self.collect_once()
        await self.forward(snapshot)
        return snapshot

    async def forward(self, snapshot: Dict[str, Any]) -> Dict[str, Any]:
        """Post readings and alerts to Hub with store-and-forward fallback."""
        queued = 0
        sent = 0
        if self.inference_buffer is not None:
            await self.inference_buffer.enqueue(DEFAULT_HUB_ENDPOINT, snapshot, store_id=self.store_id)
            queued += 1
            for alert in snapshot.get("alerts", []):
                await self.inference_buffer.enqueue(DEFAULT_ALERT_ENDPOINT, alert, store_id=self.store_id)
                queued += 1
            return {"queued": queued, "sent": sent, "buffer": "sqlite"}

        items = [(DEFAULT_HUB_ENDPOINT, snapshot)] + [
            (DEFAULT_ALERT_ENDPOINT, alert) for alert in snapshot.get("alerts", [])
        ]
        for endpoint, payload in items:
            envelope = {"endpoint": endpoint, "payload": payload}
            if await self._post(endpoint, payload):
                sent += 1
            else:
                self.buffer.enqueue(envelope)
                queued += 1
        replayed = await self.replay_buffer()
        return {"queued": queued, "sent": sent, "replayed": replayed, "buffer": "jsonl"}

    async def replay_buffer(self) -> int:
        """Replay JSONL buffered Hub posts."""
        def _sink(item: Dict[str, Any]) -> bool:
            endpoint = item.get("endpoint", DEFAULT_HUB_ENDPOINT)
            payload = item.get("payload", item)
            return self._post_sync(endpoint, payload)

        return self.buffer.replay(_sink)

    async def _post(self, endpoint: str, payload: Dict[str, Any]) -> bool:
        if not self.hub_url:
            return False
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["X-Api-Key"] = self.api_key
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(10.0)) as client:
                resp = await client.post(f"{self.hub_url}{endpoint}", json=payload, headers=headers)
            return 200 <= resp.status_code < 300
        except Exception:
            return False

    def _post_sync(self, endpoint: str, payload: Dict[str, Any]) -> bool:
        if not self.hub_url:
            return False
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["X-Api-Key"] = self.api_key
        try:
            with httpx.Client(timeout=httpx.Timeout(10.0)) as client:
                resp = client.post(f"{self.hub_url}{endpoint}", json=payload, headers=headers)
            return 200 <= resp.status_code < 300
        except Exception:
            return False

    def _snapshot(
        self,
        readings: List[Dict[str, Any]],
        alerts: List[Dict[str, Any]],
        errors: List[Dict[str, str]],
    ) -> Dict[str, Any]:
        by_type: Dict[str, int] = {}
        for reading in readings:
            rtype = str(reading.get("type", "unknown"))
            by_type[rtype] = by_type.get(rtype, 0) + 1
        return {
            "store_id": self.store_id,
            "device_id": self.device_id,
            "module": "iot_food_safety",
            "updated_at": utc_now_iso(),
            "readings": readings,
            "alerts": alerts,
            "errors": errors,
            "summary": {
                "sensor_count": len(self.sensors),
                "reading_count": len(readings),
                "error_count": len(errors),
                "alert_count": len(alerts),
                "readings_by_type": by_type,
            },
        }


def snapshot_to_json(snapshot: Dict[str, Any]) -> str:
    """Serialize a snapshot for logs or CLI output."""
    return json.dumps(snapshot, ensure_ascii=False, separators=(",", ":"))
