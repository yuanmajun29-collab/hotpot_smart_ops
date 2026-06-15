#!/usr/bin/env python3
"""SOP shift scheduler — periodic compliance evaluation (DEV-307)."""

from __future__ import annotations

import argparse
import json
import signal
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from cloud.sop.sop_engine import SOPComplianceEngine
from shared.hub_client import EdgeHubClient

# Local hour → shift name (hotpot store shifts)
SHIFT_SCHEDULE = [
    (6, 11, "morning"),
    (11, 16, "noon"),
    (16, 22, "evening"),
]

_stop = False


def _handle_stop(signum: int, frame: object) -> None:
    global _stop
    _stop = True
    print(f"[sop_scheduler] stopping (signal {signum})...", file=sys.stderr)


def current_shift(hour: Optional[int] = None) -> str:
    hour = hour if hour is not None else datetime.now().hour
    for start, end, name in SHIFT_SCHEDULE:
        if start <= hour < end:
            return name
    return "evening"


def load_signals(path: Path) -> Dict[str, Any]:
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {}


def run_evaluation(
    store_id: str,
    hub_url: str,
    shift: str,
    signals_file: Path,
) -> Dict[str, Any]:
    engine = SOPComplianceEngine()
    signals = load_signals(signals_file)
    result = engine.evaluate_shift(store_id, shift, signals)

    hub = EdgeHubClient(hub_url, store_id)
    for ev in result.get("events", []):
        hub.post_event(ev)
    hub.post("/sop", result)
    hub.flush_queue()
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="SOP periodic scheduler")
    parser.add_argument("--store-id", default="store_yuhuan")
    parser.add_argument("--hub-url", default="http://127.0.0.1:8088")
    parser.add_argument(
        "--signals-file",
        default="",
        help="Per-store sop_signals JSON (default demo/data/stores/<id>/sop_signals_noon.json)",
    )
    parser.add_argument("--interval", type=int, default=3600, help="Seconds between runs")
    parser.add_argument("--once", action="store_true", help="Run once and exit")
    parser.add_argument("--shift", default="", help="Override shift (morning|noon|evening)")
    args = parser.parse_args()

    signals_file = Path(
        args.signals_file or f"demo/data/stores/{args.store_id}/sop_signals_noon.json"
    )
    if not signals_file.is_absolute():
        signals_file = PROJECT_ROOT / signals_file

    signal.signal(signal.SIGINT, _handle_stop)
    signal.signal(signal.SIGTERM, _handle_stop)

    print(f"[sop_scheduler] store={args.store_id} interval={args.interval}s")

    while not _stop:
        shift = args.shift or current_shift()
        try:
            result = run_evaluation(args.store_id, args.hub_url, shift, signals_file)
            print(
                f"[sop_scheduler] shift={shift} compliance={result.get('compliance_rate')}% "
                f"passed={result.get('passed')}/{result.get('total')}"
            )
        except Exception as exc:
            print(f"[sop_scheduler] ERROR: {exc}", file=sys.stderr)

        if args.once:
            break
        for _ in range(args.interval):
            if _stop:
                break
            time.sleep(1)


if __name__ == "__main__":
    main()
