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


def turnover_suggestions(tables: Dict[str, Dict]) -> List[Dict[str, Any]]:
    priority = {"need_clean": 1, "checkout": 2, "empty": 3}
    items = []
    for t in tables.values():
        st = t.get("state", "")
        if st in priority:
            items.append(
                {
                    "table_id": t["table_id"],
                    "state": st,
                    "priority": priority[st],
                    "action": {"need_clean": "立即清台", "checkout": "引导结账", "empty": "可安排入座"}.get(st, ""),
                }
            )
    return sorted(items, key=lambda x: (x["priority"], x["table_id"]))


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
        self._on_persist = on_persist
        self._load_registry()

    def _load_registry(self) -> None:
        if not STORES_REGISTRY.exists():
            return
        try:
            data = json.loads(STORES_REGISTRY.read_text(encoding="utf-8"))
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

    def get_benchmark(self) -> Dict[str, Any]:
        rows: List[Dict[str, Any]] = []
        for sid in sorted(set(self._registry) | set(self._stores)):
            meta = self._registry.get(sid, {})
            summary = self.get_store(sid).get_summary()
            if not summary.get("total_events") and not self.get_store(sid).has_data():
                continue
            pos = summary.get("pos_stats") or {}
            sop = summary.get("sop_stats") or {}
            cost = summary.get("cost_stats") or {}
            levels = summary.get("by_level") or {}
            tables = summary.get("table_state_counts") or {}
            rows.append(
                {
                    "store_id": sid,
                    "store_name": meta.get("store_name", sid),
                    "city": meta.get("city", ""),
                    "metrics": {
                        "daily_revenue": pos.get("daily_revenue", 0),
                        "turnover_rate": pos.get("turnover_rate", 0),
                        "sop_compliance_rate": sop.get("compliance_rate"),
                        "cost_variance_pct": cost.get("variance_rate_pct"),
                        "critical_alerts": levels.get("critical", 0),
                        "warn_alerts": levels.get("warn", 0),
                        "need_clean": tables.get("need_clean", 0),
                        "empty_tables": tables.get("empty", 0),
                    },
                }
            )

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

        return {
            "region": "台州",
            "store_count": len(rows),
            "stores": rows,
            "rankings": rankings,
            "narrative": narrative,
            "generated_at": utc_now_iso(),
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
