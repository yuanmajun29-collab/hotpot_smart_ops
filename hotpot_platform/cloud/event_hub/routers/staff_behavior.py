"""Staff behavior routes — Phase 3.

POST /api/staff-behavior/event
    Ingest staff behavior detection event from edge.

GET /api/staff-behavior/stats
    Aggregated staff behavior stats (PPE compliance, alert counts, loitering).

GET /api/staff-behavior/alerts
    Recent staff behavior alerts list.

GET /api/staff-behavior/timeline
    Timeline of staff behavior events for dashboard.
"""

from __future__ import annotations

from datetime import datetime, timezone, date as date_type
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from hotpot_platform.cloud.event_hub import runtime
from hotpot_platform.cloud.event_hub.auth import (
    AuthContext,
    enforce_store_write,
    get_auth_context,
)
from hotpot_platform.cloud.event_hub.hub_core import DEFAULT_STORE_ID

router = APIRouter()
ROUTER_TAG = "staff_behavior"


# ── Models ───────────────────────────────────────────────────────

class StaffBehaviorEventBody(BaseModel):
    """Staff behavior detection event from edge."""

    event_id: str
    store_id: str
    level: str = "info"
    source: str = "staff_behavior"
    event_type: str = "staff_behavior"
    timestamp: str
    message: str = ""
    metadata: Optional[Dict[str, Any]] = None


class StaffBehaviorStatsQuery(BaseModel):
    """Query params for stats endpoint."""

    store_id: Optional[str] = None
    days: int = 7
    zone: Optional[str] = None


# ── Routes ───────────────────────────────────────────────────────


@router.post("/api/v1/staff-behavior/event")
def ingest_staff_behavior_event(
    body: StaffBehaviorEventBody,
    auth: AuthContext = Depends(get_auth_context),
) -> Dict[str, Any]:
    """Ingest a staff behavior detection event from edge device.

    Forwards to Hub store as a typed event.

    **请求示例**:
    ```json
    {
      "event_id": "staff-abc123",
      "store_id": "store_yuhuan",
      "level": "warning",
      "source": "staff_behavior/cam_staff_01",
      "event_type": "staff_behavior",
      "timestamp": "2026-07-16T15:30:00+00:00",
      "message": "Staff detection: 3 person(s), PPE 66.7%",
      "metadata": {
        "camera_id": "cam_staff_01",
        "zone": "kitchen",
        "person_count": 3,
        "ppe_compliance_rate": 66.7,
        "whispering_pairs": 1,
        "loitering_count": 0,
        "alerts": [],
        "persons": []
      }
    }
    ```
    """
    sid = body.store_id or auth.store_id or DEFAULT_STORE_ID
    enforce_store_write(auth, sid)

    event = {
        "event_id": body.event_id,
        "store_id": sid,
        "level": body.level,
        "source": body.source,
        "event_type": body.event_type,
        "timestamp": body.timestamp,
        "message": body.message,
        "metadata": body.metadata or {},
    }

    store = runtime.hub.get_store(sid)
    store.add_event(event)

    # If any critical alerts, also push to alert system
    meta = body.metadata or {}
    alerts = meta.get("alerts", [])
    critical_alerts = [a for a in alerts if a.get("severity") == "critical"]
    if critical_alerts:
        for alert in critical_alerts:
            store.add_event(
                {
                    "event_id": f"staff-alert-{body.event_id}-{alert['type']}",
                    "store_id": sid,
                    "level": "critical",
                    "source": f"staff_behavior/{meta.get('camera_id', 'unknown')}",
                    "event_type": f"staff_{alert['type']}",
                    "timestamp": body.timestamp,
                    "message": f"Staff {alert['type']}: {alert.get('person_id', 'unknown')} in zone {meta.get('zone', 'unknown')}",
                    "metadata": alert,
                }
            )

    return {"ok": True, "event_id": body.event_id}


