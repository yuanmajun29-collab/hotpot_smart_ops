"""T1 tests: vision_worker live mode + auto cleaning-task spawn (MVP).

Strategy: Standalone test file with explicit sys.path setup before ALL imports.
Tests are organized into groups matching the T1 deliverables.
"""

# ---- Step 0: Path setup (MUST be before any project imports) ----
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

# Pre-mock heavy detector modules (have numpy/cv2/torch deps)
from unittest.mock import MagicMock, patch
_mock_detector = MagicMock()
_mock_detector.create_detector = MagicMock(return_value=MagicMock())
_mock_detector.run_on_frame = MagicMock(return_value={"events": [], "table_states": []})
sys.modules["edge.common.detector.hotpot_detector"] = _mock_detector
sys.modules["edge.common.detector.real_yolo"] = MagicMock()
sys.modules["edge.front_hall.inference.sources"] = MagicMock()

# ---- Critical: pre-import common modules before edge tree ----
# (edge.front_hall.inference.* import chain has side effects on sys.path)
import common.hub_client  # noqa: E402
import common.store_config  # noqa: E402
from common.hub_client import EdgeHubClient  # noqa: E402

# ---- Now safe to import project modules ----
from edge.front_hall.inference.vision_worker import (  # noqa: E402
    _spawn_cleaning_tasks,
    process_camera,
    apply_jiaojiang_profile,
    run_store_vision,
)


# ---- Fixtures -----------------------------------------------------------

def _make_hub_mock():
    hub = MagicMock(spec=EdgeHubClient)
    hub.try_post.return_value = True
    hub.post_events.return_value = True
    hub.post_tables.return_value = True
    hub.pending_count.return_value = 0
    return hub


def _make_table_states(*states):
    return [
        {"table_id": tid, "state": st, "confidence": 0.85}
        for tid, st in states
    ]


def _make_camera(zone="front", cam_id="cam01"):
    return {"id": cam_id, "zone": zone, "fps": 0.5}


# ======================================================================
# Group 1: _spawn_cleaning_tasks() core logic (8 tests)
# ======================================================================

class TestSpawnCleaningTasks:

    def test_need_clean_creates_task(self):
        """need_clean table triggers one task POST to /v1/tasks/ingest."""
        hub = _make_hub_mock()
        states = _make_table_states(("T01", "dining"), ("T08", "need_clean"))
        count = _spawn_cleaning_tasks(hub, "store_jiaojiang", states)
        assert count == 1
        hub.try_post.assert_called_once()
        payload = hub.try_post.call_args[0][1]
        assert payload["event"]["event_type"] == "table_need_clean"
        assert payload["event"]["table_id"] == "T08"
        assert payload["event"]["message"] == "T08 待清台（视觉自动检测）"

    def test_needs_cleaning_alias(self):
        """'needs_cleaning' alias also triggers task creation."""
        hub = _make_hub_mock()
        states = _make_table_states(("T05", "needs_cleaning"))
        count = _spawn_cleaning_tasks(hub, "store_jiaojiang", states)
        assert count == 1

    def test_dining_does_not_create_task(self):
        """dining/empty/checkout tables do NOT trigger tasks."""
        hub = _make_hub_mock()
        states = _make_table_states(
            ("T01", "empty"), ("T02", "dining"), ("T05", "checkout")
        )
        count = _spawn_cleaning_tasks(hub, "store_jiaojiang", states)
        assert count == 0
        hub.try_post.assert_not_called()

    def test_multiple_need_clean(self):
        """Multiple need_clean tables each create a separate task."""
        hub = _make_hub_mock()
        hub.try_post.return_value = True
        states = _make_table_states(
            ("T03", "need_clean"), ("T07", "need_clean"), ("T08", "dining")
        )
        count = _spawn_cleaning_tasks(hub, "store_jiaojiang", states)
        assert count == 2
        assert hub.try_post.call_count == 2

    def test_hub_offline_fails_gracefully(self):
        """Hub offline (try_post=False) returns 0, does not raise."""
        hub = _make_hub_mock()
        hub.try_post.return_value = False
        states = _make_table_states(("T04", "need_clean"))
        count = _spawn_cleaning_tasks(hub, "store_jiaojiang", states)
        assert count == 0

    def test_event_metadata_includes_confidence(self):
        """Auto-generated event carries confidence score from inference."""
        hub = _make_hub_mock()
        states = [{"table_id": "T06", "state": "need_clean", "confidence": 0.92}]
        _spawn_cleaning_tasks(hub, "store_jiaojiang", states)
        payload = hub.try_post.call_args[0][1]
        meta = payload["event"]["metadata"]
        assert meta["confidence"] == 0.92
        assert meta["auto_detected"] is True
        assert meta["store_id"] == "store_jiaojiang"

    def test_event_has_vision_source_tag(self):
        """Event source field is 'vision' for auto-detected tasks."""
        hub = _make_hub_mock()
        states = _make_table_states(("T08", "need_clean"))
        _spawn_cleaning_tasks(hub, "store_test", states)
        payload = hub.try_post.call_args[0][1]
        assert payload["event"]["source"] == "vision"

    def test_empty_table_states_no_crash(self):
        """Empty table_states list doesn't crash or error."""
        hub = _make_hub_mock()
        count = _spawn_cleaning_tasks(hub, "store_jiaojiang", [])
        assert count == 0


