"""Food-safety sensor drivers for edge IoT collection.

Drivers expose a shared async ``read`` contract. Hardware access is optional and
lazy so deployments without Bluetooth or serial libraries can still run in mock
mode with ``MOCK_SENSORS=1``.
"""

from __future__ import annotations

import abc
import asyncio
import json
import os
import random
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional


def mock_sensors_enabled() -> bool:
    """Return whether drivers should use deterministic mock readings."""
    return os.environ.get("MOCK_SENSORS", "").strip().lower() in ("1", "true", "yes", "on")


def utc_now_iso() -> str:
    """Return a UTC ISO-8601 timestamp without microseconds."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


class SensorDriver(abc.ABC):
    """Abstract base class for food-safety sensors."""

    sensor_type = "unknown"
    unit = ""

    def __init__(self, sensor_id: str, location: str = "kitchen", mock: Optional[bool] = None) -> None:
        self.sensor_id = sensor_id
        self.location = location
        self.mock = mock_sensors_enabled() if mock is None else bool(mock)
        self._rng = random.Random(sensor_id)

    @abc.abstractmethod
    async def read(self) -> Dict[str, Any]:
        """Read one sensor sample and return a normalized dictionary."""

    async def close(self) -> None:
        """Release hardware resources. Most simple drivers are stateless."""
        return None

    def _base(self, value: Any, **extra: Any) -> Dict[str, Any]:
        data = {
            "sensor_id": self.sensor_id,
            "type": self.sensor_type,
            "location": self.location,
            "value": value,
            "unit": self.unit,
            "timestamp": utc_now_iso(),
        }
        data.update(extra)
        return data


class BluetoothTempSensor(SensorDriver):
    """Bluetooth temperature probe.

    Real hardware mode expects ``bleak`` and a BLE characteristic UUID. When no
    address/characteristic is configured, the driver falls back to mock readings.
    """

    sensor_type = "temperature"
    unit = "°C"

    def __init__(
        self,
        sensor_id: str,
        address: str = "",
        characteristic_uuid: str = "",
        location: str = "cold_storage",
        mock: Optional[bool] = None,
    ) -> None:
        super().__init__(sensor_id, location, mock)
        self.address = address
        self.characteristic_uuid = characteristic_uuid
        if not self.address or not self.characteristic_uuid:
            self.mock = True

    async def read(self) -> Dict[str, Any]:
        """Read Celsius temperature from BLE or mock generator."""
        if self.mock:
            await asyncio.sleep(0)
            value = round(self._rng.uniform(-20.5, -16.0), 1)
            return self._base(value, source="mock")

        try:
            from bleak import BleakClient  # type: ignore
        except ImportError as exc:
            raise RuntimeError("bleak is required for BluetoothTempSensor hardware mode") from exc

        try:
            async with BleakClient(self.address, timeout=8.0) as client:
                raw = await client.read_gatt_char(self.characteristic_uuid)
        except Exception as exc:
            raise RuntimeError(f"Bluetooth temperature read failed for {self.sensor_id}: {exc}") from exc
        return self._base(self._decode_temperature(raw), source="bluetooth")

    @staticmethod
    def _decode_temperature(raw: bytes) -> float:
        """Decode common little-endian signed centi-degree payloads."""
        if not raw:
            raise ValueError("empty BLE temperature payload")
        if len(raw) >= 2:
            return round(int.from_bytes(raw[:2], "little", signed=True) / 100.0, 2)
        return float(raw[0])


class TempHumiditySensor(SensorDriver):
    """Temperature + humidity probe using JSON file input, serial text, or mock."""

    sensor_type = "temp_humidity"
    unit = "°C/%RH"

    def __init__(
        self,
        sensor_id: str,
        location: str = "prep_area",
        serial_port: str = "",
        data_path: str = "",
        mock: Optional[bool] = None,
    ) -> None:
        super().__init__(sensor_id, location, mock)
        self.serial_port = serial_port
        self.data_path = data_path
        if not self.serial_port and not self.data_path:
            self.mock = True

    async def read(self) -> Dict[str, Any]:
        """Read temperature/humidity from file, serial line, or mock generator."""
        if self.mock:
            await asyncio.sleep(0)
            temp = round(self._rng.uniform(5.0, 11.5), 1)
            humidity = round(self._rng.uniform(45.0, 68.0), 1)
            return self._base(temp, humidity=humidity, source="mock")

        if self.data_path:
            try:
                payload = json.loads(Path(self.data_path).read_text(encoding="utf-8"))
            except Exception as exc:
                raise RuntimeError(f"temperature humidity file read failed: {exc}") from exc
            temp = float(payload.get("temperature", payload.get("temp_c", payload.get("value"))))
            humidity = float(payload.get("humidity", payload.get("humidity_pct")))
            return self._base(temp, humidity=humidity, raw=payload, source="file")

        try:
            import serial  # type: ignore
        except ImportError as exc:
            raise RuntimeError("pyserial is required for TempHumiditySensor serial mode") from exc

        def _read_line() -> str:
            with serial.Serial(self.serial_port, baudrate=9600, timeout=2) as port:
                return port.readline().decode("utf-8", errors="replace").strip()

        loop = asyncio.get_event_loop()
        line = await loop.run_in_executor(None, _read_line)
        payload = json.loads(line) if line.startswith("{") else self._parse_csv(line)
        temp = float(payload.get("temperature", payload.get("temp_c", payload.get("value"))))
        humidity = float(payload.get("humidity", payload.get("humidity_pct")))
        return self._base(temp, humidity=humidity, raw=payload, source="serial")

    @staticmethod
    def _parse_csv(line: str) -> Dict[str, float]:
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 2:
            raise ValueError(f"expected 'temp,humidity' serial payload, got: {line}")
        return {"temperature": float(parts[0]), "humidity": float(parts[1])}


class RFIDExpiryTracker(SensorDriver):
    """RFID batch expiry reader.

    Hardware mode reads a JSON file exported by a local RFID daemon. This keeps
    the driver pluggable without binding the project to one reader SDK.
    """

    sensor_type = "rfid_expiry"
    unit = "days"

    def __init__(
        self,
        sensor_id: str,
        location: str = "storage",
        data_path: str = "",
        mock: Optional[bool] = None,
    ) -> None:
        super().__init__(sensor_id, location, mock)
        self.data_path = data_path
        if not self.data_path:
            self.mock = True

    async def read(self) -> Dict[str, Any]:
        """Read RFID expiry metadata from JSON or mock generator."""
        if self.mock:
            await asyncio.sleep(0)
            days = self._rng.choice([0, 1, 2, 3, 5, 7])
            batch_id = f"BATCH-{self._rng.randint(1000, 9999)}"
            return self._base(
                days,
                tag_id=f"RFID-{self._rng.randint(100000, 999999)}",
                batch_id=batch_id,
                sku=self._rng.choice(["beef_roll", "lamb_roll", "tofu", "mushroom"]),
                days_remaining=days,
                source="mock",
            )

        try:
            payload = json.loads(Path(self.data_path).read_text(encoding="utf-8"))
        except Exception as exc:
            raise RuntimeError(f"RFID expiry file read failed: {exc}") from exc
        if isinstance(payload, list):
            payload = payload[0] if payload else {}
        days = int(payload.get("days_remaining", payload.get("value", 999)))
        return self._base(
            days,
            tag_id=payload.get("tag_id", payload.get("rfid", "")),
            batch_id=payload.get("batch_id", ""),
            sku=payload.get("sku", ""),
            days_remaining=days,
            raw=payload,
            source="file",
        )
