#!/usr/bin/env python3
"""MQTT → Event Hub bridge (DEV-205). Subscribes sensor topics and forwards to Hub."""

from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from edge.iot_mock.iot_rules import DoorTimeoutTracker, level_for_sensor
from edge.store_forward import StoreAndForwardBuffer
from shared.hub_client import EdgeHubClient
from shared.schemas import EventSource, utc_now_iso
from shared.store_config import DEFAULT_UAT_ROOT, uat_dir

try:
    import paho.mqtt.client as mqtt
except ImportError:
    mqtt = None  # type: ignore


def load_mqtt_topics(store_id: str, uat_root: Path) -> Dict[str, Any]:
    path = uat_dir(store_id, uat_root) / "mqtt_topics.json"
    if not path.exists():
        return {"store_id": store_id, "sensors": []}
    return json.loads(path.read_text(encoding="utf-8"))


def _level_for_reading(sensor_type: str, value: Any, thresholds: Dict[str, Any]) -> str:
    return level_for_sensor(sensor_type, value, thresholds)


def parse_payload(topic_cfg: Dict[str, Any], payload: bytes) -> Optional[Dict[str, Any]]:
    try:
        data = json.loads(payload.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        raw = payload.decode("utf-8", errors="replace").strip()
        try:
            data = {"value": float(raw)}
        except ValueError:
            data = {"value": raw}
    if isinstance(data, dict):
        value = data.get("value", data.get("reading"))
    else:
        value = data
    if value is None:
        return None
    return {
        "sensor_id": topic_cfg.get("sensor_id", ""),
        "type": topic_cfg.get("type", "unknown"),
        "unit": topic_cfg.get("unit", ""),
        "value": value,
        "raw": data if isinstance(data, dict) else {"value": value},
    }


class MqttHubBridge:
    def __init__(
        self,
        store_id: str,
        hub_url: str,
        broker_url: str,
        topics_cfg: Dict[str, Any],
        thresholds: Optional[Dict[str, Any]] = None,
        buffer_path: Optional[Any] = None,
    ) -> None:
        self.store_id = store_id
        self.hub = EdgeHubClient(hub_url, store_id)
        self.broker_url = broker_url
        self.sensors: List[Dict[str, Any]] = topics_cfg.get("sensors", [])
        self.topic_map = {s["topic"]: s for s in self.sensors if s.get("topic")}
        self.thresholds = thresholds or {}
        self._readings: Dict[str, Any] = {}
        self._lock = threading.Lock()
        self._client: Optional[Any] = None
        self._door_tracker = DoorTimeoutTracker(
            timeout_sec=float(self.thresholds.get("door_open_timeout_sec", 180))
        )
        # store-and-forward: buffer events when the Hub is unreachable (LOSS-502)
        default_buf = PROJECT_ROOT / ".iot_buffer" / f"{store_id}.jsonl"
        self.buffer = StoreAndForwardBuffer(buffer_path or default_buf)

    def _try_post(self, event: Dict[str, Any]) -> bool:
        try:
            if hasattr(self.hub, "try_post_event"):
                return bool(self.hub.try_post_event(event))
            result = self.hub.post_event(event)
            return True if result is None else bool(result)
        except Exception:
            return False

    def _forward(self, event: Dict[str, Any]) -> None:
        """Post to Hub; buffer locally (replay-safe) on failure so no reading is lost."""
        if not self._try_post(event):
            self.buffer.enqueue(event)

    def replay_buffer(self) -> int:
        """Re-deliver buffered events; returns count delivered this pass."""
        return self.buffer.replay(self._try_post)

    def _on_message(self, _client: Any, _userdata: Any, msg: Any) -> None:
        cfg = self.topic_map.get(msg.topic)
        if not cfg:
            return
        parsed = parse_payload(cfg, msg.payload)
        if not parsed:
            return
        sid = parsed["sensor_id"]
        stype = parsed["type"]
        with self._lock:
            self._readings[sid] = parsed

        level = _level_for_reading(stype, parsed["value"], self.thresholds)
        parsed["level"] = level

        if stype == "door":
            door_ev = self._door_tracker.on_reading(
                sid, parsed["value"], store_id=self.store_id, zone="kitchen"
            )
            if door_ev:
                self._forward(door_ev)

        event = {
            "event_type": f"iot_{stype}_reading" if stype != "door" else "iot_door_reading",
            "source": EventSource.IOT.value,
            "level": level,
            "store_id": self.store_id,
            "zone": "kitchen",
            "message": f"IoT {sid}: {parsed['value']}{parsed['unit']}",
            "timestamp": utc_now_iso(),
            "metadata": parsed,
        }
        self._forward(event)

    def _post_iot_stats(self) -> None:
        with self._lock:
            readings = dict(self._readings)
        if not readings:
            return
        alerts = sum(1 for r in readings.values() if r.get("level") in ("warn", "critical"))
        stats = {
            "store_id": self.store_id,
            "updated_at": utc_now_iso(),
            "stage_readings": readings,
            "summary": {"sensor_count": len(readings), "iot_alert_count": alerts},
        }
        self.hub.post("/iot", stats)

    def run(self, cycles: int = 0, flush_interval: float = 30.0) -> None:
        if mqtt is None:
            raise RuntimeError("paho-mqtt not installed")

        host, port = self._parse_broker(self.broker_url)
        client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id=f"hotpot_bridge_{self.store_id}",
        )
        client.on_message = self._on_message
        client.reconnect_delay_set(min_delay=1, max_delay=60)  # auto-reconnect on broker drop
        client.connect(host, port, keepalive=60)
        for topic in self.topic_map:
            client.subscribe(topic)
            print(f"[mqtt_bridge] subscribe {topic}")
        client.loop_start()
        self._client = client

        tick = 0
        try:
            while cycles == 0 or tick < cycles:
                time.sleep(flush_interval)
                self.replay_buffer()  # re-deliver readings buffered during outages
                self._post_iot_stats()
                self.hub.flush_queue()
                tick += 1
        finally:
            client.loop_stop()
            client.disconnect()

    @staticmethod
    def _parse_broker(url: str) -> tuple:
        url = url.replace("mqtt://", "").replace("mqtts://", "")
        if ":" in url:
            host, port_s = url.rsplit(":", 1)
            return host, int(port_s)
        return url, 1883


