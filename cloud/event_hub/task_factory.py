"""Task factory (DEV-522 / ADR-010).

Turns operational events into tasks automatically, so SOP violations / safety
alerts / table-clearing no longer rely on manual creation. Idempotent: each
source event maps to exactly one task via source_id = "evt:{event_id}".

收口的三类来源：
  - SOP 违规 (F-S04)         -> task_type=sop_violation, P1
  - 安全告警 critical (F-A04) -> task_type=safety_alert,  P0
  - 待清台 (F-T03)           -> task_type=cleaning,      P2
其余可识别来源（IoT 异常、来料拒收）一并映射；无规则命中则不生单。
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from cloud.event_hub.task_store import task_store

# level -> default priority
_LEVEL_PRIORITY = {"critical": "P0", "warn": "P1", "info": "P2"}

# event_type / source hints -> (task_type, priority, group)
_SAFETY_HINTS = ("smoke", "gas", "燃气", "烟雾", "fire", "cold_chain", "冷链", "temp_breach")


def _meta(event: Dict[str, Any]) -> Dict[str, Any]:
    m = event.get("metadata")
    return m if isinstance(m, dict) else {}


def classify(event: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Return a task spec dict for an event, or None when no rule matches."""
    etype = str(event.get("event_type", ""))
    level = str(event.get("level", "info"))
    meta = _meta(event)
    msg = str(event.get("message", ""))

    # 1) SOP violation -> integration replacing manual F-S04 assignment
    if etype in ("sop_violation", "sop_assigned") or meta.get("sop_id"):
        return {
            "task_type": "sop_violation",
            "priority": _LEVEL_PRIORITY.get(level, "P1"),
            "title": meta.get("sop_name") or msg or meta.get("sop_id") or "SOP 整改",
            "ref_type": "sop",
            "ref_id": meta.get("sop_id") or event.get("event_id"),
            "assignee_id": meta.get("assignee"),
            "assignee_group": "kitchen",
        }

    # 2) Safety / critical alert -> immediate handling task
    if level == "critical" or etype.startswith("alert_") or any(h in etype or h in msg for h in _SAFETY_HINTS):
        return {
            "task_type": "safety_alert",
            "priority": "P0" if level == "critical" else _LEVEL_PRIORITY.get(level, "P1"),
            "title": msg or etype or "安全处置",
            "ref_type": "alert",
            "ref_id": event.get("event_id"),
            "assignee_group": "kitchen",
        }

    # 3) Table needs clearing -> cleaning task
    if (etype.startswith("table_") and etype.replace("table_", "") in ("need_clean", "checkout")) \
            or "待清" in msg:
        table_id = event.get("table_id") or meta.get("table_id")
        return {
            "task_type": "cleaning",
            "priority": "P2",
            "title": f"清台：{table_id}" if table_id else (msg or "待清台"),
            "ref_type": "table",
            "ref_id": table_id or event.get("event_id"),
            "assignee_group": "fronthall",
        }

    # 4) IoT anomaly (door/temp)
    if etype.startswith("iot_") or "门磁" in msg or "超温" in msg:
        return {
            "task_type": "iot_anomaly",
            "priority": _LEVEL_PRIORITY.get(level, "P1"),
            "title": msg or etype or "IoT 异常处置",
            "ref_type": "iot",
            "ref_id": event.get("event_id"),
            "assignee_group": "kitchen",
        }

    return None


def spawn_task_for_event(db: Any, store_id: str, event: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Idempotently create a task from an event. Returns the task, or None if no rule."""
    spec = classify(event)
    if not spec:
        return None
    event_id = event.get("event_id") or event.get("id")
    source_id = f"evt:{event_id}" if event_id else None
    return task_store(db).create(
        store_id,
        created_by="system",
        source="auto",
        source_id=source_id,
        detail=str(event.get("message", "")),
        **spec,
    )


# ---- explicit helpers for the three收口 sources ----------------------------

def spawn_sop_violation(db: Any, store_id: str, *, sop_id: str, sop_name: str,
                        assignee: Optional[str] = None, event_id: Optional[str] = None,
                        level: str = "warn") -> Optional[Dict[str, Any]]:
    return spawn_task_for_event(db, store_id, {
        "event_id": event_id or f"sop:{sop_id}",
        "event_type": "sop_violation", "level": level,
        "message": f"SOP 整改：{sop_name}",
        "metadata": {"sop_id": sop_id, "sop_name": sop_name, "assignee": assignee},
    })


def spawn_cleaning(db: Any, store_id: str, *, table_id: str,
                   event_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
    return spawn_task_for_event(db, store_id, {
        "event_id": event_id or f"clean:{table_id}",
        "event_type": "table_need_clean", "level": "info",
        "message": f"{table_id} 待清台", "table_id": table_id,
    })
