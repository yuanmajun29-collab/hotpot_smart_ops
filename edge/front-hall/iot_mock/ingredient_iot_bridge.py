#!/usr/bin/env python3
"""
Ingredient lifecycle IoT bridge: receiving -> storage -> processing.

Integrates IoT readings with SOP checkpoints, cost control (weight/yield),
and event hub. Works alongside LLM + VLM (IoT provides ground-truth quantities).
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from common.iot_sensors import IOT_SENSORS, LIFECYCLE_STAGES, sensors_by_stage
from common.schemas import EventLevel, EventSource, OpsEvent, utc_now_iso

DEFAULT_INPUT = PROJECT_ROOT / "demo" / "data" / "ingredient_lifecycle_iot.json"


class IngredientIoTBridge:
    """Process ingredient batches through IoT lifecycle stages."""

    WEIGHT_TOLERANCE = 0.03
    TEMP_GRACE = 0

    def process_batches(self, batches: List[Dict[str, Any]], store_id: str = "store_yuhuan") -> Dict[str, Any]:
        stage_readings: Dict[str, List[Dict]] = {s: [] for s in LIFECYCLE_STAGES}
        events: List[Dict] = []
        sop_signals: Dict[str, Any] = {}
        cost_enrichments: List[Dict] = []

        for batch in batches:
            batch_id = batch["batch_id"]
            sku = batch["sku"]
            po_qty = float(batch.get("po_qty_kg", 0))
            iot = batch.get("iot", {})

            for stage in LIFECYCLE_STAGES:
                readings = iot.get(stage, {})
                for sensor_id, value in readings.items():
                    if sensor_id not in IOT_SENSORS:
                        continue
                    cfg = IOT_SENSORS[sensor_id]
                    reading = {
                        "batch_id": batch_id,
                        "sku": sku,
                        "stage": stage,
                        "sensor_id": sensor_id,
                        "value": value,
                        "unit": cfg.get("unit", ""),
                        "timestamp": utc_now_iso(),
                    }
                    stage_readings[stage].append(reading)

                    ev = self._evaluate_reading(store_id, batch_id, sku, sensor_id, value, po_qty, cfg)
                    if ev:
                        events.append(ev.to_dict())

                    cp = cfg.get("sop_checkpoint")
                    if cp:
                        sop_signals[cp] = self._to_sop_signal(sensor_id, value, cfg, po_qty)

            # Enrich cost data from IoT weights
            recv = iot.get("receiving", {})
            proc = iot.get("processing", {})
            actual_qty = recv.get("receiving_scale")
            usable = proc.get("prep_scale_usable")
            raw = proc.get("prep_scale_raw")
            if actual_qty is not None:
                cost_enrichments.append(
                    {
                        "batch_id": batch_id,
                        "sku": sku,
                        "po_qty_kg": po_qty,
                        "iot_actual_qty_kg": actual_qty,
                        "iot_usable_qty_kg": usable,
                        "iot_raw_prep_kg": raw,
                        "iot_yield_rate": round(usable / raw, 3) if usable and raw else None,
                        "iot_probe_temp": recv.get("receiving_probe_temp"),
                        "iot_rfid_ok": bool(recv.get("receiving_rfid_gate")),
                    }
                )

        # Aggregate store-level SOP signals (use worst-case / latest)
        store_signals = self._aggregate_store_signals(batches, sop_signals)

        return {
            "store_id": store_id,
            "processed_at": utc_now_iso(),
            "batch_count": len(batches),
            "stage_readings": stage_readings,
            "events": events,
            "sop_signals": store_signals,
            "cost_enrichments": cost_enrichments,
            "summary": self._build_summary(stage_readings, events),
        }

    def _to_sop_signal(self, sensor_id: str, value: Any, cfg: Dict, po_qty: float) -> Any:
        stype = cfg.get("type")
        if stype == "weight":
            if sensor_id == "receiving_scale" and po_qty > 0:
                return abs(po_qty - float(value)) / po_qty <= self.WEIGHT_TOLERANCE
            return float(value) > 0
        if stype == "temperature":
            lo, hi = cfg.get("normal_range", (-999, 999))
            return lo <= float(value) <= hi
        if stype == "humidity":
            lo, hi = cfg.get("normal_range", (0, 100))
            return lo <= float(value) <= hi
        if stype == "door":
            return int(value) == 0
        if stype == "rfid":
            return bool(value) if stype == "rfid" and sensor_id == "receiving_rfid_gate" else bool(value)
        if stype == "duration":
            lo, hi = cfg.get("normal_range", (0, 9999))
            return lo <= float(value) <= hi
        if stype == "gas":
            return float(value) <= cfg.get("normal_range", (0, 50))[1]
        return value

    def _aggregate_store_signals(self, batches: List[Dict], per_batch: Dict[str, Any]) -> Dict[str, Any]:
        """Build shift-level SOP signal map from latest batch IoT + store sensors."""
        signals: Dict[str, Any] = dict(per_batch)

        # Store-level aggregates from all batches
        all_storage = [b.get("iot", {}).get("storage", {}) for b in batches]
        freezer_temps = [s.get("cold_storage_1") for s in all_storage if s.get("cold_storage_1") is not None]
        fridge_temps = [s.get("cold_storage_2") for s in all_storage if s.get("cold_storage_2") is not None]
        if freezer_temps:
            signals["cold_storage_freezer"] = min(freezer_temps)
            signals["haccp_cold_temp"] = min(freezer_temps)
        if freezer_temps or fridge_temps:
            signals["cold_storage_worst"] = max(freezer_temps + fridge_temps)

        all_recv = [b.get("iot", {}).get("receiving", {}) for b in batches]
        if all_recv:
            probe_temps = [s.get("receiving_probe_temp") for s in all_recv if s.get("receiving_probe_temp") is not None]
            if probe_temps:
                signals["receiving_temp_check"] = max(probe_temps)
            recv_humids = [s.get("receiving_humidity") for s in all_recv if s.get("receiving_humidity") is not None]
            if recv_humids:
                signals["receiving_env_ok"] = max(recv_humids)

        all_proc = [b.get("iot", {}).get("processing", {}) for b in batches]
        if all_proc:
            signals["prep_yield_logged"] = all(
                p.get("prep_scale_usable", 0) > 0 for p in all_proc if p.get("prep_scale_usable") is not None
            )
            signals["prep_input_weight"] = all(
                p.get("prep_scale_raw", 0) > 0 for p in all_proc if p.get("prep_scale_raw") is not None
            )
            thaw_temps = [p.get("thaw_pool_temp") for p in all_proc if p.get("thaw_pool_temp") is not None]
            if thaw_temps:
                signals["prep_thaw_temp_ok"] = max(thaw_temps)
            timers = [p.get("prep_timer_thaw") for p in all_proc if p.get("prep_timer_thaw") is not None]
            if timers:
                signals["prep_thaw_time_ok"] = max(timers)
            area = [p.get("prep_area_temp") for p in all_proc if p.get("prep_area_temp") is not None]
            if area:
                signals["prep_area_env_ok"] = sum(area) / len(area)

        storage_humids = [s.get("storage_humidity") for s in all_storage if s.get("storage_humidity") is not None]
        if storage_humids:
            signals["storage_humidity_ok"] = max(storage_humids)

        # Boolean IoT gates
        signals["receiving_weight_match"] = all(
            abs(float(b.get("po_qty_kg", 0)) - float(b.get("iot", {}).get("receiving", {}).get("receiving_scale", b.get("po_qty_kg", 0))))
            / max(float(b.get("po_qty_kg", 1)), 0.001)
            <= self.WEIGHT_TOLERANCE
            for b in batches
            if b.get("iot", {}).get("receiving", {}).get("receiving_scale") is not None
        )
        signals["receiving_rfid_logged"] = all(
            b.get("iot", {}).get("receiving", {}).get("receiving_rfid_gate") for b in batches
        )
        signals["storage_door_closed"] = all(
            b.get("iot", {}).get("storage", {}).get("freezer_door_1", 0) == 0 for b in batches
        )
        signals["storage_fefo_ok"] = all(
            bool(b.get("iot", {}).get("storage", {}).get("rfid_shelf_zone_a")) for b in batches
        )

        return signals

    def _evaluate_reading(
        self,
        store_id: str,
        batch_id: str,
        sku: str,
        sensor_id: str,
        value: Any,
        po_qty: float,
        cfg: Dict,
    ) -> Optional[OpsEvent]:
        stype = cfg.get("type")
        stage = cfg.get("stage", "")

        if stype == "weight" and sensor_id == "receiving_scale" and po_qty > 0:
            diff = (po_qty - float(value)) / po_qty
            if diff > self.WEIGHT_TOLERANCE:
                return OpsEvent(
                    event_type="iot_weight_short",
                    source=EventSource.IOT.value,
                    level=EventLevel.WARN.value,
                    store_id=store_id,
                    zone="kitchen",
                    message=f"[IoT] {sku} 收货秤短重 {diff*100:.1f}%（PO {po_qty}kg → 秤重 {value}kg）",
                    metadata={"batch_id": batch_id, "sku": sku, "sensor_id": sensor_id, "stage": stage, "po_qty": po_qty, "actual": value},
                )

        if stype == "temperature":
            lo, hi = cfg.get("normal_range", (-999, 999))
            fv = float(value)
            if fv > hi:
                return OpsEvent(
                    event_type="iot_temp_abnormal",
                    source=EventSource.IOT.value,
                    level=EventLevel.CRITICAL.value if fv > hi + 3 else EventLevel.WARN.value,
                    store_id=store_id,
                    zone="kitchen",
                    message=f"[IoT/{stage}] {sku} {cfg.get('description', sensor_id)} 超温 {fv}°C（标准 {lo}~{hi}°C）",
                    metadata={"batch_id": batch_id, "sku": sku, "sensor_id": sensor_id, "stage": stage, "value": fv},
                )
            if fv < lo:
                return OpsEvent(
                    event_type="cold_chain_low",
                    source=EventSource.IOT.value,
                    level=EventLevel.WARN.value,
                    store_id=store_id,
                    zone="kitchen",
                    message=f"[IoT/{stage}] {sku} {cfg.get('description', sensor_id)} 低温 {fv}°C",
                    metadata={"batch_id": batch_id, "sku": sku, "sensor_id": sensor_id, "stage": stage, "value": fv},
                )

        if stype == "door" and int(value) == 1:
            return OpsEvent(
                event_type="iot_door_open_timeout",
                source=EventSource.IOT.value,
                level=EventLevel.WARN.value,
                store_id=store_id,
                zone="kitchen",
                message=f"[IoT/保存] {sku} 冷库门未关，冷链断链风险",
                metadata={"batch_id": batch_id, "sku": sku, "sensor_id": sensor_id},
            )

        if stype == "rfid" and sensor_id == "receiving_rfid_gate" and not value:
            return OpsEvent(
                event_type="iot_rfid_missing",
                source=EventSource.IOT.value,
                level=EventLevel.WARN.value,
                store_id=store_id,
                zone="kitchen",
                message=f"[IoT/来料] {sku} RFID 批次未扫描，无法追溯",
                metadata={"batch_id": batch_id, "sku": sku, "sensor_id": sensor_id},
            )

        if stype == "rfid" and sensor_id == "rfid_shelf_zone_a" and not value:
            return OpsEvent(
                event_type="iot_fefo_violation",
                source=EventSource.IOT.value,
                level=EventLevel.WARN.value,
                store_id=store_id,
                zone="kitchen",
                message=f"[IoT/保存] {sku} 未入 RFID 货位，FEFO 先进先出无法保障",
                metadata={"batch_id": batch_id, "sku": sku, "sensor_id": sensor_id},
            )

        if stype == "duration":
            lo, hi = cfg.get("normal_range", (0, 9999))
            if float(value) > hi:
                return OpsEvent(
                    event_type="iot_thaw_overtime",
                    source=EventSource.IOT.value,
                    level=EventLevel.WARN.value,
                    store_id=store_id,
                    zone="kitchen",
                    message=f"[IoT/加工] {sku} 解冻超时 {value}min（上限 {hi}min）",
                    metadata={"batch_id": batch_id, "sku": sku, "sensor_id": sensor_id, "minutes": value},
                )

        if stype == "humidity":
            lo, hi = cfg.get("normal_range", (0, 100))
            fv = float(value)
            if fv < lo or fv > hi:
                return OpsEvent(
                    event_type="iot_humidity_abnormal",
                    source=EventSource.IOT.value,
                    level=EventLevel.WARN.value,
                    store_id=store_id,
                    zone="kitchen",
                    message=f"[IoT/{stage}] {sku} 湿度异常 {fv}%RH（标准 {lo}~{hi}%）",
                    metadata={"batch_id": batch_id, "sku": sku, "sensor_id": sensor_id, "stage": stage, "value": fv},
                )

        return None

    def _build_summary(self, stage_readings: Dict, events: List) -> Dict[str, Any]:
        by_stage = {s: len(stage_readings.get(s, [])) for s in LIFECYCLE_STAGES}
        by_type: Dict[str, int] = {}
        for ev in events:
            by_type[ev.get("event_type", "?")] = by_type.get(ev.get("event_type", "?"), 0) + 1
        return {
            "readings_by_stage": by_stage,
            "iot_alert_count": len(events),
            "iot_alerts_by_type": by_type,
        }


def post_hub(hub_url: str, path: str, data: Any) -> None:
    req = urllib.request.Request(
        hub_url.rstrip("/") + path,
        data=json.dumps(data, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    urllib.request.urlopen(req, timeout=10)


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingredient lifecycle IoT bridge")
    parser.add_argument("--input", default=str(DEFAULT_INPUT))
    parser.add_argument("--store-id", default="store_yuhuan")
    parser.add_argument("--hub-url", default="")
    parser.add_argument("--merge-sop-signals", default="", help="Write merged SOP signals JSON")
    args = parser.parse_args()

    batches = json.loads(Path(args.input).read_text(encoding="utf-8"))
    bridge = IngredientIoTBridge()
    result = bridge.process_batches(batches, args.store_id)
    print(json.dumps(result, ensure_ascii=False, indent=2))

    if args.merge_sop_signals:
        out = Path(args.merge_sop_signals)
        base: Dict[str, Any] = {}
        if out.exists():
            base = json.loads(out.read_text(encoding="utf-8"))
        base.update(result["sop_signals"])
        out.write_text(json.dumps(base, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[OK] Merged SOP signals -> {out}", file=sys.stderr)

    if args.hub_url:
        hub = args.hub_url.rstrip("/")
        for ev in result["events"]:
            post_hub(hub, "/events", ev)
        post_hub(hub, "/iot", result)
        print(f"[OK] Posted {len(result['events'])} IoT events + lifecycle snapshot to hub", file=sys.stderr)


if __name__ == "__main__":
    main()