def run_mock_publish(store_id: str, broker_url: str, uat_root: Path, cycles: int = 3) -> None:
    """Publish mock sensor readings when no real devices (demo mode)."""
    if mqtt is None:
        raise RuntimeError("paho-mqtt not installed")
    cfg = load_mqtt_topics(store_id, uat_root)
    host, port = MqttHubBridge._parse_broker(broker_url)
    client = mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION2)
    client.connect(host, port, keepalive=60)
    client.loop_start()
    import random

    for i in range(cycles):
        for sensor in cfg.get("sensors", []):
            topic = sensor["topic"]
            stype = sensor.get("type", "temperature")
            if stype == "temperature":
                value = random.uniform(-20, -16)
            elif stype == "weight":
                value = round(random.uniform(8, 12), 2)
            elif stype == "gas":
                value = random.uniform(0, 30)
            elif stype == "door":
                value = 0
            else:
                value = random.random()
            payload = json.dumps({"value": value, "sensor_id": sensor["sensor_id"]})
            client.publish(topic, payload)
        time.sleep(1)
    client.loop_stop()
    client.disconnect()
    print(f"[mqtt_bridge] mock published {cycles} cycle(s) for {store_id}")


def main() -> None:
    parser = argparse.ArgumentParser(description="MQTT IoT bridge → Event Hub")
    parser.add_argument("--store-id", default="store_yuhuan")
    parser.add_argument("--hub-url", default="http://127.0.0.1:8088")
    parser.add_argument("--broker", default="mqtt://127.0.0.1:1883")
    parser.add_argument("--uat-root", default=str(DEFAULT_UAT_ROOT))
    parser.add_argument("--cycles", type=int, default=0, help="0 = run forever")
    parser.add_argument("--mock-publish", action="store_true", help="Publish mock readings to broker")
    args = parser.parse_args()

    uat_root = Path(args.uat_root)
    topics_cfg = load_mqtt_topics(args.store_id, uat_root)

    if args.mock_publish:
        run_mock_publish(args.store_id, args.broker, uat_root, cycles=3)
        return

    config_path = uat_dir(args.store_id, uat_root) / "config.json"
    thresholds = {}
    if config_path.exists():
        thresholds = json.loads(config_path.read_text(encoding="utf-8")).get("alert_thresholds", {})

    bridge = MqttHubBridge(
        args.store_id,
        args.hub_url,
        args.broker,
        topics_cfg,
        thresholds=thresholds,
    )
    print(f"[mqtt_bridge] {args.store_id} → {args.hub_url} via {args.broker}")
    bridge.run(cycles=args.cycles)


if __name__ == "__main__":
    main()
