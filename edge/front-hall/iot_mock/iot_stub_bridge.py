#!/usr/bin/env python3
"""
IoT stub bridge — no MQTT broker / real devices required (BL-02 打桩).

Simulates sensor readings and posts directly to Event Hub:
  POST /events, POST /iot, POST /v1/iot/readings
Includes door-open >3min rule (DEV-413).
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from edge.iot_mock.iot_rules import DoorTimeoutTracker, level_for_sensor, parse_door_open
from edge.iot_mock.mqtt_bridge import load_mqtt_topics
from common.hub_client import EdgeHubClient
from common.schemas import EventSource, utc_now_iso
from common.store_config import DEFAULT_UAT_ROOT, load_store_config, uat_dir


SCENARIOS = ("normal", "door_alert", "temp_high")


def stub_value(
    sensor: Dict[str, Any],
    scenario: str,
    *,
    cycle: int,
    door_forced_open: bool,
) -> Any:
    stype = sensor.get("type", "unknown")
    sid = sensor.get("sensor_id", "")

    if stype == "door":
        if scenario == "door_alert" or door_forced_open:
            return 1
        return 0

    if stype == "temperature":
        if scenario == "temp_high":
            return round(random.uniform(-12, -8), 1)
        return round(random.uniform(-20, -16), 1)

    if stype == "weight":
        return round(random.uniform(8, 12), 2)

    if stype == "gas":
        return round(random.uniform(0, 25), 1)

    return round(random.random(), 3)


class IotStubBridge:
    """Direct-to-Hub IoT simulator (no MQTT)."""

    def __init__(
        self,
        store_id: str,
        hub_url: str,
        uat_root: Path,
        *,
        scenario: str = "normal",
        door_timeout_sec: float = 180.0,
        thresholds: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.store_id = store_id
        self.hub = EdgeHubClient(hub_url, store_id)
        self.uat_root = uat_root
        self.topics_cfg = load_mqtt_topics(store_id, uat_root)
        self.sensors = self.topics_cfg.get("sensors", [])
        self.scenario = scenario if scenario in SCENARIOS else "normal"
        self.thresholds = thresholds or {}
        self.door_tracker = DoorTimeoutTracker(timeout_sec=door_timeout_sec)
        self._readings: Dict[str, Dict[str, Any]] = {}
        self._door_forced_open = self.scenario == "door_alert"

    def _persist_reading(self, sensor: Dict[str, Any], value: Any) -> Dict[str, Any]:
        sid = sensor["sensor_id"]
        stype = sensor.get("type", "unknown")
        unit = sensor.get("unit", "")
        level = level_for_sensor(stype, value, self.thresholds)
        parsed = {
            "sensor_id": sid,
            "type": stype,
            "unit": unit,
            "value": value,
            "level": level,
            "recorded_at": utc_now_iso(),
        }
        self._readings[sid] = parsed
        return parsed

    def _post_events_for_reading(self, sensor: Dict[str, Any], parsed: Dict[str, Any]) -> List[Dict[str, Any]]:
        events: List[Dict[str, Any]] = []
        stype = parsed["type"]
        sid = parsed["sensor_id"]
        value = parsed["value"]

        if stype == "door":
            door_event = self.door_tracker.on_reading(
                sid, value, store_id=self.store_id, zone="kitchen"
            )
            if door_event:
                events.append(door_event)
            state = "开启" if parse_door_open(value) else "关闭"
            events.append(
                {
                    "event_type": "iot_door_reading",
                    "source": EventSource.IOT.value,
                    "level": parsed["level"],
                    "store_id": self.store_id,
                    "zone": "kitchen",
                    "message": f"门磁 {sid}: {state}",
                    "timestamp": utc_now_iso(),
                    "metadata": parsed,
                }
            )
            return events

        if parsed["level"] in ("warn", "critical"):
            events.append(
                {
                    "event_type": f"iot_{stype}_abnormal",
                    "source": EventSource.IOT.value,
                    "level": parsed["level"],
                    "store_id": self.store_id,
                    "zone": "kitchen",
                    "message": f"IoT {sid}: {value}{parsed.get('unit', '')}",
                    "timestamp": utc_now_iso(),
                    "metadata": parsed,
                }
            )
        else:
            events.append(
                {
                    "event_type": f"iot_{stype}_reading",
                    "source": EventSource.IOT.value,
                    "level": parsed["level"],
                    "store_id": self.store_id,
                    "zone": "kitchen",
                    "message": f"IoT {sid}: {value}{parsed.get('unit', '')}",
                    "timestamp": utc_now_iso(),
                    "metadata": parsed,
                }
            )
        return events

    def tick(self, cycle: int = 1) -> Dict[str, Any]:
        batch_readings: List[Dict[str, Any]] = []
        event_count = 0

        for sensor in self.sensors:
            value = stub_value(
                sensor,
                self.scenario,
                cycle=cycle,
                door_forced_open=self._door_forced_open,
            )
            parsed = self._persist_reading(sensor, value)
            batch_readings.append(
                {
                    "sensor_id": parsed["sensor_id"],
                    "sensor_type": parsed["type"],
                    "value": float(parsed["value"]) if parsed["type"] != "door" else (1 if parse_door_open(parsed["value"]) else 0),
                    "unit": parsed.get("unit", ""),
                    "recorded_at": parsed["recorded_at"],
                }
            )
            for ev in self._post_events_for_reading(sensor, parsed):
                self.hub.post_event(ev)
                event_count += 1

        alerts = sum(1 for r in self._readings.values() if r.get("level") in ("warn", "critical"))
        door_open = any(
            parse_door_open(r["value"])
            for r in self._readings.values()
            if r.get("type") == "door"
        )
        stats = {
            "store_id": self.store_id,
            "updated_at": utc_now_iso(),
            "stage_readings": dict(self._readings),
            "summary": {
                "sensor_count": len(self._readings),
                "iot_alert_count": alerts,
                "door_open": door_open,
                "stub_scenario": self.scenario,
                "stub_mode": True,
            },
        }
        self.hub.post("/iot", stats)
        self.hub.post(
            "/v1/iot/readings/batch",
            {"store_id": self.store_id, "readings": batch_readings},
        )
        self.hub.flush_queue()

        return {
            "store_id": self.store_id,
            "cycle": cycle,
            "scenario": self.scenario,
            "sensors": len(self.sensors),
            "events": event_count,
            "door_open": door_open,
        }

    def run(self, interval: float = 30.0, cycles: int = 0) -> None:
        tick = 0
        while cycles == 0 or tick < cycles:
            tick += 1
            summary = self.tick(tick)
            print(json.dumps(summary, ensure_ascii=False), flush=True)
            if cycles > 0 and tick >= cycles:
                break
            if interval <= 0:
                break
            time.sleep(interval)


def main() -> None:
    parser = argparse.ArgumentParser(description="IoT stub bridge (no MQTT/devices)")
    parser.add_argument("--store-id", default="store_yuhuan")
    parser.add_argument("--hub-url", default="http://127.0.0.1:8088")
    parser.add_argument("--uat-root", default=str(DEFAULT_UAT_ROOT))
    parser.add_argument("--interval", type=float, default=30.0)
    parser.add_argument("--cycles", type=int, default=0, help="0 = forever")
    parser.add_argument("--scenario", choices=SCENARIOS, default="normal")
    parser.add_argument("--door-timeout-sec", type=float, default=180.0)
    parser.add_argument(
        "--fast-demo",
        action="store_true",
        help="Shorter door timeout (15s) and interval (5s) for demo",
    )
    args = parser.parse_args()

    if args.fast_demo:
        args.door_timeout_sec = 15.0
        if args.interval == 30.0:
            args.interval = 5.0

    uat_root = Path(args.uat_root)
    thresholds = {}
    cfg_path = uat_dir(args.store_id, uat_root) / "config.json"
    if cfg_path.exists():
        thresholds = json.loads(cfg_path.read_text(encoding="utf-8")).get("alert_thresholds", {})
    else:
        try:
            thresholds = load_store_config(args.store_id, uat_root).get("alert_thresholds", {})
        except FileNotFoundError:
            pass

    bridge = IotStubBridge(
        args.store_id,
        args.hub_url,
        uat_root,
        scenario=args.scenario,
        door_timeout_sec=args.door_timeout_sec,
        thresholds=thresholds,
    )
    print(
        f"[iot_stub] {args.store_id} → {args.hub_url} "
        f"scenario={args.scenario} interval={args.interval}s door_timeout={args.door_timeout_sec}s",
        file=sys.stderr,
    )
    bridge.run(interval=args.interval, cycles=args.cycles)


if __name__ == "__main__":
    main()
