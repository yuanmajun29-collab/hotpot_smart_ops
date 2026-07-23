"""Networked ingredient receiving scale driver.

Supports development mock readings via ``MOCK_SCALE=1`` and production reads
from either MQTT last-value topics or a simple TCP electronic scale endpoint.
The driver applies local tare, compares actual vs expected weight, and pushes
weight events to Hub.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import random
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import httpx

logger = logging.getLogger("receiving.ingredient_scale")

HUB_URL = os.environ.get("HOTPOT_HUB_URL", "http://127.0.0.1:8098")
STORE_ID = os.environ.get("HOTPOT_STORE_ID", "store_yuhuan")
DEVICE_ID = os.environ.get("HOTPOT_DEVICE_ID", "jetson-receiving-01")
API_KEY = os.environ.get("HOTPOT_API_KEY", "demo-key")

DEFAULT_SCALE_ID = os.environ.get("RECEIVING_SCALE_ID", "scale_receiving_01")
DEFAULT_TOPIC = os.environ.get("SCALE_MQTT_TOPIC", f"hotpot/{STORE_ID}/scale/{DEFAULT_SCALE_ID}")
DEVIATION_THRESHOLD = float(os.environ.get("RECEIVING_WEIGHT_DEVIATION_THRESHOLD", "0.10"))


def utc_now_iso() -> str:
    """Return current UTC timestamp without microseconds."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@dataclass
