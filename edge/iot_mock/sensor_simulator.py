#!/usr/bin/env python3
"""MQTT IoT sensor simulator for hotpot cold chain and gas monitoring."""

from __future__ import annotations

import argparse
import json
import random
import sys
import time
import urllib.request
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from shared.schemas import EventLevel, EventSource, OpsEvent, utc_now_iso

try:
    import paho.mqtt.client as mqtt
except ImportError:
    mqtt = None  # type: ignore


SENSORS = {
    "cold_storage_1": {"type": "temperature", "normal_range": (-22, -15), "unit": "C"},
    "cold_storage_2": {"type": "temperature", "normal_range": (0, 4), "unit": "C"},
    "prep_room": {"type": "temperature", "normal_range": (15, 25), "unit": "C"},
    "gas_main": {"type": "gas", "normal_range": (0, 50), "unit": "ppm"},
}


def reading_to_event(store_id: str, sensor_id: str, value: float, anomaly: bool) -> OpsEvent | None:
    cfg = SENSORS[sensor_id]
    if cfg["type"] == "temperature":
        lo, hi = cfg["normal_range"]
        if value > hi:
            return OpsEvent(
                event_type="cold_chain_high",
                source=EventSource.IOT.value,
                level=EventLevel.CRITICAL.value if value > hi + 5 else EventLevel.WARN.value,
                store_id=store_id,
                zone="kitchen",
                message=f"{sensor_id} 温度异常: {value:.1f}°C (正常 {lo}~{hi}°C)",
                metadata={"sensor_id": sensor_id, "value": value, "unit": "C"},
            )
        if value < lo:
            return OpsEvent(
                event_type="cold_chain_low",
                source=EventSource.IOT.value,
                level=EventLevel.WARN.value,
                store_id=store_id,
                zone="kitchen",
                message=f"{sensor_id} 温度过低: {value:.1f}°C",
                metadata={"sensor_id": sensor_id, "value": value, "unit": "C"},
            )
    elif cfg["type"] == "gas" and (anomaly or value > cfg["normal_range"][1]):
        return OpsEvent(
            event_type="gas_leak",
            source=EventSource.IOT.value,
            level=EventLevel.CRITICAL.value,
            store_id=store_id,
            zone="kitchen",
            message=f"燃气浓度异常: {value:.0f} ppm",
            metadata={"sensor_id": sensor_id, "value": value, "unit": "ppm"},
        )
    return None


def generate_reading(sensor_id: str, force_anomaly: bool = False) -> tuple[float, bool]:
    cfg = SENSORS[sensor_id]
    lo, hi = cfg["normal_range"]
    mid = (lo + hi) / 2
    if force_anomaly:
        if cfg["type"] == "gas":
            return random.uniform(hi + 20, hi + 100), True
        return hi + random.uniform(3, 10), True
    return mid + random.uniform(-1, 1), False


def post_to_hub(hub_url: str, event: OpsEvent) -> None:
    req = urllib.request.Request(
        hub_url.rstrip("/") + "/events",
        data=json.dumps(event.to_dict()).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    urllib.request.urlopen(req, timeout=5)


def run_mqtt(
    broker: str,
    port: int,
    store_id: str,
    hub_url: str,
    interval: float,
    cycles: int,
    inject_anomaly: bool,
) -> None:
    if mqtt is None:
        raise RuntimeError("paho-mqtt not installed. Run: pip install paho-mqtt")

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"hotpot_iot_{store_id}")
    topic_base = f"hotpot/{store_id}/sensors"

    def on_connect(client, userdata, flags, reason_code, properties=None):
        print(f"[MQTT] Connected to {broker}:{port}")

    client.on_connect = on_connect
    client.connect(broker, port, 60)
    client.loop_start()

    anomaly_at = cycles // 2 if inject_anomaly and cycles > 2 else -1

    for i in range(cycles):
        for sensor_id in SENSORS:
            force = i == anomaly_at and sensor_id in ("cold_storage_1", "gas_main")
            value, is_anomaly = generate_reading(sensor_id, force_anomaly=force)
            payload = {
                "store_id": store_id,
                "sensor_id": sensor_id,
                "value": round(value, 2),
                "timestamp": utc_now_iso(),
            }
            topic = f"{topic_base}/{sensor_id}"
            client.publish(topic, json.dumps(payload))
            print(f"[MQTT] {topic} -> {payload['value']}")

            if hub_url:
                ev = reading_to_event(store_id, sensor_id, value, is_anomaly)
                if ev:
                    post_to_hub(hub_url, ev)
                    print(f"[HUB] Alert: {ev.event_type} - {ev.message}")

        time.sleep(interval)

    client.loop_stop()
    client.disconnect()


def run_direct(hub_url: str, store_id: str, cycles: int, inject_anomaly: bool) -> None:
    """Fallback without MQTT broker."""
    anomaly_at = 1 if inject_anomaly else -1
    for i in range(cycles):
        for sensor_id in SENSORS:
            force = i == anomaly_at and sensor_id == "cold_storage_1"
            value, is_anomaly = generate_reading(sensor_id, force_anomaly=force)
            ev = reading_to_event(store_id, sensor_id, value, is_anomaly)
            if ev and hub_url:
                post_to_hub(hub_url, ev)
                print(f"[HUB] {ev.event_type}: {ev.message}")
        time.sleep(0.5)


def main() -> None:
    parser = argparse.ArgumentParser(description="Hotpot IoT sensor simulator")
    parser.add_argument("--store-id", default="store_yuhuan")
    parser.add_argument("--hub-url", default="http://127.0.0.1:8088")
    parser.add_argument("--mqtt-broker", default="", help="MQTT broker host; empty = direct HTTP mode")
    parser.add_argument("--mqtt-port", type=int, default=1883)
    parser.add_argument("--interval", type=float, default=2.0)
    parser.add_argument("--cycles", type=int, default=3)
    parser.add_argument("--inject-anomaly", action="store_true")
    args = parser.parse_args()

    if args.mqtt_broker:
        run_mqtt(
            args.mqtt_broker,
            args.mqtt_port,
            args.store_id,
            args.hub_url,
            args.interval,
            args.cycles,
            args.inject_anomaly,
        )
    else:
        run_direct(args.hub_url, args.store_id, args.cycles, args.inject_anomaly)


if __name__ == "__main__":
    main()
