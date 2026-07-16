"""MQTT electronic scale simulator for receiving dock.

Simulates a smart scale publishing weight readings via MQTT.
Supports mock (random) and replay (CSV) modes.

Topics:  hotpot/{store_id}/scale/{scale_id}
Payload: {"scale_id":"scale_receiving_01","weight_kg":23.5,"unit":"kg","timestamp":"...","stable":true}

Dependencies: paho-mqtt (pip install paho-mqtt)

Usage:
  PYTHONPATH=. python3 -m edge.receiving.mqtt_scale_sim --store-id store_yuhuan --mode mock
  PYTHONPATH=. python3 -m edge.receiving.mqtt_scale_sim --store-id store_yuhuan --mode replay --csv demo/data/scale_samples.csv
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import os
import random
import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("receiving.mqtt_scale")

# ── Defaults ──
DEFAULT_BROKER = os.environ.get("MQTT_BROKER", "127.0.0.1")
DEFAULT_PORT = int(os.environ.get("MQTT_PORT", "1883"))
DEFAULT_SCALE_ID = "scale_receiving_01"
DEFAULT_INTERVAL = float(os.environ.get("SCALE_INTERVAL", "2.0"))

PROJECT_ROOT = Path(__file__).resolve().parents[2]

# ── Try import paho-mqtt ──
try:
    import paho.mqtt.client as mqtt  # type: ignore
    HAS_MQTT = True
except ImportError:
    HAS_MQTT = False
    logger.warning("paho-mqtt not installed — MQTT disabled, will print to stdout")


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


class MockScale:
    """Simulates a scale with realistic weight fluctuation → stabilization."""

    def __init__(self, target_kg: float = 25.0, noise: float = 0.5):
        self.target = target_kg
        self.noise = noise
        self.stable = False
        self._stable_count = 0
        self._current = target_kg + random.uniform(-5, 5)

    def read(self) -> Dict[str, Any]:
        # Random walk toward target
        drift = (self.target - self._current) * 0.3 + random.gauss(0, self.noise)
        self._current += drift
        self._current = round(self._current, 2)

        # Stable detection: within ±0.1kg for 3+ consecutive reads
        if abs(self._current - self.target) < 0.15:
            self._stable_count += 1
        else:
            self._stable_count = 0
        self.stable = self._stable_count >= 3

        return {
            "scale_id": DEFAULT_SCALE_ID,
            "weight_kg": self._current,
            "unit": "kg",
            "timestamp": utc_now_iso(),
            "stable": self.stable,
        }


class ReplayScale:
    """Replays scale readings from a CSV file (columns: weight_kg)."""

    def __init__(self, csv_path: str):
        self._rows: List[float] = []
        self._idx = 0
        with open(csv_path, newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                try:
                    self._rows.append(float(row.get("weight_kg", 0)))
                except (ValueError, TypeError):
                    pass
        if not self._rows:
            self._rows = [25.0, 24.8, 24.6, 24.5]
        logger.info("Loaded %d scale readings from %s", len(self._rows), csv_path)

    def read(self) -> Dict[str, Any]:
        kg = self._rows[self._idx % len(self._rows)]
        self._idx += 1
        return {
            "scale_id": DEFAULT_SCALE_ID,
            "weight_kg": kg,
            "unit": "kg",
            "timestamp": utc_now_iso(),
            "stable": self._idx > 2,
        }


class MQTTPublisher:
    """Minimal MQTT publisher wrapping paho-mqtt."""

    def __init__(self, broker: str, port: int, topic: str):
        self.topic = topic
        if not HAS_MQTT:
            self._client = None
            logger.warning("MQTT disabled — printing to stdout")
            return
        self._client = mqtt.Client(client_id=f"scale-sim-{os.getpid()}")
        self._client.on_connect = self._on_connect
        try:
            self._client.connect(broker, port, keepalive=60)
            self._client.loop_start()
        except Exception as e:
            logger.error("MQTT connect failed: %s", e)
            self._client = None

    def _on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            logger.info("MQTT connected to broker")
        else:
            logger.error("MQTT connection failed, rc=%d", rc)

    def publish(self, payload: dict):
        msg = json.dumps(payload, ensure_ascii=False)
        if self._client:
            self._client.publish(self.topic, msg, qos=1)
            logger.debug("MQTT → %s: %s", self.topic, msg)
        else:
            print(f"[MQTT-DRY] {self.topic}: {msg}")

    def close(self):
        if self._client:
            self._client.loop_stop()
            self._client.disconnect()


def main():
    parser = argparse.ArgumentParser(description="MQTT electronic scale simulator")
    parser.add_argument("--store-id", default="store_yuhuan")
    parser.add_argument("--scale-id", default=DEFAULT_SCALE_ID)
    parser.add_argument("--broker", default=DEFAULT_BROKER)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--mode", choices=["mock", "replay"], default="mock")
    parser.add_argument("--csv", help="CSV file path for replay mode")
    parser.add_argument("--target-kg", type=float, default=25.0, help="Target weight for mock mode")
    parser.add_argument("--interval", type=float, default=DEFAULT_INTERVAL)
    parser.add_argument("--count", type=int, default=0, help="Number of readings (0=unlimited)")

    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    topic = f"hotpot/{args.store_id}/scale/{args.scale_id}"

    if args.mode == "replay":
        csv_path = args.csv or str(PROJECT_ROOT / "demo" / "data" / "scale_samples.csv")
        scale = ReplayScale(csv_path)
    else:
        scale = MockScale(target_kg=args.target_kg)

    publisher = MQTTPublisher(args.broker, args.port, topic)

    running = True

    def _shutdown(sig, frame):
        nonlocal running
        running = False

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    logger.info("Scale simulator started — topic=%s mode=%s broker=%s:%d",
                 topic, args.mode, args.broker, args.port)

    count = 0
    while running:
        reading = scale.read()
        publisher.publish(reading)

        status = "◉ 稳定" if reading["stable"] else "~ 波动"
        logger.info("%s %.2f kg %s", status, reading["weight_kg"],
                     f"(#{count+1})" if args.count else "")

        count += 1
        if args.count and count >= args.count:
            break
        time.sleep(args.interval)

    publisher.close()
    logger.info("Scale simulator stopped after %d readings", count)


if __name__ == "__main__":
    main()
