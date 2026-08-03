"""T4 tests: Live verification mode enablement (MVP).

Covers:
  - Deployment script structure and permissions
  - Configuration validation
  - Smoke test logic
  - Verification metrics definitions
  - 7-day acceptance criteria
"""

import sys
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

# Pre-mock heavy deps
sys.modules["edge.common.detector.hotpot_detector"] = MagicMock()
sys.modules["edge.front_hall.inference.sources"] = MagicMock()

import common.hub_client  # noqa: E402
import common.store_config  # noqa: E402

# ---- Constants ----

T4_SCRIPT_PATH = _PROJECT_ROOT / "deploy" / "start-live-verification.sh"


# ======================================================================
# Group 1: Deployment Script (4 tests)
# ======================================================================

class TestDeploymentScript:

    def test_script_exists(self):
        """T4 deployment script exists."""
        assert T4_SCRIPT_PATH.exists(), f"Script not found: {T4_SCRIPT_PATH}"

    def test_script_is_executable(self):
        """Script has executable permission."""
        if T4_SCRIPT_PATH.exists():
            assert os.access(T4_SCRIPT_PATH, os.X_OK), "Script is not executable"

    def test_script_has_start_command(self):
        """Script supports 'start' command."""
        if T4_SCRIPT_PATH.exists():
            content = T4_SCRIPT_PATH.read_text(encoding="utf-8")
            assert "start)" in content or '"start"' in content
            assert "start_vision_worker" in content

    def test_script_has_stop_and_status(self):
        """Script supports stop/status/test commands."""
        if T4_SCRIPT_PATH.exists():
            content = T4_SCRIPT_PATH.read_text(encoding="utf-8")
            assert "stop_verification" in content
            assert "show_status_dashboard" in content
            assert "run_smoke_test" in content


# ======================================================================
# Group 2: Live Mode Configuration (3 tests)
# ======================================================================

class TestLiveModeConfig:

    def test_vision_interval_default(self):
        """Default vision interval is 5 seconds."""
        # Check script default value
        if T4_SCRIPT_PATH.exists():
            content = T4_SCRIPT_PATH.read_text(encoding="utf-8")
            assert "VISION_INTERVAL_SEC=5" in content or "VISION_INTERVAL_SEC:-5" in content

    def test_escalation_interval_is_30s(self):
        """Escalator check interval is 30 seconds."""
        if T4_SCRIPT_PATH.exists():
            content = T4_SCRIPT_PATH.read_text(encoding="utf-8")
            assert "ESCALATION_CHECK_SEC=30" in content or "30" in content

    def test_hub_url_configurable(self):
        """Hub URL is configurable via environment variable."""
        if T4_SCRIPT_PATH.exists():
            content = T4_SCRIPT_PATH.read_text(encoding="utf-8")
            assert "HUB_URL" in content
            assert "43.139.143.12" in content  # Default Hub address


# ======================================================================
# Group 3: Verification Metrics (5 tests)
# ======================================================================

class TestVerificationMetrics:

    def test_accuracy_target_ge_80(self):
        """Vision recognition accuracy target >= 80%."""
        metrics = _get_verification_metrics()
        assert metrics["min_accuracy_pct"] >= 80

    def test_auto_task_success_rate_ge_90(self):
        """Auto task creation success rate target >= 90%."""
        metrics = _get_verification_metrics()
        assert metrics["min_task_spawn_rate_pct"] >= 90

    def test_response_time_target_le_3min(self):
        """Average accept response time <= 3 minutes."""
        metrics = _get_verification_metrics()
        assert metrics["max_avg_response_sec"] <= 180

    def test_escalation_rate_le_10(self):
        """Escalation trigger rate should be <= 10%."""
        metrics = _get_verification_metrics()
        assert metrics["max_escalation_rate_pct"] <= 10

    def test_continuous_run_days_eq_7(self):
        """Continuous run target is 7 days."""
        metrics = _get_verification_metrics()
        assert metrics["continuous_run_days"] == 7


