"""T2 tests: task_escalator timeout escalation mechanism (MVP).

Covers:
  - Escalation level thresholds (3min/5min)
  - Idempotency (same task not re-escalated to same level)
  - Background thread lifecycle
  - Status API
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

# Path setup (same pattern as T1)
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

# Pre-mock heavy deps
sys.modules["edge.common.detector.hotpot_detector"] = MagicMock()
sys.modules["edge.front_hall.inference.sources"] = MagicMock()

import common.hub_client  # noqa: E402
import common.store_config  # noqa: E402

from datetime import datetime, timezone  # noqa: E402
from unittest.mock import patch as mock_patch  # noqa: E402
from hotpot_platform.cloud.event_hub.middleware.task_escalator import (  # noqa: E402
    ESCALATION_LEVELS,
    TaskEscalator,
    EscalationEvent,
    TASK_ESCALATION_POLICY,
    init_escalator,
    stop_escalator,
)


# ---- Fixtures -----------------------------------------------------------

def _make_db_mock():
    db = MagicMock()
    db._connect.return_value.__enter__ = MagicMock(return_value=MagicMock())
    db._connect.return_value.__exit__ = MagicMock(return_value=False)
    db._lock = threading_mock_lock() if 'threading_mock_lock' not in dir() else MagicMock()
    return db


def _mock_task_store(db):
    """Create a mock task_store that returns configurable tasks."""
    store = MagicMock()
    store.utc_now_iso.return_value = datetime.now(timezone.utc).replace(microsecond=0).isoformat()

    def list_tasks_side_effect(store_id, status, task_type, limit=50, **kw):
        # Return tasks based on what was set in _test_tasks attribute
        return getattr(list_tasks_side_effect, "_test_tasks", [])

    store.list_tasks.side_effect = list_tasks_side_effect
    return store


def _make_task(task_id, age_seconds=0, status="pending", task_type="cleaning"):
    """Create a fake task dict with given age."""
    from datetime import timedelta
    now = datetime.now(timezone.utc).replace(microsecond=0)
    created = (now - timedelta(seconds=age_seconds)).isoformat()
    return {
        "task_id": task_id,
        "store_id": "store_jiaojiang",
        "status": status,
        "task_type": task_type,
        "created_at": created,
        "title": f"清台：{task_id}",
    }


class threading_mock_lock:
    """Minimal lock mock for testing."""
    def __enter__(self): return self
    def __exit__(self, *a): pass


# ======================================================================
# Group 1: Escalation threshold logic (5 tests)
# ======================================================================

class TestEscalationThresholds:

    def test_no_escalation_for_fresh_task(self):
        """Task <3min old → no escalation."""
        esc = TaskEscalator(_make_db_mock(), check_interval_sec=0.1)
        task = _make_task("T01", age_seconds=60)  # 1 min
        result = esc._evaluate_task(task, esc._now_iso())
        assert result is None

    def test_reminder_at_3min(self):
        """Task >=3min → reminder level."""
        esc = TaskEscalator(_make_db_mock(), check_interval_sec=0.1)
        task = _make_task("T02", age_seconds=200)  # 3m20s
        result = esc._evaluate_task(task, esc._now_iso())
        assert result is not None
        assert result.level == "reminder"
        assert result.target_role == "front_hall_lead"
        assert "领班提醒" in result.message

    def test_escalation_at_5min(self):
        """Task >=5min → escalation level."""
        esc = TaskEscalator(_make_db_mock(), check_interval_sec=0.1)
        task = _make_task("T03", age_seconds=320)  # 5m20s
        result = esc._evaluate_task(task, esc._now_iso())
        assert result is not None
        assert result.level == "escalation"
        assert result.target_role == "store_manager"
        assert "店长升级" in result.message

    def test_non_cleaning_task_not_escalated(self):
        """Non-cleaning tasks are NOT escalated by this policy."""
        esc = TaskEscalator(_make_db_mock(), check_interval_sec=0.1)
        task = _make_task("T04", age_seconds=400, task_type="sop_violation")
        result = esc._evaluate_task(task, esc._now_iso())
        assert result is None


# ======================================================================
# Group 2: Idempotency (3 tests)
# ======================================================================

class TestEscalationIdempotency:

    def test_same_level_not_repeated(self):
        """Same task not escalated twice to same level."""
        esc = TaskEscalator(_make_db_mock(), check_interval_sec=0.1)
        task = _make_task("T05", age_seconds=200)

        event1 = esc._evaluate_task(task, esc._now_iso())
        event2 = esc._evaluate_task(task, esc._now_iso())

        assert event1 is not None  # First time triggers
        assert event2 is None     # Second time does not repeat

    def test_can_escalate_to_higher_level(self):
        """Task can escalate from reminder → escalation over time."""
        esc = TaskEscalator(_make_db_mock(), check_interval_sec=0.1)
        task = _make_task("T06", age_seconds=200)

        # At 3min: should get reminder
        event1 = esc._evaluate_task(task, esc._now_iso())
        assert event1 is not None
        assert event1.level == "reminder"

        # Simulate aging past 5min
        task["created_at"] = (
            datetime.now(timezone.utc).replace(microsecond=0)
        ).__sub__(__import__("datetime").timedelta(seconds=320)).isoformat()

        event2 = esc._evaluate_task(task, esc._now_iso())
        assert event2 is not None
        assert event2.level == "escalation"  # Upgraded!

    def test_reset_clears_cache(self):
        """reset_task() clears escalation cache for a task."""
        esc = TaskEscalator(_make_db_mock(), check_interval_sec=0.1)
        task = _make_task("T07", age_seconds=200)

        esc._evaluate_task(task, esc._now_iso())  # Escalate once
        assert "T07" in esc._escalated_cache

        esc.reset_task("T07")
        assert "T07" not in esc._escalated_cache

        # Can now escalate again
        event = esc._evaluate_task(task, esc._now_iso())
        assert event is not None


# ======================================================================
# Group 3: Thread lifecycle (3 tests)
# ======================================================================

class TestThreadLifecycle:

    def test_start_creates_thread(self):
        """start() creates a background daemon thread."""
        esc = TaskEscalator(_make_db_mock(), check_interval_sec=0.1)
        esc.start()
        assert esc.is_running
        esc.stop(timeout=1.0)

    def test_stop_terminates_thread(self):
        """stop() terminates the thread within timeout."""
        esc = TaskEscalator(_make_db_mock(), check_interval_sec=0.1)
        esc.start()
        assert esc.is_running
        esc.stop(timeout=1.0)
        assert not esc.is_running

    def test_double_start_safe(self):
        """Calling start() twice doesn't create extra threads."""
        esc = TaskEscalator(_make_db_mock(), check_interval_sec=0.1)
        esc.start()
        t1 = esc._thread
        esc.start()  # Should be no-op
        assert esc._thread is t1
        esc.stop(timeout=1.0)


# ======================================================================
# Group 4: Status API (2 tests)
# ======================================================================

class TestStatusAPI:

    def test_status_returns_policy_info(self):
        """get_status() returns escalation config."""
        esc = TaskEscalator(_make_db_mock(), check_interval_sec=42.0)
        status = esc.get_status()
        assert status["running"] is False
        assert status["check_interval_sec"] == 42.0
        assert "reminder" in status["levels"]
        assert "escalation" in status["levels"]
        assert status["levels"]["reminder"]["seconds"] == 180
        assert status["levels"]["escalation"]["seconds"] == 300

    def test_status_shows_escalated_count(self):
        """get_status() shows number of escalated tasks after evaluation."""
        esc = TaskEscalator(_make_db_mock(), check_interval_sec=0.1)
        task = _make_task("T08", age_seconds=200)
        esc._evaluate_task(task, esc._now_iso())

        status = esc.get_status()
        assert status["escalated_count"] == 1
        assert "T08" in status["escalated_tasks"]


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v", "-tb=short"]))