class ScaleReading:
    """Normalized electronic scale reading."""

    scale_id: str
    gross_weight_kg: float
    net_weight_kg: float
    tare_kg: float
    stable: bool
    timestamp: str
    source: str
    unit: str = "kg"
    raw: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize reading for API responses and Hub payloads."""
        return {
            "scale_id": self.scale_id,
            "gross_weight_kg": self.gross_weight_kg,
            "net_weight_kg": self.net_weight_kg,
            "tare_kg": self.tare_kg,
            "stable": self.stable,
            "timestamp": self.timestamp,
            "source": self.source,
            "unit": self.unit,
            "raw": self.raw,
        }


def compare_weight(actual_kg: float, expected_kg: Optional[float]) -> Dict[str, Any]:
    """Compare actual and expected weights and flag deviations over threshold."""
    if expected_kg is None or expected_kg <= 0:
        return {
            "expected_weight_kg": expected_kg,
            "actual_weight_kg": actual_kg,
            "deviation_kg": None,
            "deviation_pct": None,
            "deviation_flag": False,
            "threshold_pct": round(DEVIATION_THRESHOLD * 100, 2),
        }

    deviation_kg = actual_kg - expected_kg
    deviation_pct = deviation_kg / expected_kg
    return {
        "expected_weight_kg": round(expected_kg, 3),
        "actual_weight_kg": round(actual_kg, 3),
        "deviation_kg": round(deviation_kg, 3),
        "deviation_pct": round(deviation_pct * 100, 2),
        "deviation_flag": abs(deviation_pct) > DEVIATION_THRESHOLD,
        "threshold_pct": round(DEVIATION_THRESHOLD * 100, 2),
    }


class IngredientScaleDriver:
    """Read receiving-scale weights from mock, MQTT, or TCP sources."""

    def __init__(
        self,
        scale_id: str = DEFAULT_SCALE_ID,
        source: Optional[str] = None,
        mqtt_topic: str = DEFAULT_TOPIC,
        tcp_host: Optional[str] = None,
        tcp_port: Optional[int] = None,
    ) -> None:
        self.scale_id = scale_id
        self.source = (source or os.environ.get("SCALE_SOURCE") or "mock").lower()
        self.mqtt_topic = mqtt_topic
        self.tcp_host = tcp_host or os.environ.get("SCALE_TCP_HOST")
        self.tcp_port = tcp_port or int(os.environ.get("SCALE_TCP_PORT", "4001"))
        self.tare_kg = float(os.environ.get("SCALE_TARE_KG", "0"))
        self._last_mqtt_payload: Optional[Dict[str, Any]] = None
        self._mqtt_client = None
        self._mock_weight = float(os.environ.get("MOCK_SCALE_WEIGHT_KG", "25.0"))

        if os.environ.get("MOCK_SCALE") == "1":
            self.source = "mock"

    def tare(self, gross_weight_kg: Optional[float] = None) -> float:
        """Set tare to the provided gross weight or the latest synchronous read."""
        if gross_weight_kg is None:
            gross_weight_kg = self._read_mock_gross()
        self.tare_kg = round(max(float(gross_weight_kg), 0.0), 3)
        return self.tare_kg

    async def read_weight(self) -> ScaleReading:
        """Read one scale value and return gross/net weight with tare applied."""
        if self.source == "mqtt":
            gross, stable, raw = await self._read_mqtt()
        elif self.source == "tcp":
            gross, stable, raw = await self._read_tcp()
        else:
            gross, stable, raw = await self._read_mock()

        net = round(max(gross - self.tare_kg, 0.0), 3)
        return ScaleReading(
            scale_id=str(raw.get("scale_id") or self.scale_id),
            gross_weight_kg=round(gross, 3),
            net_weight_kg=net,
            tare_kg=round(self.tare_kg, 3),
            stable=stable,
            timestamp=str(raw.get("timestamp") or utc_now_iso()),
            source=self.source,
            unit=str(raw.get("unit") or "kg"),
            raw=raw,
        )

    async def read_and_compare(self, expected_weight_kg: Optional[float]) -> Dict[str, Any]:
        """Read current net weight and compare it with expected receiving weight."""
        reading = await self.read_weight()
        comparison = compare_weight(reading.net_weight_kg, expected_weight_kg)
        return {"reading": reading.to_dict(), "comparison": comparison}

    async def post_weight_event(
        self,
        reading: ScaleReading,
        expected_weight_kg: Optional[float] = None,
        batch_ref: Optional[str] = None,
        sku: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Best-effort POST of a weight event to Hub receiving checkin API."""
        comparison = compare_weight(reading.net_weight_kg, expected_weight_kg)
        ingredients = [{"class_name": sku or "食材", "count": 1, "confidence": 1.0}]
        payload: Dict[str, Any] = {
            "store_id": STORE_ID,
            "device_id": DEVICE_ID,
            "ingredients": ingredients,
            "source": f"edge_scale_{reading.source}",
            "timestamp": reading.timestamp,
            "weight_kg": reading.net_weight_kg,
            "po_weight_kg": expected_weight_kg,
            "batch_ref": batch_ref,
            "scale": reading.to_dict(),
            "weight_check": comparison,
        }
        payload = {k: v for k, v in payload.items() if v is not None}

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(
                    f"{HUB_URL}/v1/receiving/checkin",
                    json=payload,
                    headers={"X-Api-Key": API_KEY, "Content-Type": "application/json"},
                )
                resp.raise_for_status()
                return resp.json()
        except Exception as exc:
            logger.warning("weight event push failed: %s", exc)
            return {"ok": False, "error": str(exc)}

    async def _read_mock(self) -> Any:
        await asyncio.sleep(0)
        gross = self._read_mock_gross()
        return gross, True, {
            "scale_id": self.scale_id,
            "weight_kg": gross,
            "unit": "kg",
            "stable": True,
            "timestamp": utc_now_iso(),
            "mock": True,
        }

    def _read_mock_gross(self) -> float:
        noise = float(os.environ.get("MOCK_SCALE_NOISE_KG", "0.08"))
        self._mock_weight += random.uniform(-noise, noise)
        return round(max(self._mock_weight, 0.0), 3)

    async def _read_tcp(self) -> Any:
        if not self.tcp_host:
            raise RuntimeError("SCALE_TCP_HOST is required for tcp scale source")

        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(self.tcp_host, self.tcp_port),
            timeout=float(os.environ.get("SCALE_TCP_TIMEOUT", "3.0")),
        )
        try:
            command = os.environ.get("SCALE_TCP_COMMAND", "READ\n").encode("utf-8")
            writer.write(command)
            await writer.drain()
            raw_line = await asyncio.wait_for(reader.readline(), timeout=3.0)
        finally:
            writer.close()
            await writer.wait_closed()

        raw_text = raw_line.decode("utf-8", errors="ignore").strip()
        payload = self._parse_weight_payload(raw_text)
        return float(payload["weight_kg"]), bool(payload.get("stable", True)), payload

    async def _read_mqtt(self) -> Any:
        if self._last_mqtt_payload is None:
            await self._ensure_mqtt_client()
            timeout_s = float(os.environ.get("SCALE_MQTT_WAIT_SEC", "5.0"))
            deadline = asyncio.get_event_loop().time() + timeout_s
            while self._last_mqtt_payload is None and asyncio.get_event_loop().time() < deadline:
                await asyncio.sleep(0.05)
        if self._last_mqtt_payload is None:
            raise TimeoutError(f"no MQTT scale reading on {self.mqtt_topic}")
        payload = self._last_mqtt_payload
        return float(payload["weight_kg"]), bool(payload.get("stable", True)), payload

    async def _ensure_mqtt_client(self) -> None:
        if self._mqtt_client is not None:
            return
        try:
            import paho.mqtt.client as mqtt  # type: ignore
        except ImportError as exc:
            raise RuntimeError("paho-mqtt is required for mqtt scale source") from exc

        broker = os.environ.get("MQTT_BROKER", "127.0.0.1")
        port = int(os.environ.get("MQTT_PORT", "1883"))
        client = mqtt.Client(client_id=f"receiving-scale-{os.getpid()}")

        def _on_message(_client: Any, _userdata: Any, msg: Any) -> None:
            try:
                self._last_mqtt_payload = self._parse_weight_payload(msg.payload.decode("utf-8"))
            except Exception as exc:
                logger.warning("invalid scale MQTT payload: %s", exc)

        client.on_message = _on_message
        client.connect(broker, port, keepalive=60)
        client.subscribe(self.mqtt_topic, qos=1)
        client.loop_start()
        self._mqtt_client = client

    def _parse_weight_payload(self, raw_text: str) -> Dict[str, Any]:
        """Parse JSON or plain numeric scale payloads into a dict."""
        try:
            payload = json.loads(raw_text)
            if not isinstance(payload, dict):
                raise ValueError("payload must be an object")
        except json.JSONDecodeError:
            payload = {"weight_kg": float(raw_text.split()[0])}

        weight = payload.get("weight_kg", payload.get("weight", payload.get("net")))
        if weight is None:
            raise ValueError(f"weight_kg missing in payload: {raw_text}")
        payload["weight_kg"] = float(weight)
        payload.setdefault("scale_id", self.scale_id)
        payload.setdefault("unit", "kg")
        payload.setdefault("stable", True)
        payload.setdefault("timestamp", utc_now_iso())
        return payload