@router.get("/api/v1/staff-behavior/stats")
def staff_behavior_stats(
    store_id: Optional[str] = Query(None, description="门店 ID"),
    days: int = Query(7, ge=1, le=90, description="查询天数"),
    zone: Optional[str] = Query(None, description="区域过滤"),
    auth: AuthContext = Depends(get_auth_context),
) -> Dict[str, Any]:
    """Aggregated staff behavior statistics.

    Returns:
        - total_events: total staff behavior events in period
        - ppe_compliance_trend: daily PPE compliance rate
        - alert_breakdown: by alert type
        - loitering_trend: daily loitering incidents
        - latest_detection: most recent detection result
    """
    sid = store_id or auth.store_id or DEFAULT_STORE_ID
    enforce_store_write(auth, sid)

    store = runtime.hub.get_store(sid)
    events = store.get_events(limit=500)

    from datetime import timedelta as _td

    cutoff = datetime.now(timezone.utc) - _td(days=days)
    cutoff_str = cutoff.strftime("%Y-%m-%d")

    staff_events = [
        e
        for e in events
        if e.get("event_type") == "staff_behavior"
        and e.get("timestamp", "")[:10] >= cutoff_str
    ]

    if zone:
        staff_events = [
            e
            for e in staff_events
            if (e.get("metadata", {}).get("zone") or "") == zone
        ]

    # Daily aggregations
    daily_ppe: Dict[str, List[float]] = {}
    daily_loiter: Dict[str, int] = {}
    alert_types: Dict[str, int] = {}

    for ev in staff_events:
        ts = ev.get("timestamp", "")[:10]
        meta = ev.get("metadata", {})
        ppe = meta.get("ppe_compliance_rate")
        if ppe is not None:
            daily_ppe.setdefault(ts, []).append(ppe)
        loiter = meta.get("loitering_count", 0)
        daily_loiter[ts] = daily_loiter.get(ts, 0) + loiter
        for alert in meta.get("alerts", []):
            t = alert.get("type", "unknown")
            alert_types[t] = alert_types.get(t, 0) + 1

    # Build trend arrays
    dates = sorted(set(list(daily_ppe.keys()) + list(daily_loiter.keys())))[
        -days:
    ]
    ppe_trend = [
        round(sum(daily_ppe.get(d, [0])) / max(len(daily_ppe.get(d, [])), 1), 1)
        for d in dates
    ]
    loiter_trend = [daily_loiter.get(d, 0) for d in dates]

    # Latest detection
    latest = staff_events[0] if staff_events else None
    latest_summary = None
    if latest:
        meta = latest.get("metadata", {})
        latest_summary = {
            "timestamp": latest.get("timestamp"),
            "person_count": meta.get("person_count", 0),
            "ppe_compliance_rate": meta.get("ppe_compliance_rate", 0),
            "whispering_pairs": meta.get("whispering_pairs", 0),
            "loitering_count": meta.get("loitering_count", 0),
            "alert_count": len(meta.get("alerts", [])),
        }

    return {
        "store_id": sid,
        "days": days,
        "zone": zone,
        "total_events": len(staff_events),
        "dates": dates,
        "ppe_compliance_trend": ppe_trend,
        "loitering_trend": loiter_trend,
        "alert_breakdown": alert_types,
        "latest_detection": latest_summary,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/api/v1/staff-behavior/alerts")
def staff_behavior_alerts(
    store_id: Optional[str] = Query(None, description="门店 ID"),
    days: int = Query(7, ge=1, le=90, description="查询天数"),
    level: Optional[str] = Query(None, description="告警级别过滤"),
    auth: AuthContext = Depends(get_auth_context),
) -> Dict[str, Any]:
    """Recent staff behavior alerts."""
    sid = store_id or auth.store_id or DEFAULT_STORE_ID
    enforce_store_write(auth, sid)

    store = runtime.hub.get_store(sid)
    events = store.get_events(limit=500)

    from datetime import timedelta as _td

    cutoff = datetime.now(timezone.utc) - _td(days=days)
    cutoff_str = cutoff.strftime("%Y-%m-%d")

    alert_events = [
        e
        for e in events
        if e.get("event_type", "").startswith("staff_")
        and e.get("event_type") != "staff_behavior"
        and e.get("timestamp", "")[:10] >= cutoff_str
    ]

    if level:
        alert_events = [
            e
            for e in alert_events
            if e.get("level") == level
        ]

    return {
        "store_id": sid,
        "alerts": [
            {
                "event_id": e.get("event_id"),
                "level": e.get("level"),
                "type": e.get("event_type"),
                "message": e.get("message"),
                "timestamp": e.get("timestamp"),
                "metadata": e.get("metadata"),
            }
            for e in alert_events
        ],
        "count": len(alert_events),
    }


@router.get("/api/v1/staff-behavior/timeline")
def staff_behavior_timeline(
    store_id: Optional[str] = Query(None, description="门店 ID"),
    limit: int = Query(50, ge=1, le=200, description="返回条数"),
    auth: AuthContext = Depends(get_auth_context),
) -> Dict[str, Any]:
    """Timeline of staff behavior detection events."""
    sid = store_id or auth.store_id or DEFAULT_STORE_ID
    enforce_store_write(auth, sid)

    store = runtime.hub.get_store(sid)
    events = store.get_events(limit=limit * 2)

    staff_events = [
        e
        for e in events
        if e.get("event_type") == "staff_behavior"
    ][:limit]

    return {
        "store_id": sid,
        "events": [
            {
                "event_id": e.get("event_id"),
                "timestamp": e.get("timestamp"),
                "level": e.get("level"),
                "message": e.get("message"),
                "source": e.get("source"),
                "metadata": e.get("metadata"),
            }
            for e in staff_events
        ],
        "count": len(staff_events),
    }
