"""Pytest bootstrap: ensure project root is on sys.path."""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("HOTPOT_DAILY_REPORT_SCHEDULER", "0")
