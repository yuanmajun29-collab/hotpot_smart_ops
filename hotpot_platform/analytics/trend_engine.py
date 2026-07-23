"""Time-series trend analysis for store operation metrics."""

from __future__ import annotations

from collections import defaultdict
from datetime import date as date_type, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _parse_day(value: Any) -> Optional[date_type]:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date_type):
        return value
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).date()
    except ValueError:
        try:
            return date_type.fromisoformat(str(value)[:10])
        except ValueError:
            return None


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


class TrendEngine:
    """Build daily/weekly/monthly aggregations, moving averages, and warnings."""

    METRIC_ALIASES = {
        "waste": "waste_rate",
        "waste_rate": "waste_rate",
        "turnover": "table_turnover",
        "table_turnover": "table_turnover",
        "sop": "sop_compliance",
        "sop_compliance": "sop_compliance",
        "food_safety": "food_safety_alerts",
        "food_safety_alerts": "food_safety_alerts",
    }

    def __init__(self, hub: Any, db: Any) -> None:
        self.hub = hub
        self.db = db

    def normalize_metric(self, metric: str) -> str:
        return self.METRIC_ALIASES.get(metric, metric)

    def daily_series(self, store_id: str, metric: str, days: int = 30) -> List[Dict[str, Any]]:
        metric = self.normalize_metric(metric)
        days = max(1, min(days, 365))
        today = date_type.today()
        start = today - timedelta(days=days - 1)
        base = [
            {"date": (start + timedelta(days=i)).isoformat(), "value": 0.0, "event_count": 0}
            for i in range(days)
        ]

        if metric == "waste_rate":
            return self._waste_daily(store_id, days, base)

        if metric in ("sop_compliance", "food_safety_alerts"):
            return self._events_daily(store_id, metric, days, base)

        if metric == "table_turnover":
            value = self._current_turnover(store_id)
            if base:
                base[-1]["value"] = value
                base[-1]["event_count"] = 1 if value else 0
            return base

        return base

    def trend(
        self,
        store_id: str,
        metric: str,
        days: int = 30,
        moving_window: int = 7,
    ) -> Dict[str, Any]:
        metric = self.normalize_metric(metric)
        daily = self.daily_series(store_id, metric, days)
        values = [_safe_float(row.get("value")) for row in daily]
        moving_average = self.moving_average(values, moving_window)
        change_rate = self.change_rate(values)
        warnings = self.early_warnings(metric, daily)

        return {
            "store_id": store_id,
            "metric": metric,
            "days": days,
            "daily": daily,
            "weekly": self.aggregate(daily, "weekly"),
            "monthly": self.aggregate(daily, "monthly"),
            "values": values,
            "moving_average": moving_average,
            "change_rate_pct": change_rate,
            "warnings": warnings,
            "summary": self.summary(store_id, metric, daily, change_rate, warnings),
            "generated_at": _utc_now(),
        }

    def aggregate(self, daily: List[Dict[str, Any]], period: str) -> List[Dict[str, Any]]:
        grouped: Dict[str, List[float]] = defaultdict(list)
        counts: Dict[str, int] = defaultdict(int)
        for row in daily:
            day = _parse_day(row.get("date"))
            if not day:
                continue
            if period == "monthly":
                key = f"{day.year:04d}-{day.month:02d}"
            else:
                year, week, _ = day.isocalendar()
                key = f"{year:04d}-W{week:02d}"
            grouped[key].append(_safe_float(row.get("value")))
            counts[key] += int(row.get("event_count") or 0)
        return [
            {
                "period": key,
                "value": round(sum(vals) / len(vals), 4) if vals else 0.0,
                "total": round(sum(vals), 4),
                "event_count": counts[key],
            }
            for key, vals in sorted(grouped.items())
        ]

    def moving_average(self, values: List[float], window: int = 7) -> List[Optional[float]]:
        window = max(1, window)
        out: List[Optional[float]] = []
        for idx in range(len(values)):
            start = max(0, idx - window + 1)
            segment = values[start : idx + 1]
            out.append(round(sum(segment) / len(segment), 4) if segment else None)
        return out

    def change_rate(self, values: List[float]) -> Optional[float]:
        non_empty = [v for v in values if v is not None]
        if len(non_empty) < 2:
            return None
        prev = non_empty[-2]
        curr = non_empty[-1]
        if prev == 0:
            return None if curr == 0 else 100.0
        return round((curr - prev) / abs(prev) * 100.0, 2)

    def early_warnings(self, metric: str, daily: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        values = [_safe_float(row.get("value")) for row in daily]
        warnings: List[Dict[str, Any]] = []
        if metric == "waste_rate" and len(values) >= 4:
            prev = values[-4]
            curr = values[-1]
            if prev > 0:
                pct = (curr - prev) / prev * 100.0
                if pct >= 15.0:
                    warnings.append(
                        {
                            "type": "waste_rate_increase_3d",
                            "severity": "warn",
                            "message": f"废料率最近3天上升 {pct:.1f}%",
                            "change_pct": round(pct, 2),
                        }
                    )
        if metric == "food_safety_alerts" and values and values[-1] > 0:
            warnings.append(
                {
                    "type": "food_safety_active",
                    "severity": "critical",
                    "message": f"今日食安告警 {int(values[-1])} 条",
                    "count": int(values[-1]),
                }
            )
        return warnings

    def summary(
        self,
        store_id: str,
        metric: str,
        daily: List[Dict[str, Any]],
        change_rate: Optional[float],
        warnings: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        latest = daily[-1]["value"] if daily else 0.0
        direction = "flat"
        if change_rate is not None and change_rate > 0:
            direction = "up"
        elif change_rate is not None and change_rate < 0:
            direction = "down"
        return {
            "store_id": store_id,
            "metric": metric,
            "latest": latest,
            "direction": direction,
            "change_rate_pct": change_rate,
            "warning_count": len(warnings),
        }

    def _waste_daily(self, store_id: str, days: int, base: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        try:
            data = self.db.query_waste_trend(store_id, days=days, include_compare=False)
        except Exception:
            data = {}
        daily = data.get("daily") or []
        if not daily:
            try:
                daily = (self.db.query_waste_count_stats(store_id, days=days) or {}).get("daily") or []
            except Exception:
                daily = []
        by_date = {row.get("date"): row for row in daily}
        store = self.hub.get_store(store_id)
        pos = getattr(store, "pos_stats", {}) or {}
        denominator = max(_safe_float(pos.get("daily_revenue")), 0.0)
        for row in base:
            source = by_date.get(row["date"]) or {}
            count = _safe_float(source.get("total_count"))
            row["raw_count"] = int(count)
            row["event_count"] = int(source.get("event_count") or 0)
            if denominator > 0:
                row["value"] = round(count / denominator * 100.0, 4)
                row["unit"] = "waste_count_per_revenue_pct"
            else:
                row["value"] = count
                row["unit"] = "waste_count"
        return base

    def _events_daily(
        self,
        store_id: str,
        metric: str,
        days: int,
        base: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        store = self.hub.get_store(store_id)
        events = store.get_events(limit=500)
        start = date_type.today() - timedelta(days=days - 1)
        rows = {row["date"]: row for row in base}
        sop_rates: Dict[str, List[float]] = defaultdict(list)
        for ev in events:
            day = _parse_day(ev.get("timestamp"))
            if not day or day < start:
                continue
            key = day.isoformat()
            event_type = str(ev.get("event_type") or "")
            meta = ev.get("metadata") or {}
            if metric == "food_safety_alerts" and self._is_food_safety_event(ev):
                rows[key]["value"] += 1
                rows[key]["event_count"] += 1
            elif metric == "sop_compliance":
                if event_type == "sop_compliance":
                    status = meta.get("status")
                    sop_rates[key].append(0.0 if status == "violation" else 100.0)
                elif event_type in ("sop_completed", "sop_violation", "sop_overdue"):
                    sop_rates[key].append(100.0 if event_type == "sop_completed" else 0.0)
        if metric == "sop_compliance":
            latest = _safe_float((getattr(store, "sop_stats", {}) or {}).get("compliance_rate"))
            for key, vals in sop_rates.items():
                rows[key]["value"] = round(sum(vals) / len(vals), 2) if vals else 0.0
                rows[key]["event_count"] = len(vals)
            if base and not sop_rates and latest:
                base[-1]["value"] = latest
                base[-1]["event_count"] = 1
        return base

    def _current_turnover(self, store_id: str) -> float:
        store = self.hub.get_store(store_id)
        pos = getattr(store, "pos_stats", {}) or {}
        if pos.get("turnover_rate") is not None:
            return _safe_float(pos.get("turnover_rate"))
        return 0.0

    def _is_food_safety_event(self, event: Dict[str, Any]) -> bool:
        event_type = str(event.get("event_type") or "")
        source = str(event.get("source") or "")
        return (
            event_type in {"cold_chain_high", "cold_chain_low", "gas_leak"}
            or event_type.startswith("iot_temp")
            or event_type.startswith("iot_humidity")
            or event_type.startswith("iot_door")
            or event_type.startswith("iot_fefo")
            or "food_safety" in event_type
            or "iot" in source
        )
