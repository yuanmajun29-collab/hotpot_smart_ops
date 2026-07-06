"""Device & integration stub layer — inject full business data without real hardware."""

from __future__ import annotations

import random
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def build_stub_seed(store_id: str, store_name: str, inject_anomaly: bool = False) -> Dict[str, Any]:
    """Generate minimal seed covering vision/IoT/POS/SOP/ERP/cost layers."""
    ts = utc_now_iso()
    tables = [
        {"table_id": f"T0{i}", "state": s, "confidence": 0.85, "updated_at": ts}
        for i, s in enumerate(["dining", "need_clean", "checkout", "empty", "dining", "empty"], 1)
    ]
    if inject_anomaly:
        tables[1]["state"] = "need_clean"
        tables[2]["state"] = "need_clean"

    events: List[Dict[str, Any]] = [
        {
            "event_type": "table_need_clean",
            "source": "vision_stub",
            "level": "warn",
            "store_id": store_id,
            "zone": "front",
            "table_id": "T02",
            "message": f"[stub] {store_name} 桌位 T02 待清台",
            "confidence": 0.88,
        },
        {
            "event_type": "cold_chain_temp",
            "source": "iot_stub",
            "level": "critical" if inject_anomaly else "info",
            "store_id": store_id,
            "zone": "kitchen",
            "message": f"[stub] 冷柜温度 {'8.2°C 偏高' if inject_anomaly else '2.1°C 正常'}",
            "metadata": {"temp_c": 8.2 if inject_anomaly else 2.1, "device_id": "fridge_01"},
        },
        {
            "event_type": "door_open",
            "source": "iot_stub",
            "level": "info",
            "store_id": store_id,
            "zone": "kitchen",
            "message": "[stub] 后厨门磁 开",
            "metadata": {"device_id": "door_kitchen"},
        },
    ]

    revenue = random.randint(38000, 62000)
    sop_rate = random.uniform(78, 96) if not inject_anomaly else random.uniform(62, 72)
    passed = int(sop_rate / 100 * 5)
    failed = max(0, 5 - passed)

    return {
        "store_id": store_id,
        "pos_stats": {
            "store_id": store_id,
            "store_name": store_name,
            "date": ts[:10],
            "turnover_rate": round(random.uniform(2.2, 3.1), 1),
            "daily_revenue": revenue,
            "avg_ticket": random.randint(110, 145),
            "table_count": 40,
            "dish_timeout_count": random.randint(1, 6),
            "queue_count": random.randint(8, 25),
            "queue_lost_rate": round(random.uniform(0.05, 0.15), 2),
            "food_cost_rate": round(random.uniform(0.30, 0.35), 2),
            "staff_count": random.randint(22, 32),
        },
        "table_states": tables,
        "sop_stats": {
            "store_id": store_id,
            "shift": "noon",
            "total": 5,
            "passed": passed,
            "failed": failed,
            "compliance_rate": round(sop_rate, 1),
            "evaluated_at": ts,
        },
        "cost_stats": {
            "store_id": store_id,
            "batch_count": random.randint(2, 5),
            "variance_rate_pct": round(random.uniform(1.2, 6.5 if inject_anomaly else 3.5), 1),
            "short_weight_batches": 1 if inject_anomaly else 0,
            "updated_at": ts,
        },
        "iot_stats": {
            "store_id": store_id,
            "fridge_temp_c": 8.2 if inject_anomaly else 2.1,
            "fridge_status": "warn" if inject_anomaly else "ok",
            "door_open_count": random.randint(0, 3),
            "gas_leak": False,
            "updated_at": ts,
        },
        "erp_stats": {
            "store_id": store_id,
            "pending_po_count": random.randint(1, 4),
            "today_received_batches": random.randint(0, 2),
            "updated_at": ts,
        },
        "sample_events": events,
    }


def tick_store_inprocess(
    hub: Any,
    store_id: str,
    store_name: Optional[str] = None,
    inject_anomaly: bool = False,
) -> Dict[str, Any]:
    """Inject stub data directly into Hub (fast path for Admin tick / tests)."""
    meta = hub._registry.get(store_id, {})
    name = store_name or meta.get("store_name", store_id)
    seed = build_stub_seed(store_id, name, inject_anomaly=inject_anomaly)
    hub.apply_seed(seed)
    return {
        "store_id": store_id,
        "store_name": name,
        "mode": "inprocess",
        "layers": _pipeline_layers(hub, store_id),
        "inject_anomaly": inject_anomaly,
    }


def tick_all_stores_inprocess(hub: Any, inject_anomaly: bool = False) -> List[Dict[str, Any]]:
    results = []
    for sid, meta in sorted(hub._registry.items()):
        results.append(
            tick_store_inprocess(
                hub,
                sid,
                meta.get("store_name"),
                inject_anomaly=inject_anomaly and sid == sorted(hub._registry)[0],
            )
        )
    return results


def _pipeline_layers(hub: Any, store_id: str) -> Dict[str, bool]:
    store = hub.get_store(store_id)
    summary = store.get_summary()
    return {
        "vision": bool(store.table_states or any(
            (e.get("source") or "").startswith("vision") for e in list(store.events)[:20]
        )),
        "iot": bool(store.iot_stats or any(
            (e.get("source") or "").startswith("iot") for e in list(store.events)[:20]
        )),
        "pos": bool(store.pos_stats),
        "sop": bool(store.sop_stats),
        "erp": bool(store.erp_stats),
        "cost": bool(store.cost_stats),
        "events": summary.get("total_events", 0) > 0,
    }


def get_pipeline_status(hub: Any) -> List[Dict[str, Any]]:
    """Per-store data layer readiness for Admin pipeline view."""
    rows = []
    for sid in sorted(set(hub._registry) | set(hub._stores)):
        meta = hub._registry.get(sid, {})
        layers = _pipeline_layers(hub, sid)
        ready = sum(1 for v in layers.values() if v)
        total = len(layers)
        rows.append(
            {
                "store_id": sid,
                "store_name": meta.get("store_name", sid),
                "status": meta.get("status", "active"),
                "region_id": meta.get("region_id"),
                "layers": layers,
                "ready_count": ready,
                "total_layers": total,
                "pipeline_pct": round(ready / total * 100) if total else 0,
                "has_data": hub.get_store(sid).has_data(),
            }
        )
    return rows


def run_subprocess_pipeline(
    store_id: str,
    store_name: str,
    hub_url: str,
    inject_anomaly: bool = False,
) -> Dict[str, Any]:
    """Full shell pipeline (vision/iot/sop/erp/cost scripts) — slower, closer to prod."""
    script = PROJECT_ROOT / "demo" / "run_store_pipeline.sh"
    cmd = [
        "bash",
        str(script),
        store_id,
        store_name,
        "1" if inject_anomaly else "0",
        hub_url,
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, cwd=str(PROJECT_ROOT), timeout=120)
    return {
        "store_id": store_id,
        "mode": "subprocess",
        "returncode": proc.returncode,
        "stdout_tail": proc.stdout[-2000:] if proc.stdout else "",
        "stderr_tail": proc.stderr[-500:] if proc.stderr else "",
        "ok": proc.returncode == 0,
    }
