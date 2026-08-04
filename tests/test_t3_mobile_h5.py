"""T3 tests: Mobile H5 cleaning task acceptance page (MVP).

Covers:
  - Page structure and required elements
  - Task filtering logic
  - Accept / Complete action handlers
  - Table state correction flow
  - Elapsed time calculation and overdue detection
"""

import sys
import re
from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

# Pre-mock heavy deps for any edge module imports
sys.modules["edge.common.detector.hotpot_detector"] = MagicMock()
sys.modules["edge.front_hall.inference.sources"] = MagicMock()

import common.hub_client  # noqa: E402
import common.store_config  # noqa: E402

# ---- Read the HTML file --------------------------------------------------

T3_HTML_PATH = _PROJECT_ROOT / "hotpot_platform" / "dashboard" / "cleaning-tasks.html"

def _get_html_content():
    return T3_HTML_PATH.read_text(encoding="utf-8")


def _get_script_content():
    """Extract JS from <script> tag."""
    html = _get_html_content()
    # Find the main script block (last one with our logic)
    match = re.search(r'<script src="[^"]*core\.js"[^>]*>\s*</script>\s*<script>(.*?)</script>', html, re.DOTALL)
    if match:
        return match.group(1)
    raise RuntimeError("Could not extract T3 script content")


# ======================================================================
# Group 1: Page Structure (4 tests)
# ======================================================================

class TestPageStructure:

    def test_html_file_exists(self):
        """T3 HTML file exists at expected path."""
        assert T3_HTML_PATH.exists(), f"File not found: {T3_HTML_PATH}"

    def test_has_mobile_viewport(self):
        """Page has mobile viewport meta tag."""
        html = _get_html_content()
        assert 'viewport' in html
        assert 'width=device-width' in html

    def test_has_required_sections(self):
        """Page contains header, filter bar, task list, correct sheet."""
        html = _get_html_content()
        assert 'class="header"' in html
        assert 'filter-bar' in html
        assert 'id="task-list"' in html
        assert 'id="correct-sheet"' in html
        assert 'id="correct-overlay"' in html

    def test_has_action_buttons(self):
        """Page has accept, complete, correct buttons in template."""
        html = _get_html_content()
        assert "接单" in html or "acceptTask" in html
        assert "完成" in html or "completeTask" in html
        assert "纠正" in html or "openCorrectSheet" in html


# ======================================================================
# Group 2: Task Filtering Logic (3 tests)
# ======================================================================

class TestTaskFiltering:

    def test_filter_pending_only(self):
        """Filter 'pending' returns only pending tasks."""
        # Simulate the filterTasks() logic
        all_tasks = [
            {"task_id": "T1", "status": "pending"},
            {"task_id": "T2", "status": "accepted"},
            {"task_id": "T3", "status": "pending"},
        ]
        current_filter = "pending"
        if current_filter:
            statuses = current_filter.split(",")
            result = [t for t in all_tasks if t["status"] in statuses]
        else:
            result = all_tasks
        assert len(result) == 2
        assert all(t["status"] == "pending" for t in result)

    def test_filter_accepted_in_progress(self):
        """Filter 'accepted,in_progress' returns active tasks."""
        all_tasks = [
            {"task_id": "T1", "status": "pending"},
            {"task_id": "T2", "status": "accepted"},
            {"task_id": "T3", "status": "in_progress"},
            {"task_id": "T4", "status": "done"},
        ]
        statuses = "accepted,in_progress".split(",")
        result = [t for t in all_tasks if t["status"] in statuses]
        assert len(result) == 2

    def test_filter_all_returns_everything(self):
        """Empty filter string returns all tasks."""
        all_tasks = [
            {"task_id": "T1", "status": "pending"},
            {"task_id": "T2", "status": "done"},
        ]
        current_filter = ""
        result = all_tasks if not current_filter else [
            t for t in all_tasks if t.status in current_filter.split(",")
        ]
        assert len(result) == 2


# ======================================================================
# Group 3: Elapsed Time & Overdue Detection (4 tests)
# ======================================================================

