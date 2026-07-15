"""Defect ROI measurement helpers for kitchen edge inference."""

from __future__ import annotations

from math import sqrt
from typing import Mapping

import cv2
import numpy as np


DEFAULT_THRESHOLDS = {
    "warn_manual": 2.0,
    "auto_reject": 5.0,
}


def pixels_to_mm(px: float, calib: float) -> float:
    """Convert a pixel length to millimeters using mm-per-pixel calibration."""
    if calib <= 0:
        raise ValueError("calib must be positive")
    return float(px) * float(calib)


def decide_action(size_mm: float, thresholds: Mapping[str, float] | None = None) -> str:
    """Return log_only, warn_manual, or auto_reject for a measured defect size."""
    values = dict(DEFAULT_THRESHOLDS)
    if thresholds:
        values.update(thresholds)

    warn_mm = float(values.get("warn_manual", values.get("warn_mm", 2.0)))
    reject_mm = float(values.get("auto_reject", values.get("reject_mm", 5.0)))
    if reject_mm < warn_mm:
        warn_mm, reject_mm = reject_mm, warn_mm

    if size_mm < warn_mm:
        return "log_only"
    if size_mm < reject_mm:
        return "warn_manual"
    return "auto_reject"


def estimate_bbox_size_mm(bbox: list[int] | tuple[int, int, int, int], calib: float) -> float:
    """Estimate a linear defect size from bbox area when contour measurement fails."""
    x1, y1, x2, y2 = bbox
    width = max(0, int(x2) - int(x1))
    height = max(0, int(y2) - int(y1))
    return pixels_to_mm(sqrt(width * height), calib)


def measure_defect(roi: np.ndarray) -> dict | None:
    """Measure the dominant defect contour inside an ROI.

    The pipeline uses adaptive thresholding for uneven kitchen lighting, then
    closes small holes before selecting the largest external contour.
    """
    if roi is None or roi.size == 0:
        return None

    if roi.ndim == 2:
        gray = roi
    elif roi.ndim == 3 and roi.shape[2] == 4:
        gray = cv2.cvtColor(roi, cv2.COLOR_BGRA2GRAY)
    elif roi.ndim == 3:
        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
    else:
        return None

    height, width = gray.shape[:2]
    if height < 3 or width < 3:
        return None

    block_size = min(11, height, width)
    if block_size % 2 == 0:
        block_size -= 1
    block_size = max(3, block_size)

    binary = cv2.adaptiveThreshold(
        gray,
        255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY_INV,
        block_size,
        2,
    )

    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    closed = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel)

    contours, _ = cv2.findContours(closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    contours = [cnt for cnt in contours if cv2.contourArea(cnt) >= 4.0]
    if not contours:
        return None

    contour = max(contours, key=cv2.contourArea)
    area_px = float(cv2.contourArea(contour))
    rect = cv2.minAreaRect(contour)
    diameter_px = float(max(rect[1]))
    x, y, w, h = cv2.boundingRect(contour)

    if area_px <= 0 or diameter_px <= 0:
        return None

    return {
        "area_px": area_px,
        "diameter_px": diameter_px,
        "bbox_px": [int(x), int(y), int(x + w), int(y + h)],
        "contour": contour,
    }
