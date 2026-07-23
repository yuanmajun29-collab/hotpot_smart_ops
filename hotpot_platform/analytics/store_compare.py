"""Cross-store KPI comparison engine."""

from __future__ import annotations

import statistics
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from hotpot_platform.analytics.trend_engine import TrendEngine


METRICS = ("waste_rate", "table_turnover", "sop_compliance", "food_safety_alerts")
LOWER_IS_BETTER = {"waste_rate", "food_safety_alerts"}


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _safe_float(value: Any, default: Optional[float] = None) -> Optional[float]:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


class StoreCompareEngine:
    """Compare KPIs across stores with ranking, outliers, and trend deltas."""

    def __init__(self, hub: Any, db: Any, trend_engine: Optional[TrendEngine] = None) -> None:
        self.hub = hub
        self.db = db
        self.trends = trend_engine or TrendEngine(hub, db)

    def compare(
        self,
        zone_id: Optional[str] = None,
        region_id: Optional[str] = None,
        days: int = 7,
        time_range: Optional[Tuple[str, str]] = None,
        persist: bool = True,
    ) -> Dict[str, Any]:
        store_ids = self._filter_store_ids(zone_id=zone_id, region_id=region_id)
        rows = [self._store_row(sid, days=days) for sid in store_ids]
        metric_stats = self._metric_stats(rows)
        grids = self._comparison_grids(rows, metric_stats)
        rankings = self._rankings(rows)
        outliers = self._outliers(rows, metric_stats)

        scope_id = self._scope_id(zone_id, region_id, days, time_range)
        previous = self._get_snapshot(scope_id, "analytics_compare_snapshot") or {}
        trend_detection = self._detect_snapshot_trends(rows, previous.get("rows") or [])

        result = {
            "scope": {
                "zone_id": zone_id,
                "region_id": region_id,
                "days": days,
                "time_range": time_range,
                "store_count": len(rows),
            },
            "metrics": list(METRICS),
            "rows": rows,
            "rankings": rankings,
            "outliers": outliers,
            "comparison_grids": grids,
            "metric_stats": metric_stats,
            "trend_detection": trend_detection,
            "generated_at": _utc_now(),
        }
        if persist:
            self.db.persist_snapshot(scope_id, "analytics_compare_snapshot", result)
        return result

    def dashboard(self, zone_id: Optional[str], days: int = 7) -> Dict[str, Any]:
        compare = self.compare(zone_id=zone_id, days=days, persist=True)
        rows = compare["rows"]
        alerts = sum((row["metrics"].get("food_safety_alerts") or {}).get("value") or 0 for row in rows)
        connected = len([row for row in rows if row.get("has_data")])
        suggestions = []
        for row in rows:
            flags = row.get("flags") or []
            if flags:
                suggestions.append(
                    {
                        "store_id": row["store_id"],
                        "store_name": row["store_name"],
                        "flags": flags,
                    }
                )
        return {
            "zone_id": zone_id,
            "days": days,
            "store_count": len(rows),
            "connected_stores": connected,
            "avg_metrics": {
                metric: compare["metric_stats"].get(metric, {}).get("mean")
                for metric in METRICS
            },
            "food_safety_alerts": int(alerts),
            "outlier_count": len(compare["outliers"]),
            "top_rankings": {
                metric: compare["rankings"].get(metric, [])[:5]
                for metric in METRICS
            },
            "stores": rows,
            "priority_stores": suggestions[:10],
            "generated_at": compare["generated_at"],
        }

    def _store_row(self, store_id: str, days: int) -> Dict[str, Any]:
        meta = self._store_meta(store_id)
        store = self.hub.get_store(store_id)
        metrics: Dict[str, Dict[str, Any]] = {}
        for metric in METRICS:
            trend = self.trends.trend(store_id, metric, days=days)
            latest = trend["daily"][-1] if trend.get("daily") else {"value": 0.0}
            metrics[metric] = {
                "value": latest.get("value"),
                "unit": latest.get("unit", self._unit(metric)),
                "change_rate_pct": trend.get("change_rate_pct"),
                "warnings": trend.get("warnings") or [],
            }
            if "raw_count" in latest:
                metrics[metric]["raw_count"] = latest["raw_count"]
        flags = self._store_flags(metrics)
        return {
            "store_id": store_id,
            "store_name": meta.get("store_name", store_id),
            "region_id": meta.get("region_id"),
            "city": meta.get("city", ""),
            "status": meta.get("status", ""),
            "has_data": store.has_data(),
            "metrics": metrics,
            "flags": flags,
        }

    def _filter_store_ids(self, zone_id: Optional[str], region_id: Optional[str]) -> List[str]:
        stores = self.hub.list_stores()
        regions = getattr(self.hub, "_regions", []) or []
        if zone_id:
            child_regions = {
                region.get("region_id")
                for region in regions
                if region.get("parent_zone_id") == zone_id
            }
            stores = [s for s in stores if s.get("region_id") in child_regions]
        if region_id:
            stores = [s for s in stores if s.get("region_id") == region_id]
        return sorted({s["store_id"] for s in stores if s.get("store_id")})

    def _metric_stats(self, rows: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
        stats: Dict[str, Dict[str, Any]] = {}
        for metric in METRICS:
            values = [
                _safe_float(row["metrics"][metric].get("value"))
                for row in rows
                if _safe_float(row["metrics"][metric].get("value")) is not None
            ]
            if not values:
                stats[metric] = {"mean": None, "stdev": 0.0, "count": 0}
                continue
            mean = statistics.mean(values)
            stdev = statistics.pstdev(values) if len(values) > 1 else 0.0
            stats[metric] = {"mean": round(mean, 4), "stdev": round(stdev, 4), "count": len(values)}
        return stats

    def _rankings(self, rows: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
        rankings: Dict[str, List[Dict[str, Any]]] = {}
        for metric in METRICS:
            reverse = metric not in LOWER_IS_BETTER
            ranked = sorted(
                rows,
                key=lambda row: _safe_float(row["metrics"][metric].get("value"), -1e12 if reverse else 1e12),
                reverse=reverse,
            )
            rankings[metric] = [
                {
                    "rank": idx + 1,
                    "store_id": row["store_id"],
                    "store_name": row["store_name"],
                    "value": row["metrics"][metric].get("value"),
                }
                for idx, row in enumerate(ranked)
            ]
        return rankings

    def _outliers(
        self,
        rows: List[Dict[str, Any]],
        metric_stats: Dict[str, Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        outliers: List[Dict[str, Any]] = []
        for row in rows:
            for metric in METRICS:
                stat = metric_stats.get(metric) or {}
                mean = stat.get("mean")
                stdev = stat.get("stdev") or 0.0
                value = _safe_float(row["metrics"][metric].get("value"))
                if mean is None or value is None or stdev <= 0:
                    continue
                high = mean + 2 * stdev
                low = mean - 2 * stdev
                if value > high or value < low:
                    direction = "high" if value > high else "low"
                    outliers.append(
                        {
                            "store_id": row["store_id"],
                            "store_name": row["store_name"],
                            "metric": metric,
                            "value": value,
                            "mean": mean,
                            "stdev": stdev,
                            "direction": direction,
                            "severity": "bad"
                            if (metric in LOWER_IS_BETTER and direction == "high")
                            or (metric not in LOWER_IS_BETTER and direction == "low")
                            else "good",
                        }
                    )
        return outliers

    def _comparison_grids(
        self,
        rows: List[Dict[str, Any]],
        metric_stats: Dict[str, Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        grids: List[Dict[str, Any]] = []
        for row in rows:
            cells = {}
            for metric in METRICS:
                value = _safe_float(row["metrics"][metric].get("value"), 0.0) or 0.0
                mean = metric_stats.get(metric, {}).get("mean")
                if mean is None:
                    delta = None
                    status = "no_baseline"
                else:
                    delta = round(value - mean, 4)
                    bad = value > mean if metric in LOWER_IS_BETTER else value < mean
                    status = "below_peer" if bad else "above_peer"
                cells[metric] = {
                    "value": value,
                    "peer_delta": delta,
                    "status": status,
                }
            grids.append({"store_id": row["store_id"], "store_name": row["store_name"], "cells": cells})
        return grids

    def _detect_snapshot_trends(
        self,
        rows: List[Dict[str, Any]],
        previous_rows: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        previous_by_store = {row.get("store_id"): row for row in previous_rows}
        changes: List[Dict[str, Any]] = []
        improving = 0
        worsening = 0
        for row in rows:
            prev = previous_by_store.get(row["store_id"])
            if not prev:
                continue
            for metric in METRICS:
                curr_val = _safe_float(row["metrics"][metric].get("value"))
                prev_val = _safe_float((prev.get("metrics") or {}).get(metric, {}).get("value"))
                if curr_val is None or prev_val is None or curr_val == prev_val:
                    continue
                better = curr_val < prev_val if metric in LOWER_IS_BETTER else curr_val > prev_val
                improving += 1 if better else 0
                worsening += 0 if better else 1
                changes.append(
                    {
                        "store_id": row["store_id"],
                        "metric": metric,
                        "previous": prev_val,
                        "current": curr_val,
                        "direction": "improving" if better else "worsening",
                    }
                )
        return {"improving": improving, "worsening": worsening, "changes": changes[:100]}

    def _store_flags(self, metrics: Dict[str, Dict[str, Any]]) -> List[str]:
        flags: List[str] = []
        if (_safe_float(metrics["food_safety_alerts"].get("value"), 0.0) or 0.0) > 0:
            flags.append("food_safety_attention")
        if (_safe_float(metrics["sop_compliance"].get("value"), 100.0) or 100.0) < 80:
            flags.append("sop_low")
        if (_safe_float(metrics["waste_rate"].get("change_rate_pct"), 0.0) or 0.0) >= 15:
            flags.append("waste_rising")
        return flags

    def _store_meta(self, store_id: str) -> Dict[str, Any]:
        for item in self.hub.list_stores():
            if item.get("store_id") == store_id:
                return dict(item)
        return {"store_id": store_id}

    def _get_snapshot(self, store_id: str, kind: str) -> Optional[Dict[str, Any]]:
        getter = getattr(self.db, "get_snapshot", None)
        if not getter:
            return None
        try:
            snap = getter(store_id, kind)
            return snap if isinstance(snap, dict) else None
        except Exception:
            return None

    def _scope_id(
        self,
        zone_id: Optional[str],
        region_id: Optional[str],
        days: int,
        time_range: Optional[Tuple[str, str]],
    ) -> str:
        if time_range:
            return f"__analytics_compare__:{zone_id or '*'}:{region_id or '*'}:{time_range[0]}:{time_range[1]}"
        return f"__analytics_compare__:{zone_id or '*'}:{region_id or '*'}:{days}"

    def _unit(self, metric: str) -> str:
        if metric == "sop_compliance":
            return "pct"
        if metric == "table_turnover":
            return "turns_per_day"
        if metric == "food_safety_alerts":
            return "count"
        return "waste_rate"