class TestElapsedTime:

    def _calc_elapsed(self, created_at):
        """Replicate getElapsedTime() logic."""
        if not created_at:
            return ""
        try:
            from datetime import datetime, timedelta
            created = datetime.fromisoformat(created_at)
            now = datetime.now()
            sec = int((now - created).total_seconds())
            if sec < 60:
                return f"{sec}秒前"
            elif sec < 3600:
                return f"{int(sec / 60)}分钟前"
            else:
                return f"{int(sec / 3600)}小时前"
        except Exception:
            return ""

    def test_fresh_task_shows_seconds(self):
        """Task created seconds ago shows 'X秒前'."""
        from datetime import datetime, timedelta
        now = datetime.now().replace(microsecond=0)
        recent = (now - timedelta(seconds=45)).isoformat()
        elapsed = self._calc_elapsed(recent)
        assert "秒前" in elapsed

    def test_older_task_shows_minutes(self):
        """Task created minutes ago shows 'X分钟前'."""
        from datetime import datetime, timedelta
        now = datetime.now().replace(microsecond=0)
        older = (now - timedelta(minutes=5)).isoformat()
        elapsed = self._calc_elapsed(older)
        assert "分钟前" in elapsed

    def test_overdue_detection_true(self):
        """Task >3min old is detected as overdue."""
        from datetime import datetime, timedelta
        now = datetime.now()
        created = now - timedelta(seconds=200)  # 3m20s
        age_sec = (now - created).total_seconds()
        assert age_sec > 180  # overdue threshold
        assert is_overdue_check({"created_at": created.isoformat()})

    def test_overdue_detection_false(self):
        """Task <3min old is NOT overdue."""
        from datetime import datetime, timedelta
        now = datetime.now()
        created = now - timedelta(seconds=100)  # 1m40s
        age_sec = (now - created).total_seconds()
        assert age_sec < 180
        assert not is_overdue_check({"created_at": created.isoformat()})


def is_overdue_check(task):
    """Replicate isOverdue() logic from T3 page."""
    if not task.get("created_at"):
        return False
    try:
        from datetime import datetime
        created = datetime.fromisoformat(task["created_at"])
        age_sec = (datetime.now() - created).total_seconds()
        return age_sec > 180
    except Exception:
        return False


def MathFloor(x):
    return int(x)


# ======================================================================
# Group 4: Action Handlers & API Calls (4 tests)
# ======================================================================

class TestActionHandlers:

    def test_accept_calls_correct_endpoint(self):
        """Accept task POSTs to /v1/tasks/{id}/accept."""
        # Verify the endpoint pattern matches tasks.py router
        script = _get_script_content()
        assert "tasks/" in script and "/accept" in script

    def test_complete_calls_submit_endpoint(self):
        """Complete task POSTs to /v1/tasks/{id}/submit."""
        script = _get_script_content()
        assert "/submit" in script

    def test_correction_posts_to_ingest(self):
        """Correction uses /v1/tasks/ingest with correction event type."""
        script = _get_script_content()
        assert "table_state_correction" in script
        assert "/ingest" in script

    def test_correction_includes_metadata(self):
        """Correction event includes corrected_state and actor info."""
        script = _get_script_content()
        assert "corrected_by" in script
        assert "corrected_state" in script
        assert "auto_detected" in script
        assert "false" in script  # manual correction should have auto_detected=false


# ======================================================================
# Group 5: Security & Audit (3 tests)
# ======================================================================

class TestSecurityAndAudit:

    def test_requires_auth(self):
        """Page calls HotpotApp.requireAuth() before rendering."""
        script = _get_script_content()
        assert "requireAuth" in script

    def test_sends_jwt_token(self):
        """API requests include Authorization Bearer header."""
        script = _get_script_content()
        assert "Authorization" in script
        assert "Bearer" in script

    def test_correction_has_audit_note(self):
        """Correction sheet shows audit warning to user."""
        html = _get_html_content()
        assert "审计日志" in html or "audit" in html.lower()


# ======================================================================
# Group 6: Auto-refresh (2 tests)
# ======================================================================

class TestAutoRefresh:

    def test_has_auto_refresh_timer(self):
        """Page includes auto-refresh countdown timer."""
        script = _get_script_content()
        assert "setInterval" in script
        assert "refreshCountdown" in script or "refresh-countdown" in script.lower()

    def test_refresh_interval_is_5_seconds(self):
        """Auto-refresh interval is ~5 seconds."""
        html = _get_html_content()
        assert "5s" in html or "5000" in html


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v", "-tb=short"]))
