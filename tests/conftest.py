"""Pytest bootstrap: ensure project root is on sys.path."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("HOTPOT_DAILY_REPORT_SCHEDULER", "0")

# Mock heavy detector imports (numpy/cv2/torch) for tests that don't need real inference
sys.modules.setdefault("edge.common.detector.hotpot_detector", MagicMock())
sys.modules.setdefault("edge.common.detector.real_yolo", MagicMock())
sys.modules.setdefault("edge.front_hall.inference.sources", MagicMock())