# ======================================================================
# Group 2: process_camera() live_mode behavior (4 tests)
# ======================================================================

class TestProcessCameraLiveMode:

    @patch("edge.front_hall.inference.vision_worker.run_on_frame")
    @patch("edge.front_hall.inference.vision_worker.create_source")
    @patch("edge.front_hall.inference.vision_worker.table_regions_for_frame", return_value=[])
    def test_live_mode_skips_mock_profile(self, mock_regions, mock_src, mock_run):
        """live_mode=True → apply_jiaojiang_profile() NOT called."""
        hub = _make_hub_mock()
        import numpy as np
        mock_src.return_value.read.return_value = (np.zeros((1080, 1920, 3), dtype=np.uint8), {})
        mock_run.return_value = {
            "events": [],
            "table_states": [{"table_id": "T01", "state": "empty"}],
        }
        with patch("edge.front_hall.inference.vision_worker.apply_jiaojiang_profile") as mp:
            process_camera("store_jiaojiang", _make_camera(), "mock", hub,
                           Path("/tmp/uat"), None, live_mode=True)
            mp.assert_not_called()

    @patch("edge.front_hall.inference.vision_worker.run_on_frame")
    @patch("edge.front_hall.inference.vision_worker.create_source")
    @patch("edge.front_hall.inference.vision_worker.table_regions_for_frame", return_value=[])
    def test_mock_mode_applies_profile(self, mock_regions, mock_src, mock_run):
        """live_mode=False → apply_jiaojiang_profile() IS called."""
        hub = _make_hub_mock()
        import numpy as np
        mock_src.return_value.read.return_value = (np.zeros((1080, 1920, 3), dtype=np.uint8), {})
        mock_run.return_value = {
            "events": [],
            "table_states": [{"table_id": "T01", "state": "empty"}],
        }
        with patch("edge.front_hall.inference.vision_worker.apply_jiaojiang_profile",
                   return_value={"events": [], "table_states": []}) as mp:
            process_camera("store_jiaojiang", _make_camera(), "mock", hub,
                           Path("/tmp/uat"), None, live_mode=False)
            mp.assert_called_once()

    @patch("edge.front_hall.inference.vision_worker.run_on_frame")
    @patch("edge.front_hall.inference.vision_worker.create_source")
    @patch("edge.front_hall.inference.vision_worker.table_regions_for_frame", return_value=[])
    @patch("edge.front_hall.inference.vision_worker._spawn_cleaning_tasks", return_value=1)
    def test_live_mode_spawns_cleaning_tasks(self, mock_spawn, mock_regions, mock_src, mock_run):
        """live_mode=True + need_clean in result → _spawn_cleaning_tasks called."""
        hub = _make_hub_mock()
        import numpy as np
        mock_src.return_value.read.return_value = (np.zeros((1080, 1920, 3), dtype=np.uint8), {})
        mock_run.return_value = {
            "events": [],
            "table_states": [{"table_id": "T08", "state": "need_clean"}],
        }
        result = process_camera("store_jiaojiang", _make_camera(), "mock", hub,
                                Path("/tmp/uat"), None, live_mode=True)
        mock_spawn.assert_called_once()
        assert result["auto_tasks_spawned"] == 1

    @patch("edge.front_hall.inference.vision_worker.run_on_frame")
    @patch("edge.front_hall.inference.vision_worker.create_source")
    @patch("edge.front_hall.inference.vision_worker.table_regions_for_frame", return_value=[])
    @patch("edge.front_hall.inference.vision_worker._spawn_cleaning_tasks", return_value=0)
    def test_no_need_clean_no_auto_task(self, mock_spawn, mock_regions, mock_src, mock_run):
        """No need_clean tables → auto_tasks_spawned not set in result."""
        hub = _make_hub_mock()
        import numpy as np
        mock_src.return_value.read.return_value = (np.zeros((1080, 1920, 3), dtype=np.uint8), {})
        mock_run.return_value = {
            "events": [],
            "table_states": [{"table_id": "T02", "state": "dining"}],
        }
        result = process_camera("store_jiaojiang", _make_camera(), "mock", hub,
                                Path("/tmp/uat"), None, live_mode=True)
        mock_spawn.assert_called_once()
        assert result.get("auto_tasks_spawned", 0) == 0


# ======================================================================
# Group 3: run_store_vision output format (3 tests)
# ======================================================================

