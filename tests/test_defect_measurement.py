import numpy as np
import cv2
import pytest

from edge.kitchen.inference.defect_measurement import (
    decide_action,
    estimate_bbox_size_mm,
    measure_defect,
    pixels_to_mm,
)
from deploy.jetson.jetson_server import _is_suspicious


def test_pixels_to_mm_conversion():
    assert pixels_to_mm(40, 0.05) == 2.0
    assert estimate_bbox_size_mm([0, 0, 30, 40], 0.1) == pytest.approx(3.4641016151377544)


def test_measure_defect_known_rectangle():
    roi = np.full((80, 80, 3), 255, dtype=np.uint8)
    cv2.rectangle(roi, (20, 30), (50, 45), (0, 0, 0), -1)

    measurement = measure_defect(roi)

    assert measurement is not None
    assert 25 <= measurement["diameter_px"] <= 35
    assert measurement["area_px"] > 300
    assert pixels_to_mm(measurement["diameter_px"], 0.1) >= 2.5


def test_measure_defect_empty_and_tiny_noise_roi():
    assert measure_defect(np.empty((0, 0, 3), dtype=np.uint8)) is None

    roi = np.full((40, 40, 3), 255, dtype=np.uint8)
    roi[5, 5] = 0
    roi[20, 30] = 0

    assert measure_defect(roi) is None


def test_measure_defect_multi_contour_uses_largest():
    roi = np.full((100, 100, 3), 255, dtype=np.uint8)
    cv2.rectangle(roi, (8, 8), (15, 15), (0, 0, 0), -1)
    cv2.rectangle(roi, (50, 55), (85, 75), (0, 0, 0), -1)

    measurement = measure_defect(roi)

    assert measurement is not None
    assert measurement["diameter_px"] >= 30
    assert measurement["bbox_px"][0] >= 45


def test_decide_action_thresholds():
    thresholds = {"warn_manual": 2.0, "auto_reject": 5.0}
    assert decide_action(1.9, thresholds) == "log_only"
    assert decide_action(2.0, thresholds) == "warn_manual"
    assert decide_action(5.0, thresholds) == "auto_reject"


def test_is_suspicious_adds_defect_fields_with_env_thresholds(monkeypatch):
    monkeypatch.setenv("DEFECT_CALIB_MM_PER_PX", "0.5")
    monkeypatch.setenv("DEFECT_THRESHOLD_MM", "2,5")

    detections = [{"cls": 45, "conf": 0.9, "bbox": [0, 0, 6, 6], "label": "bowl"}]
    suspicious, reason = _is_suspicious(detections, image=None)

    assert suspicious is False
    assert reason.startswith("normal:")
    assert detections[0]["defect_size_mm"] == 3.0
    assert detections[0]["action"] == "warn_manual"
    assert detections[0]["measurement_source"] == "bbox_area_estimate"
