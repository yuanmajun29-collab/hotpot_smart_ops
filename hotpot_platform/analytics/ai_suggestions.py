"""Rule-based operation suggestions with lifecycle persistence."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from hotpot_platform.analytics.store_compare import StoreCompareEngine


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


class SuggestionEngine:
    """Generate and persist deterministic operation suggestions."""

    SNAPSHOT_KIND = "analytics_suggestions"
    VALID_STATUSES = {"new", "read", "acknowledged", "implemented"}

    def __init__(self, hub: Any, db: Any, compare_engine: Optional[StoreCompareEngine] = None) -> None:
        self.hub = hub
        self.db = db
        self.compare = compare_engine or StoreCompareEngine(hub, db)

    def suggestions_for_store(self, store_id: str, days: int = 7, refresh: bool = True) -> Dict[str, Any]:
        existing = self._load(store_id)
        generated = self._generate(store_id, days=days) if refresh else []
        merged = self._merge(existing, generated)
        payload = {"store_id": store_id, "suggestions": merged, "generated_at": _utc_now()}
        self.db.persist_snapshot(store_id, self.SNAPSHOT_KIND, payload)
        return payload

    def update_status(
        self,
        store_id: str,
        suggestion_id: str,
        status: str,
        actor: str = "",
    ) -> Dict[str, Any]:
        if status not in self.VALID_STATUSES:
            raise ValueError(f"invalid suggestion status: {status}")
        payload = self.suggestions_for_store(store_id, refresh=False)
        found = None
        now = _utc_now()
        for item in payload["suggestions"]:
            if item.get("suggestion_id") != suggestion_id:
                continue
            item["status"] = status
            item[f"{status}_at"] = now
            if actor:
                item[f"{status}_by"] = actor
            found = item
            break
        if not found:
            raise KeyError(suggestion_id)
        self.db.persist_snapshot(store_id, self.SNAPSHOT_KIND, payload)
        return found

    def mark_read(self, store_id: str, suggestion_id: str, actor: str = "") -> Dict[str, Any]:
        return self.update_status(store_id, suggestion_id, "read", actor)

    def acknowledge(self, store_id: str, suggestion_id: str, actor: str = "") -> Dict[str, Any]:
        return self.update_status(store_id, suggestion_id, "acknowledged", actor)

    def implemented(self, store_id: str, suggestion_id: str, actor: str = "") -> Dict[str, Any]:
        return self.update_status(store_id, suggestion_id, "implemented", actor)

    def _generate(self, store_id: str, days: int) -> List[Dict[str, Any]]:
        row = self.compare._store_row(store_id, days=days)
        metrics = row.get("metrics") or {}
        waste = _safe_float((metrics.get("waste_rate") or {}).get("value"))
        waste_change = _safe_float((metrics.get("waste_rate") or {}).get("change_rate_pct"))
        sop = _safe_float((metrics.get("sop_compliance") or {}).get("value"), 100.0)
        turnover_change = _safe_float((metrics.get("table_turnover") or {}).get("change_rate_pct"))
        food_alerts = _safe_float((metrics.get("food_safety_alerts") or {}).get("value"))
        empty_alert_frequent = self._empty_alert_frequent(store_id)

        out: List[Dict[str, Any]] = []
        if (waste > 0 and waste_change >= 15.0) or (waste > 0 and sop < 80.0):
            out.append(
                self._item(
                    store_id,
                    "waste_sop_cutting_station",
                    "建议检查切配工位操作规范",
                    "废料指标偏高且 SOP 得分偏低，优先复盘切配称重、边角料归集与出品标准。",
                    "medium",
                    ["waste_rate", "sop_compliance"],
                    {"waste_rate": waste, "waste_change_pct": waste_change, "sop_score": sop},
                )
            )
        if turnover_change < 0 and empty_alert_frequent:
            out.append(
                self._item(
                    store_id,
                    "turnover_empty_alert_flow",
                    "建议优化翻台流程",
                    "翻台趋势下降且空盘/待清台类提醒频繁，建议调整巡台、清台和迎宾衔接。",
                    "medium",
                    ["table_turnover", "front_hall_alerts"],
                    {"turnover_change_pct": turnover_change, "empty_alert_frequent": empty_alert_frequent},
                )
            )
        if food_alerts > 0:
            out.append(
                self._item(
                    store_id,
                    "food_safety_checklist",
                    "高风险门店检查清单",
                    "存在食安告警，立即检查冷链温湿度、门磁、燃气、留样和异常批次追溯记录。",
                    "critical",
                    ["food_safety_alerts"],
                    {"food_safety_alerts": food_alerts},
                    checklist=[
                        "复核近24小时冷链温度曲线",
                        "检查门磁/燃气/湿度异常传感器",
                        "抽查异常批次收货与留样记录",
                        "确认班组长已完成现场复盘",
                    ],
                )
            )
        return out

    def _item(
        self,
        store_id: str,
        rule_id: str,
        title: str,
        detail: str,
        severity: str,
        metrics: List[str],
        evidence: Dict[str, Any],
        checklist: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        digest = hashlib.sha1(f"{store_id}:{rule_id}".encode("utf-8")).hexdigest()[:12]
        return {
            "suggestion_id": f"sug_{digest}",
            "store_id": store_id,
            "rule_id": rule_id,
            "title": title,
            "detail": detail,
            "severity": severity,
            "metrics": metrics,
            "evidence": evidence,
            "checklist": checklist or [],
            "status": "new",
            "created_at": _utc_now(),
            "updated_at": _utc_now(),
        }

    def _merge(self, existing: List[Dict[str, Any]], generated: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        old = {item.get("suggestion_id"): item for item in existing}
        merged: List[Dict[str, Any]] = []
        active_ids = set()
        for item in generated:
            active_ids.add(item["suggestion_id"])
            prior = old.get(item["suggestion_id"])
            if prior:
                item["status"] = prior.get("status", "new")
                item["created_at"] = prior.get("created_at", item["created_at"])
                for key, value in prior.items():
                    if key.endswith("_at") or key.endswith("_by"):
                        item[key] = value
            item["updated_at"] = _utc_now()
            merged.append(item)
        for item in existing:
            if item.get("suggestion_id") not in active_ids and item.get("status") != "implemented":
                stale = dict(item)
                stale["status"] = item.get("status", "new")
                stale["stale"] = True
                merged.append(stale)
        return merged

    def _load(self, store_id: str) -> List[Dict[str, Any]]:
        getter = getattr(self.db, "get_snapshot", None)
        if not getter:
            return []
        try:
            payload = getter(store_id, self.SNAPSHOT_KIND)
        except Exception:
            return []
        if not isinstance(payload, dict):
            return []
        return list(payload.get("suggestions") or [])

    def _empty_alert_frequent(self, store_id: str) -> bool:
        store = self.hub.get_store(store_id)
        events = store.get_events(limit=200)
        count = 0
        for ev in events:
            meta = ev.get("metadata") or {}
            alerts = meta.get("alerts") or []
            event_type = str(ev.get("event_type") or "")
            if event_type in {"table_need_clean", "table_checkout"}:
                count += 1
            if any(str(a).startswith("empty_plate_count") or str(a) == "needs_cleaning" for a in alerts):
                count += 1
        table_counts = (store.get_summary().get("table_state_counts") or {})
        count += int(table_counts.get("need_clean") or 0)
        return count >= 3
