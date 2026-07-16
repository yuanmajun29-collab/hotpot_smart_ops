"""SOP compliance monitor for 7 kitchen workstations.

Runs on edge (Jetson), monitors 7 stations with independent 3-state machines,
and pushes compliance reports to Hub POST /v1/sop/compliance.

7 Workstations:
  sop_broth      — 汤底：温度≥85°C，汤色正常
  sop_cutting    — 切配：刀具在位、砧板清洁
  sop_plating    — 摆盘：重量±5g、间距均匀
  sop_sauce      — 蘸料：蘸料盒满度>30%
  sop_washing    — 洗消：洗碗机温度≥82°C
  sop_serving    — 传菜：传菜时间<3min
  sop_cold_storage — 冷库：库温-18~-22°C

State machine (per station):
  running ──(3 consecutive fails)──→ warning
  warning ──(2 consecutive ok)───→ running
  warning ──(5 consecutive fails)──→ violation
  violation ──(manual reset)─────→ warning

Usage:
  PYTHONPATH=. python3 -m edge.receiving.sop_compliance --store-id store_yuhuan
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import random
import signal
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx  # type: ignore

logger = logging.getLogger("receiving.sop_compliance")

# ── Config ──
HUB_URL = os.environ.get("HOTPOT_HUB_URL", "http://127.0.0.1:8098")
_STORE_ID = os.environ.get("HOTPOT_STORE_ID", "store_yuhuan")
DEVICE_ID = os.environ.get("HOTPOT_DEVICE_ID", "jetson-sop-01")
API_KEY = os.environ.get("HOTPOT_API_KEY", "demo-key")
SCAN_INTERVAL = int(os.environ.get("SOP_SCAN_INTERVAL", "30"))

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


class StationStatus(str, Enum):
    RUNNING = "running"
    WARNING = "warning"
    VIOLATION = "violation"


@dataclass
class Station:
    station_id: str
    name: str
    status: StationStatus = StationStatus.RUNNING
    consecutive_ok: int = 0
    consecutive_fail: int = 0
    last_readings: Dict[str, Any] = field(default_factory=dict)
    last_message: str = ""
    last_updated: str = ""

    def evaluate(self, readings: Dict[str, Any]) -> bool:
        """Evaluate compliance based on readings. Returns True if OK."""
        self.last_readings = readings
        return _evaluate_station(self.station_id, readings)

    def tick(self, ok: bool, message: str = ""):
        """Advance state machine by one tick."""
        self.last_message = message
        self.last_updated = utc_now_iso()

        if ok:
            self.consecutive_ok += 1
            self.consecutive_fail = 0
        else:
            self.consecutive_fail += 1
            self.consecutive_ok = 0

        old_status = self.status

        if self.status == StationStatus.RUNNING:
            if self.consecutive_fail >= 3:
                self.status = StationStatus.WARNING
        elif self.status == StationStatus.WARNING:
            if self.consecutive_ok >= 2:
                self.status = StationStatus.RUNNING
            elif self.consecutive_fail >= 5:
                self.status = StationStatus.VIOLATION
        elif self.status == StationStatus.VIOLATION:
            # Manual reset only — stays in violation
            pass

        if old_status != self.status:
            logger.warning("Station %s: %s → %s (fails=%d)",
                           self.station_id, old_status.value, self.status.value,
                           self.consecutive_fail)

    def reset(self):
        """Manual reset from violation → warning."""
        self.status = StationStatus.WARNING
        self.consecutive_fail = 0
        self.consecutive_ok = 0
        self.last_updated = utc_now_iso()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "station_id": self.station_id,
            "name": self.name,
            "status": self.status.value,
            "readings": self.last_readings,
            "message": self.last_message,
            "updated_at": self.last_updated,
        }


# ── Station evaluation rules ──

def _evaluate_station(station_id: str, readings: Dict[str, Any]) -> bool:
    """Return True if the station is compliant."""
    if station_id == "sop_broth":
        temp = readings.get("temp_c", 0)
        return temp >= 85.0
    elif station_id == "sop_cutting":
        knife = readings.get("knife_detected", True)
        board_clean = readings.get("board_clean", True)
        return knife and board_clean
    elif station_id == "sop_plating":
        weight_dev = abs(readings.get("weight_deviation_g", 0))
        spacing_ok = readings.get("spacing_uniform", True)
        return weight_dev <= 5.0 and spacing_ok
    elif station_id == "sop_sauce":
        fill_pct = readings.get("fill_pct", 0)
        return fill_pct >= 30.0
    elif station_id == "sop_washing":
        temp = readings.get("temp_c", 0)
        detergent = readings.get("detergent_pct", 0)
        return temp >= 82.0 and detergent >= 10.0
    elif station_id == "sop_serving":
        elapsed_s = readings.get("elapsed_s", 0)
        tray_stable = readings.get("tray_stable", True)
        return elapsed_s <= 180.0 and tray_stable
    elif station_id == "sop_cold_storage":
        temp = readings.get("temp_c", 0)
        labels_ok = readings.get("labels_valid", True)
        return -22.0 <= temp <= -18.0 and labels_ok
    return True


# ── 7 Station definitions ──
STATIONS: List[Station] = [
    Station("sop_broth", "汤底"),
    Station("sop_cutting", "切配"),
    Station("sop_plating", "摆盘"),
    Station("sop_sauce", "蘸料"),
    Station("sop_washing", "洗消"),
    Station("sop_serving", "传菜"),
    Station("sop_cold_storage", "冷库"),
]

STATION_MAP: Dict[str, Station] = {s.station_id: s for s in STATIONS}


# ── Mock sensor readings (for dev mode) ──

def _mock_readings(station: Station) -> Dict[str, Any]:
    """Generate mock sensor readings based on station type."""
    if station.station_id == "sop_broth":
        return {"temp_c": random.uniform(82, 92)}
    elif station.station_id == "sop_cutting":
        return {"knife_detected": random.random() > 0.1, "board_clean": random.random() > 0.15}
    elif station.station_id == "sop_plating":
        return {"weight_deviation_g": random.uniform(0, 8), "spacing_uniform": random.random() > 0.1}
    elif station.station_id == "sop_sauce":
        return {"fill_pct": random.uniform(15, 60)}
    elif station.station_id == "sop_washing":
        return {"temp_c": random.uniform(78, 88), "detergent_pct": random.uniform(5, 25)}
    elif station.station_id == "sop_serving":
        return {"elapsed_s": random.uniform(30, 240), "tray_stable": random.random() > 0.05}
    elif station.station_id == "sop_cold_storage":
        return {"temp_c": random.uniform(-24, -16), "labels_valid": random.random() > 0.05}
    return {}


# ── Hub communication ──

def push_compliance(stations: List[Station]) -> Dict[str, Any]:
    """Push station compliance report to Hub POST /v1/sop/compliance."""
    station_data = [s.to_dict() for s in stations]
    running_count = sum(1 for s in stations if s.status == StationStatus.RUNNING)
    violation_count = sum(1 for s in stations if s.status == StationStatus.VIOLATION)
    warning_count = sum(1 for s in stations if s.status == StationStatus.WARNING)

    payload = {
        "store_id": _STORE_ID,
        "device_id": DEVICE_ID,
        "timestamp": utc_now_iso(),
        "stations": station_data,
        "summary": {
            "total": len(stations),
            "running": running_count,
            "warning": warning_count,
            "violation": violation_count,
            "compliance_rate": round(running_count / len(stations) * 100, 1),
        },
    }

    try:
        resp = httpx.post(
            f"{HUB_URL}/v1/sop/compliance",
            json=payload,
            headers={"X-Api-Key": API_KEY, "Content-Type": "application/json"},
            timeout=10.0,
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        logger.error("push compliance failed: %s", e)
        return {"ok": False, "error": str(e)}


def one_scan() -> Dict[str, Any]:
    """Run one scan across all 7 stations, update state machines, push to Hub."""
    for station in STATIONS:
        readings = _mock_readings(station)
        ok = station.evaluate(readings)
        msg = "OK" if ok else "不合格"
        station.tick(ok, msg)
        logger.debug("%s: %s (readings=%s)", station.name, station.status.value,
                     json.dumps(readings, ensure_ascii=False))

    return push_compliance(STATIONS)


# ── Main loop ──

def main():
    parser = argparse.ArgumentParser(description="SOP 7-station compliance monitor")
    parser.add_argument("--store-id", default=_STORE_ID)
    parser.add_argument("--interval", type=int, default=SCAN_INTERVAL)
    parser.add_argument("--once", action="store_true", help="Run one scan and exit")
    parser.add_argument("--json", action="store_true", help="JSON output")

    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    if args.store_id:
        import edge.receiving.sop_compliance as mod
        mod._STORE_ID = args.store_id

    if args.once:
        result = one_scan()
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print(f"合规率: {result.get('compliance_rate', 'N/A')}%")
            for s in STATIONS:
                status_mark = "✓" if s.status == StationStatus.RUNNING else "✗"
                print(f"  {status_mark} {s.name}({s.station_id}): {s.status.value} — {s.last_message}")
        return

    # Continuous loop
    running = True

    def _shutdown(sig, frame):
        nonlocal running
        running = False

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    logger.info("SOP compliance monitor started — %d stations, interval=%ds, hub=%s",
                 len(STATIONS), args.interval, HUB_URL)

    while running:
        try:
            result = one_scan()
            rate = result.get("compliance_rate", "?")
            violations = result.get("violations", [])
            logger.info("Scan complete — compliance=%s%% violations=%d",
                         rate, len(violations))
        except Exception as e:
            logger.error("Scan failed: %s", e)
        time.sleep(args.interval)

    logger.info("SOP compliance monitor stopped")


if __name__ == "__main__":
    main()