class TestRunStoreVisionLiveMode:

    @patch("edge.front_hall.inference.vision_worker.load_store_config")
    @patch("edge.front_hall.inference.vision_worker.process_camera")
    def test_live_mode_propagated(self, mock_proc, mock_cfg):
        """run_store_vision passes live_mode=True to process_camera."""
        mock_cfg.return_value = {"cameras": [_make_camera()], "edge_api_key": ""}
        mock_proc.return_value = {"events": [], "table_states": []}
        run_store_vision("store_jiaojiang", "http://localhost:8088", "mock",
                         Path("/tmp/uat"), None, cycle=1, live_mode=True)
        args, kwargs = mock_proc.call_args
        assert kwargs.get("live_mode") is True

    @patch("edge.front_hall.inference.vision_worker.load_store_config")
    @patch("edge.front_hall.inference.vision_worker.process_camera")
    def test_output_includes_auto_tasks(self, mock_proc, mock_cfg):
        """Summary output includes auto_tasks_spawned count per camera."""
        mock_cfg.return_value = {"cameras": [_make_camera()], "edge_api_key": ""}
        mock_proc.return_value = {
            "events": [], "table_states": [], "auto_tasks_spawned": 2
        }
        summary = run_store_vision("store_jiaojiang", "http://localhost:8088",
                                    "mock", Path("/tmp/uat"), None, live_mode=True)
        assert summary["mode"] == "live"
        assert summary["cameras"][0]["auto_tasks"] == 2

    @patch("edge.front_hall.inference.vision_worker.load_store_config")
    @patch("edge.front_hall.inference.vision_worker.process_camera")
    def test_mock_mode_output_tag(self, mock_proc, mock_cfg):
        """Mock mode shows 'mode': 'mock' in summary."""
        mock_cfg.return_value = {"cameras": [_make_camera()], "edge_api_key": ""}
        mock_proc.return_value = {"events": [], "table_states": []}
        summary = run_store_vision("store_jiaojiang", "http://localhost:8088",
                                    "mock", Path("/tmp/uat"), None, live_mode=False)
        assert summary["mode"] == "mock"


# ======================================================================
# Group 4: CLI --live flag (2 tests)
# ======================================================================

class TestCLIArgs:

    @patch("edge.front_hall.inference.vision_worker.run_store_vision")
    def test_live_flag_default_false(self, mock_run):
        """Without --live, live_mode defaults to False."""
        mock_run.return_value = {}
        with patch("sys.argv", ["vision_worker.py", "--cycles", "0"]):
            try:
                from edge.front_hall.inference.vision_worker import main
                main()
            except SystemExit:
                pass
        args, kwargs = mock_run.call_args
        assert kwargs.get("live_mode") is False

    @patch("edge.front_hall.inference.vision_worker.run_store_vision")
    def test_live_flag_enabled(self, mock_run):
        """With --live, live_mode=True."""
        mock_run.return_value = {}
        with patch("sys.argv", ["vision_worker.py", "--live", "--cycles", "0"]):
            try:
                from edge.front_hall.inference.vision_worker import main
                main()
            except SystemExit:
                pass
        args, kwargs = mock_run.call_args
        assert kwargs.get("live_mode") is True


# ======================================================================
# Group 5: apply_jiaojiang_profile legacy behavior (3 tests)
# ======================================================================

class TestApplyJiaojiangProfile:

    def test_overrides_jiaojiang_tables(self):
        """Jiaojiang store tables get overridden with hardcoded profile."""
        result = {
            "table_states": [
                {"table_id": "T01", "state": "empty"},
                {"table_id": "T08", "state": "dining"},
            ]
        }
        out = apply_jiaojiang_profile(result, "store_jiaojiang")
        states = {t["table_id"]: t["state"] for t in out["table_states"]}
        assert states["T01"] == "empty"
        assert states["T08"] == "need_clean"  # profile override

    def test_non_jiaojiang_unchanged(self):
        """Non-jiaojiang stores pass through unchanged."""
        original = {"table_states": [{"table_id": "T01", "state": "dining"}]}
        out = apply_jiaojiang_profile(original.copy(), "store_yuhuan")
        assert out["table_states"][0]["state"] == "dining"

    def test_no_table_states_unchanged(self):
        """Missing table_states key doesn't crash."""
        result = {"events": []}
        out = apply_jiaojiang_profile(result, "store_jiaojiang")
        assert "table_states" not in out


# ======================================================================
# Group 6: Idempotency / dedup (1 test)
# ======================================================================

class TestIdempotency:

    def test_same_table_stable_event_format(self):
        """Same table_id generates events with consistent structure for Hub dedup."""
        hub = _make_hub_mock()
        states = _make_table_states(("T08", "need_clean"))

        _spawn_cleaning_tasks(hub, "store_jiaojiang", states)
        first_call = hub.try_post.call_args[0][1]

        hub.reset_mock()
        hub.try_post.return_value = True
        _spawn_cleaning_tasks(hub, "store_jiaojiang", states)
        second_call = hub.try_post.call_args[0][1]

        # Both reference same table → Hub source_id dedup prevents duplicates
        assert first_call["event"]["table_id"] == second_call["event"]["table_id"]
        assert first_call["event"]["event_type"] == second_call["event"]["event_type"]


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v", "-tb=short"]))
