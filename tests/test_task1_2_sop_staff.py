"""Tests for task 1-2: SOP视觉合规 + 员工行为接入Edge Agent."""

import sys
from pathlib import Path

# Ensure project root is on path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def test_stage_sop_import():
    """验证 stage_sop 模块可导入且 STAGE_NAME/run 可用。"""
    from edge.kitchen.inference.stages.stage_sop import STAGE_NAME, run
    assert STAGE_NAME == "sop"
    assert callable(run)


def test_stage_sop_ppe_functions_exist():
    """验证 PPE 检测辅助函数存在。"""
    from edge.kitchen.inference.stages.stage_sop import (
        _check_ppe_hat,
        _check_ppe_apron,
        _check_ppe_mask,
        _check_ppe_gloves,
        _extract_person_roi,
    )
    import numpy as np

    # 创建一个人形测试图片
    dummy_frame = np.ones((200, 100, 3), dtype=np.uint8) * 128
    # 头顶白色（模拟帽子）
    dummy_frame[:30, :, :] = 255

    roi = _extract_person_roi(dummy_frame, [0, 0, 100, 200])
    assert roi is not None

    assert isinstance(_check_ppe_hat(dummy_frame), (bool, np.bool_))
    assert isinstance(_check_ppe_apron(dummy_frame), (bool, np.bool_))
    assert isinstance(_check_ppe_mask(dummy_frame), (bool, np.bool_))
    assert isinstance(_check_ppe_gloves(dummy_frame), (bool, np.bool_))


def test_sop_infer_module_import():
    """验证 sop_infer 模块可导入且有 router。"""
    from edge.agent.modules.sop_infer import router, STATION_IDS, STATION_NAMES
    assert router is not None
    assert len(STATION_IDS) == 7
    assert "sop_broth" in STATION_IDS
    assert STATION_NAMES["sop_broth"] == "汤底"


def test_staff_behavior_infer_module_import():
    """验证 staff_behavior_infer 模块可导入且有 router。"""
    from edge.agent.modules.staff_behavior_infer import router, _active
    assert router is not None
    # _active 默认应为 False
    assert _active is False


def test_staff_behavior_detector_import():
    """验证 StaffBehaviorDetector 可导入。"""
    from edge.staff_behavior.detector import StaffBehaviorDetector, DetectionResult
    detector = StaffBehaviorDetector()
    assert detector is not None
    assert detector.conf_threshold == 0.35


def test_sop_compliance_vision_mode_function():
    """验证 sop_compliance 的 vision 模式函数存在。"""
    from edge.receiving.sop_compliance import (
        _load_frames_from_dir,
        _vision_readings,
        one_scan_vision,
    )
    assert callable(_load_frames_from_dir)
    assert callable(_vision_readings)
    assert callable(one_scan_vision)


def test_sop_compliance_load_frames():
    """验证帧加载函数对不存在目录返回空。"""
    from edge.receiving.sop_compliance import _load_frames_from_dir
    result = _load_frames_from_dir("/nonexistent/path")
    assert result == {}, "不存在的目录应返回空字典"


def test_sop_compliance_stations():
    """验证 7 工位状态机定义。"""
    from edge.receiving.sop_compliance import STATIONS, STATION_MAP, Station, StationStatus
    assert len(STATIONS) == 7
    for s in STATIONS:
        assert s.status == StationStatus.RUNNING
        assert s.station_id in STATION_MAP


def test_module_registry_has_new_modules():
    """验证 server.py 注册了新模块。"""
    # 直接读取 server.py 源码检查注册表
    server_path = PROJECT_ROOT / "edge" / "agent" / "server.py"
    content = server_path.read_text()
    assert '"sop": sop_infer' in content
    assert '"staff_behavior": staff_behavior_infer' in content
