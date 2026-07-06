from __future__ import annotations

from typing import Any, Dict, List


def compute_store_health(metrics: Dict[str, Any]) -> Dict[str, Any]:
    """F-HQ06/F-HQ07: derive ok | warn | critical from store metrics."""
    reasons: List[str] = []
    status = "ok"
    critical_alerts = int(metrics.get("critical_alerts") or 0)
    warn_alerts = int(metrics.get("warn_alerts") or 0)
    sop = metrics.get("sop_compliance_rate")
    cost_var = metrics.get("cost_variance_pct")
    need_clean = int(metrics.get("need_clean") or 0)

    if critical_alerts > 0:
        status = "critical"
        reasons.append(f"严重告警 {critical_alerts} 条未闭环")
    if sop is not None and float(sop) < 70:
        status = "critical"
        reasons.append(f"SOP 合规仅 {sop}%")
    elif sop is not None and float(sop) < 85 and status != "critical":
        status = "warn"
        reasons.append(f"SOP 合规 {sop}% 偏低")
    if cost_var is not None and float(cost_var) > 5:
        if status != "critical":
            status = "warn"
        reasons.append(f"来料偏差 {cost_var}%")
    if need_clean >= 3:
        if status == "ok":
            status = "warn"
        reasons.append(f"待清台 {need_clean} 桌积压")
    if warn_alerts >= 3 and status == "ok":
        status = "warn"
        reasons.append(f"警告事件 {warn_alerts} 条")

    score = 100
    score -= critical_alerts * 15
    score -= max(0, warn_alerts - 1) * 3
    if sop is not None:
        score -= max(0, 90 - float(sop)) * 0.5
    if need_clean:
        score -= need_clean * 2
    score = max(0, min(100, int(score)))

    return {"status": status, "score": score, "reasons": reasons}


def _rollup_from_rows(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    health_counts = {"ok": 0, "warn": 0, "critical": 0}
    for r in rows:
        health_counts[r["health"]["status"]] = health_counts.get(r["health"]["status"], 0) + 1
    sop_vals = [r["metrics"]["sop_compliance_rate"] for r in rows if r["metrics"].get("sop_compliance_rate") is not None]
    return {
        "store_count": len(rows),
        "critical_stores": health_counts.get("critical", 0),
        "warn_stores": health_counts.get("warn", 0),
        "ok_stores": health_counts.get("ok", 0),
        "total_critical_alerts": sum(r["metrics"].get("critical_alerts", 0) for r in rows),
        "total_need_clean": sum(r["metrics"].get("need_clean", 0) for r in rows),
        "avg_sop_compliance": round(sum(sop_vals) / len(sop_vals), 1) if sop_vals else None,
    }


def _region_worst_health(rows: List[Dict[str, Any]], status: str = "active") -> str:
    if status == "planned" or not rows:
        return "planned"
    statuses = [r["health"]["status"] for r in rows]
    if "critical" in statuses:
        return "critical"
    if "warn" in statuses:
        return "warn"
    return "ok"
