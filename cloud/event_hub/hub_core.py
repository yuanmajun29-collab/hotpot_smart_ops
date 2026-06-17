"""Shared multi-tenant Event Hub core (memory layer)."""

from __future__ import annotations

import json
import threading
import uuid
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Deque, Dict, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[2]
STORES_REGISTRY = PROJECT_ROOT / "demo" / "data" / "stores.json"
MAX_EVENTS = 500
DEFAULT_STORE_ID = "store_yuhuan"

PersistHook = Optional[Callable[[str, str, Any], None]]


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


from cloud.event_hub.domain.health import (
    compute_store_health,
    _rollup_from_rows,
    _region_worst_health,
)
from cloud.event_hub.domain.turnover import turnover_suggestions


def _anomaly_stores_from_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    anomaly: List[Dict[str, Any]] = []
    for r in rows:
        if r["health"]["status"] != "ok":
            anomaly.append(
                {
                    "store_id": r["store_id"],
                    "store_name": r["store_name"],
                    "health": r["health"]["status"],
                    "score": r["health"]["score"],
                    "reasons": r["health"]["reasons"],
                    "metrics": r["metrics"],
                }
            )
    order = {"critical": 0, "warn": 1, "ok": 2}
    anomaly.sort(key=lambda x: (order.get(x["health"], 9), -x["score"]))
    return anomaly


