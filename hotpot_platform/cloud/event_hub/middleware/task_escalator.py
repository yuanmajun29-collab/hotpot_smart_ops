"""Task escalation scheduler (MVP: cleaning-task timeout → auto-escalate).

Monitors pending cleaning tasks and escalates unresponsive ones:
  - T+3min  → push to 领班 (front-hall lead) with reminder
  - T+5min  → escalate to 店长 (store manager) + alert flag

Runs as a background thread inside Event Hub process.
Idempotent: same task escalated only once per level.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger("task_escalator")

# ---- Escalation policy constants -------------------------------------------

ESCALATION_LEVELS = {
    "reminder": {"seconds": 180, "label": "领班提醒", "target_role": "front_hall_lead"},
    "escalation": {"seconds": 300, "label": "店长升级", "target_role": "store_manager"},
}

# task_type → (default_due_seconds, escalation_enabled)
TASK_ESCALATION_POLICY = {
    "cleaning": {"due_seconds": 180, "enabled": True},
}


@dataclass
class EscalationEvent:
    """Record of an escalation action taken."""
    task_id: str
    store_id: str
    level: str  # "reminder" | "escalation"
    triggered_at: str
    target_role: str
    message: str
    auto: bool = True


class TaskEscalator:
    """Background scheduler for task timeout escalation.

    Usage:
        esc = TaskEscalator(db, interval_sec=30)
        esc.start()
        # ... later ...
        esc.stop()
    """

    def __init__(
        self,
        db: Any,
        *,
        check_interval_sec: float = 30.0,
        alert_callback=None,
    ):
        self.db = db
        self.check_interval = check_interval_sec
        self.alert_callback = alert_callback  # callable(event) -> None
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._escalated_cache: Dict[str, str] = {}  # task_id -> highest level escalated
        self._lock = threading.Lock()

    def start(self) -> None:
        """Start background escalation checker."""
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="task-escalator")
        self._thread.start()
        logger.info("[TaskEscalator] Started (interval=%.1fs)", self.check_interval)

    def stop(self, timeout: float = 5.0) -> None:
        """Signal stop and wait for thread to finish."""
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=timeout)
        logger.info("[TaskEscalator] Stopped")

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def _now_iso(self) -> str:
        """Return current UTC time as ISO string (for testing)."""
        from datetime import datetime, timezone
        return datetime.now(timezone.utc).replace(microsecond=0).isoformat()

    # ---- core loop -------------------------------------------------------

    def _loop(self) -> None:
        while not self._stop_event.is_set():
            if self._stop_event.wait(timeout=self.check_interval):
                break
            try:
                self._check_and_escalate()
            except Exception:
                logger.exception("[TaskEscalator] Error in check cycle")
        logger.debug("[TaskEscalator] Loop exited")

    def _check_and_escalate(self) -> List[EscalationEvent]:
        """One pass: find overdue tasks and escalate if needed."""
        from hotpot_platform.cloud.event_hub.task_store import task_store

        store = task_store(self.db)
        now_iso = store.utc_now_iso()

        # Get all pending/in_progress cleaning tasks
        tasks = store.list_tasks(
            "store_jiaojiang",  # TODO: multi-store support
            status="pending",
            task_type="cleaning",
            limit=100,
        )
        tasks += store.list_tasks(
            "store_jiaojiang",
            status="in_progress",
            task_type="cleaning",
            limit=100,
        )

        events: List[EscalationEvent] = []
        for task in tasks:
            event = self._evaluate_task(task, now_iso)
            if event:
                events.append(event)
                self._record_escalation(store, event)
                if self.alert_callback:
                    try:
                        self.alert_callback(event)
                    except Exception:
                        logger.exception("[TaskEscalator] Alert callback error")

        if events:
            logger.info("[TaskEscalator] %d escalation(s) this cycle", len(events))
        return events

    def _evaluate_task(self, task: Dict[str, Any], now_iso: str) -> Optional[EscalationEvent]:
        """Check if a single task needs escalation. Returns event or None."""
        task_id = task.get("task_id", "")
        created_at = task.get("created_at", "")
        task_type = task.get("task_type", "")

        if not created_at:
            return None

        # Only escalate task types that have an active policy
        if task_type not in TASK_ESCALATION_POLICY:
            return None
        if not TASK_ESCALATION_POLICY[task_type].get("enabled", False):
            return None

        # Parse ISO timestamp to compare
        try:
            from datetime import datetime, timezone
            created_dt = datetime.fromisoformat(created_at)
            now_dt = datetime.fromisoformat(now_iso)
            age_sec = (now_dt - created_dt).total_seconds()
        except (ValueError, TypeError):
            return None

        with self._lock:
            already_escalated = self._escalated_cache.get(task_id, "")

        # Check escalation levels in reverse order (highest first)
        # so we always return the most severe applicable level
        level_order = list(reversed(list(ESCALATION_LEVELS.keys())))
        original_order = list(ESCALATION_LEVELS.keys())  # for idx comparison
        for level_name in level_order:
            level_cfg = ESCALATION_LEVELS[level_name]
            threshold = level_cfg["seconds"]
            if age_sec < threshold:
                continue

            # Already escalated to this level or higher? (compare using original order)
            current_idx = (
                original_order.index(already_escalated)
                if already_escalated in original_order
                else -1
            )
            new_idx = original_order.index(level_name)

            if new_idx > current_idx:
                event = EscalationEvent(
                    task_id=task_id,
                    store_id=task.get("store_id", ""),
                    level=level_name,
                    triggered_at=now_iso,
                    target_role=level_cfg["target_role"],
                    message=(
                        f"清台任务 {task_id} 已超时 {int(age_sec)}s"
                        f"（阈值 {threshold}s）→ {level_cfg['label']}"
                    ),
                )
                self._escalated_cache[task_id] = level_name
                return event

        return None

    def _record_escalation(self, store, event: EscalationEvent) -> None:
        """Write escalation event to task_events audit trail."""
        try:
            store._write_event(
                store._connect(),
                event.task_id,
                f"escalate_{event.level}",
                "system",
                None,
                None,
                note=event.message,
            )
        except Exception:
            logger.exception("[TaskEscalator] Failed to write audit record for %s", event.task_id)

    # ---- public API ------------------------------------------------------

    def get_status(self) -> Dict[str, Any]:
        """Return escalator state for monitoring API."""
        with self._lock:
            return {
                "running": self.is_running,
                "check_interval_sec": self.check_interval,
                "escalated_count": len(self._escalated_cache),
                "escalated_tasks": dict(self._escalated_cache),
                "policy": TASK_ESCALATION_POLICY,
                "levels": {k: {"seconds": v["seconds"], "label": v["label"]}
                          for k, v in ESCALATION_LEVELS.items()},
            }

    def reset_task(self, task_id: str) -> None:
        """Clear escalation cache for a task (e.g. after manual reassign)."""
        with self._lock:
            self._escalated_cache.pop(task_id, None)


# ---- singleton for Event Hub runtime -----------------------------------

_instance: Optional[TaskEscalator] = None


def get_escalator(db=None) -> TaskEscalator:
    """Get or create the global TaskEscalator instance."""
    global _instance
    if _instance is None and db is not None:
        _instance = TaskEscalator(db)
    if _instance is None:
        raise RuntimeError("TaskEscalator not initialized; call init_escalator(db) first")
    return _instance


def init_escalator(db, **kwargs) -> TaskEscalator:
    """Initialize and start the global escalator."""
    global _instance
    _instance = TaskEscalator(db, **kwargs)
    _instance.start()
    return _instance


def stop_escalator() -> None:
    """Stop the global escalator."""
    global _instance
    if _instance:
        _instance.stop()
        _instance = None