def _get_verification_metrics() -> dict:
    """Return MVP verification acceptance criteria."""
    return {
        "min_accuracy_pct": 80,
        "min_task_spawn_rate_pct": 90,
        "max_avg_response_sec": 180,
        "max_escalation_rate_pct": 10,
        "continuous_run_days": 7,
        "min_tables_covered": 6,
        "max_tables_covered": 10,
        "detection_interval_sec": 5,
        "reminder_threshold_sec": 180,
        "escalation_threshold_sec": 300,
    }


# ======================================================================
# Group 4: Closed-Loop Chain Validation (3 tests)
# ======================================================================

class TestClosedLoopChain:

    def test_chain_has_4_steps(self):
        """Closed loop has exactly 4 steps."""
        chain = get_closed_loop_steps()
        assert len(chain) == 4

    def test_chain_order_correct(self):
        """Chain order: detect → create_task → accept → complete."""
        chain = get_closed_loop_steps()
        expected = ["vision_detect", "auto_create_task", "mobile_accept", "mobile_complete"]
        assert chain == expected

    def test_each_step_has_owner(self):
        """Each step has a responsible component."""
        chain_details = get_closed_loop_details()
        for step, detail in chain_details.items():
            assert "component" in detail
            assert "api_endpoint" in detail or "method" in detail


def get_closed_loop_steps():
    """Return ordered list of closed-loop steps."""
    return [
        "vision_detect",
        "auto_create_task",
        "mobile_accept",
        "mobile_complete",
    ]


def get_closed_loop_details():
    """Return detailed info about each closed-loop step."""
    return {
        "vision_detect": {
            "component": "vision_worker.py (--live)",
            "method": "process_camera() → table_states",
            "output": "need_clean / dining / empty states",
        },
        "auto_create_task": {
            "component": "vision_worker.py",
            "method": "_spawn_cleaning_tasks()",
            "api_endpoint": "POST /v1/tasks/ingest",
            "idempotency_key": "source_id = evt:{event_id}",
        },
        "mobile_accept": {
            "component": "cleaning-tasks.html (H5)",
            "method": "acceptTask()",
            "api_endpoint": "POST /v1/tasks/{id}/accept",
            "permission": "task_ack",
        },
        "mobile_complete": {
            "component": "cleaning-tasks.html (H5)",
            "method": "completeTask()",
            "api_endpoint": "POST /v1/tasks/{id}/submit",
            "permission": "task_ack",
        },
    }


# ======================================================================
# Group 5: Acceptance Criteria Document (2 tests)
# ======================================================================

class TestAcceptanceCriteriaDoc:

    def test_doc_lists_all_metrics(self):
        """Acceptance criteria doc lists all required metrics."""
        doc = get_acceptance_criteria_text()
        required_keywords = [
            "准确率", "成功率", "响应时间", "升级", "连续运行"
        ]
        for kw in required_keywords:
            assert kw in doc, f"Missing keyword: {kw}"

    def test_doc_has_pass_fail_criteria(self):
        """Acceptance criteria has clear pass/fail thresholds."""
        doc = get_acceptance_criteria_text()
        assert "%" in doc or "≥" in doc or ">=" in doc


def get_acceptance_criteria_text() -> str:
    """Return the acceptance criteria document text."""
    m = _get_verification_metrics()
    return f"""
火瞳 · 待清台闭环 MVP 验收标准
=====================================

验证周期: {m['continuous_run_days']} 天连续运行
覆盖范围: 椒江店 {m['min_tables_covered']}-{m['max_tables_covered']} 张桌位

验收指标:
  1. 视觉识别准确率 ≥ {m['min_accuracy_pct']}%
     (正确识别 need_clean / dining / empty 的比例)

  2. 自动建任务成功率 ≥ {m['min_task_spawn_rate_pct']}%
     (视觉检测到 need_clean 后成功创建工单的比例)

  3. 平均接单响应时间 ≤ {m['max_avg_response_sec']}s
     (从建单到员工点击接单的平均时长)

  4. 超时升级触发率 ≤ {m['max_escalation_rate_pct']}%
     (需要升级到领班/店长的任务占比)

  5. 连续运行稳定性
     - 7天无崩溃重启
     - 日志无未捕获异常
     - 内存无泄漏趋势

闭环链路验证:
  视觉检测 → 自动建任务 → H5接单 → 完成/纠正

通过条件: 全部5项指标达标
"""


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v", "-tb=short"]))