class EventStore:
    """In-memory state for a single store tenant."""

    def __init__(self, store_id: str, on_persist: PersistHook = None) -> None:
        self.store_id = store_id
        self._on_persist = on_persist
        self._lock = threading.Lock()
        self.events: Deque[Dict[str, Any]] = deque(maxlen=MAX_EVENTS)
        self.table_states: Dict[str, Dict[str, Any]] = {}
        self.pos_stats: Dict[str, Any] = {}
        self.sop_stats: Dict[str, Any] = {}
        self.cost_stats: Dict[str, Any] = {}
        self.iot_stats: Dict[str, Any] = {}
        self.erp_stats: Dict[str, Any] = {}

    def _persist(self, kind: str, payload: Any) -> None:
        if self._on_persist:
            self._on_persist(self.store_id, kind, payload)

    def add_event(self, event: Dict[str, Any]) -> Dict[str, Any]:
        with self._lock:
            event = dict(event)
            if "timestamp" not in event:
                event["timestamp"] = utc_now_iso()
            if "event_id" not in event:
                event["event_id"] = str(uuid.uuid4())
            event["store_id"] = self.store_id
            self.events.appendleft(event)
            if event.get("table_id") and event.get("event_type", "").startswith("table_"):
                state = event["event_type"].replace("table_", "")
                self.table_states[event["table_id"]] = {
                    "table_id": event["table_id"],
                    "state": state,
                    "confidence": event.get("confidence", 1.0),
                    "updated_at": event["timestamp"],
                }
                self._persist("tables", list(self.table_states.values()))
            self._persist("event", event)
            return event

    def set_table_states(self, states: List[Dict[str, Any]]) -> None:
        with self._lock:
            for s in states:
                self.table_states[s["table_id"]] = s
            self._persist("tables", list(self.table_states.values()))

    def set_pos_stats(self, stats: Dict[str, Any]) -> None:
        with self._lock:
            stats = dict(stats)
            stats["store_id"] = self.store_id
            self.pos_stats = stats
            self._persist("pos", stats)

    def set_sop_stats(self, stats: Dict[str, Any]) -> None:
        with self._lock:
            stats = dict(stats)
            stats["store_id"] = self.store_id
            self.sop_stats = stats
            self._persist("sop", stats)

    def set_cost_stats(self, stats: Dict[str, Any]) -> None:
        with self._lock:
            stats = dict(stats)
            stats["store_id"] = self.store_id
            self.cost_stats = stats
            self._persist("cost", stats)

    def set_iot_stats(self, stats: Dict[str, Any]) -> None:
        with self._lock:
            stats = dict(stats)
            stats["store_id"] = self.store_id
            self.iot_stats = stats
            self._persist("iot", stats)

    def set_erp_stats(self, stats: Dict[str, Any]) -> None:
        with self._lock:
            stats = dict(stats)
            stats["store_id"] = self.store_id
            self.erp_stats = stats
            self._persist("erp", stats)

    def get_events(self, level: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
        with self._lock:
            items = list(self.events)
        if level:
            items = [e for e in items if e.get("level") == level]
        return items[:limit]

    def get_summary(self) -> Dict[str, Any]:
        with self._lock:
            events = list(self.events)
            tables = dict(self.table_states)
            pos = dict(self.pos_stats)
            sop = dict(self.sop_stats)
            cost = dict(self.cost_stats)
            iot = dict(self.iot_stats)
            erp = dict(self.erp_stats)
        by_level = {"info": 0, "warn": 0, "critical": 0}
        by_source = {"vision": 0, "iot": 0, "pos": 0, "system": 0}
        for e in events:
            by_level[e.get("level", "info")] = by_level.get(e.get("level", "info"), 0) + 1
            by_source[e.get("source", "system")] = by_source.get(e.get("source", "system"), 0) + 1
        state_counts = {"empty": 0, "dining": 0, "need_clean": 0, "checkout": 0}
        for t in tables.values():
            state_counts[t.get("state", "empty")] = state_counts.get(t.get("state", "empty"), 0) + 1
        return {
            "store_id": self.store_id,
            "total_events": len(events),
            "by_level": by_level,
            "by_source": by_source,
            "table_states": tables,
            "table_state_counts": state_counts,
            "pos_stats": pos,
            "sop_stats": sop,
            "cost_stats": cost,
            "iot_stats": iot,
            "erp_stats": erp,
            "turnover_suggestions": turnover_suggestions(tables),
        }

    def has_data(self) -> bool:
        with self._lock:
            return bool(
                self.events
                or self.table_states
                or self.pos_stats
                or self.sop_stats
                or self.cost_stats
                or self.iot_stats
                or self.erp_stats
            )

    def load_snapshot(self, kind: str, payload: Any) -> None:
        with self._lock:
            if kind == "tables" and isinstance(payload, list):
                self.table_states = {s["table_id"]: s for s in payload if s.get("table_id")}
            elif kind == "pos":
                self.pos_stats = dict(payload)
            elif kind == "sop":
                self.sop_stats = dict(payload)
            elif kind == "cost":
                self.cost_stats = dict(payload)
            elif kind == "iot":
                self.iot_stats = dict(payload)
            elif kind == "erp":
                self.erp_stats = dict(payload)
            elif kind == "event" and isinstance(payload, dict):
                self.events.appendleft(payload)

    def load_events_batch(self, events: List[Dict[str, Any]]) -> None:
        with self._lock:
            for ev in reversed(events):
                self.events.appendleft(ev)


class MultiTenantHub:
    def __init__(self, on_persist: PersistHook = None) -> None:
        self._lock = threading.Lock()
        self._stores: Dict[str, EventStore] = {}
        self._registry: Dict[str, Dict[str, Any]] = {}
        self._regions: List[Dict[str, Any]] = []
        self._zones: List[Dict[str, Any]] = []
        self._on_persist = on_persist
        self._load_registry()

    def _load_registry(self) -> None:
        if not STORES_REGISTRY.exists():
            return
        try:
            data = json.loads(STORES_REGISTRY.read_text(encoding="utf-8"))
            self._regions = list(data.get("regions", []))
            self._zones = list(data.get("parent_regions", []))
            for item in data.get("pilot_stores", []):
                sid = item.get("store_id")
                if sid:
                    self._registry[sid] = item
        except Exception as exc:
            print(f"[EventHub] WARN: failed to load stores registry: {exc}")

    def get_store(self, store_id: str) -> EventStore:
        with self._lock:
            if store_id not in self._stores:
                self._stores[store_id] = EventStore(store_id, on_persist=self._on_persist)
            return self._stores[store_id]

    def list_stores(self) -> List[Dict[str, Any]]:
        store_ids = set(self._registry) | set(self._stores)
        items: List[Dict[str, Any]] = []
        for sid in sorted(store_ids):
            meta = dict(self._registry.get(sid, {}))
            meta.setdefault("store_id", sid)
            meta["has_data"] = self.get_store(sid).has_data()
            items.append(meta)
        return items

    def _store_benchmark_row(self, sid: str) -> Optional[Dict[str, Any]]:
        meta = self._registry.get(sid, {})
        summary = self.get_store(sid).get_summary()
        if not summary.get("total_events") and not self.get_store(sid).has_data():
            return None
        pos = summary.get("pos_stats") or {}
        sop = summary.get("sop_stats") or {}
        cost = summary.get("cost_stats") or {}
        levels = summary.get("by_level") or {}
        tables = summary.get("table_state_counts") or {}
        metrics = {
            "daily_revenue": pos.get("daily_revenue", 0),
            "turnover_rate": pos.get("turnover_rate", 0),
            "sop_compliance_rate": sop.get("compliance_rate"),
            "cost_variance_pct": cost.get("variance_rate_pct"),
            "critical_alerts": levels.get("critical", 0),
            "warn_alerts": levels.get("warn", 0),
            "need_clean": tables.get("need_clean", 0),
            "empty_tables": tables.get("empty", 0),
        }
        health = compute_store_health(metrics)
        return {
            "store_id": sid,
            "store_name": meta.get("store_name", sid),
            "city": meta.get("city", ""),
            "type": meta.get("type", ""),
            "metrics": metrics,
            "health": health,
        }

    def _rows_for_region(self, region_meta: Dict[str, Any]) -> List[Dict[str, Any]]:
        rows: List[Dict[str, Any]] = []
        for sid in region_meta.get("store_ids") or []:
            row = self._store_benchmark_row(sid)
            if row:
                rows.append(row)
        return rows

    def _child_region_summary(self, region_meta: Dict[str, Any]) -> Dict[str, Any]:
        rows = self._rows_for_region(region_meta)
        rollup = _rollup_from_rows(rows)
        return {
            "region_id": region_meta.get("region_id"),
            "region_name": region_meta.get("region_name"),
            "parent": region_meta.get("parent", ""),
            "status": region_meta.get("status", "planned"),
            "store_count": len(region_meta.get("store_ids") or []),
            "connected_stores": len(rows),
            "health_status": _region_worst_health(rows, region_meta.get("status", "active")),
            "rollup": rollup,
        }

    def get_region_overview(self, region_id: Optional[str] = None) -> Dict[str, Any]:
        """F-HQ06/F-HQ07: zone or region rollup, health matrix, anomaly stores."""
        regions_meta = self._regions or [
            {
                "region_id": "region_taizhou",
                "region_name": "台州区域",
                "parent": "华东大区",
                "status": "active",
                "store_ids": sorted(self._registry.keys()),
            }
        ]
        zones_meta = self._zones or [
            {
                "zone_id": "zone_east_china",
                "zone_name": "华东大区",
                "status": "active",
                "child_region_ids": [r.get("region_id") for r in regions_meta],
            }
        ]

        zone = None
        region = None
        if region_id:
            zone = next((z for z in zones_meta if z.get("zone_id") == region_id), None)
            if not zone:
                region = next((r for r in regions_meta if r.get("region_id") == region_id), None)
        if not zone and not region:
            zone = next((z for z in zones_meta if z.get("status") == "active"), zones_meta[0] if zones_meta else None)

        level = "zone" if zone else "region"
        if zone:
            scope_id = zone.get("zone_id", "zone_east_china")
            scope_name = zone.get("zone_name", "华东大区")
            parent_name = ""
            child_ids = set(zone.get("child_region_ids") or [])
            child_metas = [r for r in regions_meta if r.get("region_id") in child_ids]
            store_ids: List[str] = []
            for cm in child_metas:
                store_ids.extend(cm.get("store_ids") or [])
            child_regions = [self._child_region_summary(cm) for cm in child_metas]
        else:
            region = region or next((r for r in regions_meta if r.get("status") == "active"), regions_meta[0])
            scope_id = region.get("region_id", "region_taizhou")
            scope_name = region.get("region_name", "台州区域")
            parent_name = region.get("parent", "")
            store_ids = list(region.get("store_ids") or [])
            child_regions = []

        rows: List[Dict[str, Any]] = []
        for sid in store_ids:
            row = self._store_benchmark_row(sid)
            if row:
                rows.append(row)

        rollup = _rollup_from_rows(rows)
        anomaly_stores = _anomaly_stores_from_rows(rows)

        def _rank(key: str, reverse: bool = True) -> Dict[str, int]:
            sorted_rows = sorted(
                rows,
                key=lambda r: r["metrics"].get(key) if r["metrics"].get(key) is not None else -1e9,
                reverse=reverse,
            )
            return {r["store_id"]: i + 1 for i, r in enumerate(sorted_rows)}

        rankings = {
            "sop_compliance_rate": _rank("sop_compliance_rate"),
            "cost_variance_pct": _rank("cost_variance_pct", reverse=False),
            "critical_alerts": _rank("critical_alerts", reverse=False),
            "daily_revenue": _rank("daily_revenue"),
        }

        narrative: List[str] = []
        if level == "zone":
            active_children = [c for c in child_regions if c.get("status") == "active"]
            planned_children = [c for c in child_regions if c.get("status") == "planned"]
            narrative.append(
                f"{scope_name}共接入 {rollup['store_count']} 家门店，"
                f"覆盖 {len(active_children)} 个运营区域"
            )
            if planned_children:
                names = "、".join(c["region_name"] for c in planned_children)
                narrative.append(f"筹备中区域：{names}")
            if rollup["critical_stores"]:
                names = [a["store_name"] for a in anomaly_stores if a["health"] == "critical"]
                narrative.append(f"⚠ 大区 {rollup['critical_stores']} 家店需立即关注：{', '.join(names)}")
            worst_child = sorted(
                [c for c in child_regions if c.get("connected_stores")],
                key=lambda c: ({"critical": 0, "warn": 1, "ok": 2, "planned": 3}.get(c.get("health_status", "ok"), 9)),
            )
            if worst_child and worst_child[0].get("health_status") in ("critical", "warn"):
                c0 = worst_child[0]
                narrative.append(f"优先巡检：{c0['region_name']}（{c0['rollup'].get('critical_stores', 0)} 家异常）")
        else:
            if rollup["critical_stores"]:
                names = [a["store_name"] for a in anomaly_stores if a["health"] == "critical"]
                narrative.append(f"⚠ {rollup['critical_stores']} 家店需立即关注：{', '.join(names)}")
            if len(rows) >= 2:
                by_sop = sorted(rows, key=lambda r: r["metrics"].get("sop_compliance_rate") or 0, reverse=True)
                narrative.append(
                    f"SOP 合规：{by_sop[0]['store_name']}（{by_sop[0]['metrics'].get('sop_compliance_rate')}%）"
                    f" 领先 {by_sop[-1]['store_name']}（{by_sop[-1]['metrics'].get('sop_compliance_rate')}%）"
                )
                by_crit = sorted(rows, key=lambda r: r["metrics"].get("critical_alerts") or 0)
                if by_crit[0]["metrics"].get("critical_alerts", 0) < by_crit[-1]["metrics"].get("critical_alerts", 0):
                    narrative.append(
                        f"食安告警：{by_crit[-1]['store_name']} 严重告警 {by_crit[-1]['metrics'].get('critical_alerts')} 条，"
                        f"建议优先巡检"
                    )
                by_clean = sorted(rows, key=lambda r: r["metrics"].get("need_clean") or 0, reverse=True)
                if by_clean[0]["metrics"].get("need_clean", 0) > 0:
                    narrative.append(
                        f"翻台压力：{by_clean[0]['store_name']} 待清台 {by_clean[0]['metrics'].get('need_clean')} 桌，"
                        f"建议增配保洁"
                    )
        if not narrative:
            narrative.append("区域内门店运营态势正常")

        regions_brief = [
            {
                "region_id": r.get("region_id"),
                "region_name": r.get("region_name"),
                "parent": r.get("parent"),
                "status": r.get("status", "planned"),
                "store_count": len(r.get("store_ids") or []),
            }
            for r in regions_meta
        ]
        zones_brief = [
            {
                "zone_id": z.get("zone_id"),
                "zone_name": z.get("zone_name"),
                "status": z.get("status", "active"),
                "region_count": len(z.get("child_region_ids") or []),
            }
            for z in zones_meta
        ]

        return {
            "brand": "冯校长火锅",
            "level": level,
            "region_id": scope_id,
            "region_name": scope_name,
            "parent_region": parent_name,
            "region": scope_name,
            "store_count": len(rows),
            "rollup": rollup,
            "health_matrix": [
                {
                    "store_id": r["store_id"],
                    "store_name": r["store_name"],
                    "city": r.get("city", ""),
                    "health": r["health"]["status"],
                    "score": r["health"]["score"],
                    "reasons": r["health"]["reasons"],
                }
                for r in rows
            ],
            "anomaly_stores": anomaly_stores,
            "regions": regions_brief,
            "parent_regions": zones_brief,
            "child_regions": child_regions,
            "stores": rows,
            "rankings": rankings,
            "narrative": narrative,
            "generated_at": utc_now_iso(),
        }

    def get_benchmark(self) -> Dict[str, Any]:
        return self.get_region_overview()

    def get_national_overview(self) -> Dict[str, Any]:
        """F-HQ12: aggregate all zones for national dashboard."""
        zones = list(self._zones) or [{"zone_id": "zone_east_china", "zone_name": "华东大区", "status": "active"}]
        zone_rollups = []
        all_rows: List[Dict[str, Any]] = []
        all_anomaly: List[Dict[str, Any]] = []

        for z in zones:
            zid = z.get("zone_id")
            if not zid:
                continue
            overview = self.get_region_overview(zid)
            rollup = overview.get("rollup") or {}
            zone_rollups.append(
                {
                    "zone_id": zid,
                    "zone_name": z.get("zone_name", zid),
                    "status": z.get("status", "active"),
                    "rollup": rollup,
                    "health_status": _region_worst_health(
                        overview.get("stores") or [],
                        z.get("status", "active"),
                    ),
                    "child_regions": overview.get("child_regions") or [],
                }
            )
            all_rows.extend(overview.get("stores") or [])
            all_anomaly.extend(overview.get("anomaly_stores") or [])

        national_rollup = _rollup_from_rows(all_rows) if all_rows else {
            "store_count": len(self._registry),
            "critical_stores": 0,
            "warn_stores": 0,
            "ok_stores": 0,
            "total_critical_alerts": 0,
            "total_need_clean": 0,
            "avg_sop_compliance": None,
        }
        order = {"critical": 0, "warn": 1, "ok": 2}
        all_anomaly.sort(key=lambda x: (order.get(x.get("health"), 9), -x.get("score", 0)))
        top_anomaly = all_anomaly[:10]

        narrative = [
            f"全国共接入 {national_rollup.get('store_count', 0)} 家门店，"
            f"覆盖 {len([z for z in zone_rollups if z.get('status') == 'active'])} 个运营大区"
        ]
        if national_rollup.get("critical_stores"):
            names = [a["store_name"] for a in top_anomaly if a.get("health") == "critical"][:3]
            narrative.append(f"⚠ {national_rollup['critical_stores']} 家店需立即关注：{', '.join(names)}")

        return {
            "brand": "冯校长火锅",
            "level": "national",
            "region_id": "org_hq",
            "region_name": "全国总部",
            "rollup": national_rollup,
            "zones": zone_rollups,
            "stores": all_rows,
            "anomaly_stores": top_anomaly,
            "narrative": narrative,
            "generated_at": utc_now_iso(),
        }

    def reload_registry_from(self, data: Dict[str, Any]) -> None:
        with self._lock:
            self._zones = list(data.get("parent_regions", []))
            self._regions = list(data.get("regions", []))
            self._registry = {
                s["store_id"]: dict(s)
                for s in data.get("pilot_stores", [])
                if s.get("store_id")
            }

    def apply_seed(self, seed: Dict[str, Any]) -> None:
        store_id = seed.get("store_id") or DEFAULT_STORE_ID
        store = self.get_store(store_id)
        if seed.get("pos_stats"):
            store.set_pos_stats(seed["pos_stats"])
        if seed.get("table_states"):
            store.set_table_states(seed["table_states"])
        if seed.get("sop_stats"):
            store.set_sop_stats(seed["sop_stats"])
        if seed.get("cost_stats"):
            store.set_cost_stats(seed["cost_stats"])
        if seed.get("iot_stats"):
            store.set_iot_stats(seed["iot_stats"])
        if seed.get("erp_stats"):
            store.set_erp_stats(seed["erp_stats"])
        for ev in seed.get("sample_events", []):
            store.add_event(dict(ev))


def seed_from_directory(hub: MultiTenantHub, stores_dir: Path) -> int:
    count = 0
    if not stores_dir.is_dir():
        return count
    for seed_file in sorted(stores_dir.glob("*/seed.json")):
        try:
            seed = json.loads(seed_file.read_text(encoding="utf-8"))
            hub.apply_seed(seed)
            sid = seed.get("store_id", seed_file.parent.name)
            print(f"[EventHub] Seeded store {sid} from {seed_file}")
            count += 1
        except Exception as exc:
            print(f"[EventHub] WARN: seed failed for {seed_file}: {exc}")
    return count
