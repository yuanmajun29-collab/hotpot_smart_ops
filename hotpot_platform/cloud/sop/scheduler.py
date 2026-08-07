#!/usr/bin/env python3
"""SOP shift scheduler — periodic compliance evaluation (DEV-307).

已从老版 SOPComplianceEngine 迁移到 sop_engine.checker.SOPChecker。
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from hotpot_platform.cloud.sop_engine.checker import SOPChecker
from common.hub_client import EdgeHubClient
from common.schemas import utc_now_iso

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
    """运行一次 SOP 合规性评估，使用新版 SOPChecker 逐信号检测。"""
    checker = SOPChecker()
    signals = load_signals(signals_file)

    all_events: list[dict] = []
    total_checks = 0
    passed_checks = 0

    # 逐信号检查
    signal_items = (signals if isinstance(signals, list)
                    else signals.get("items", signals.get("signals", signals.get("events", [])))
                    if isinstance(signals, dict) else [])
    if isinstance(signal_items, dict):
        signal_items = list(signal_items.values())

    for sig in signal_items:
        if not isinstance(sig, dict):
            sig = {"signal": sig}
        sig.setdefault("store_id", store_id)
        sig.setdefault("shift", shift)

        try:
            check_result = checker.check_compliance(store_id, sig)
        except Exception as exc:
            print(f"[sop_scheduler] check_compliance error: {exc}", file=sys.stderr)
            continue

        total_checks += 1
        violations = check_result.get("violations", [])
        if not violations:
            passed_checks += 1

        # 将违规项转为 Hub 事件
        for v in violations:
            all_events.append({
                "event_type": "sop_violation",
                "source": "sop",
                "level": v.get("severity", "warn"),
                "store_id": store_id,
                "message": v.get("description", str(v)),
                "timestamp": utc_now_iso(),
                "zone": "back_kitchen",
                "metadata": {
                    "rule_id": v.get("rule_id", ""),
                    "category": v.get("category", ""),
                    "shift": shift,
                    "evidence": v.get("evidence", {}),
                },
            })

    compliance_rate = round((passed_checks / total_checks * 100) if total_checks else 100, 1)

    result = {
        "store_id": store_id,
        "shift": shift,
        "compliance_rate": compliance_rate,
        "passed": passed_checks,
        "total": total_checks,
        "events": all_events,
        "checked_at": utc_now_iso(),
    }

    hub = EdgeHubClient(hub_url, store_id)
    for ev in all_events:
        hub.post_event(ev)
    hub.post("/sop", result)
    hub.flush_queue()
    return result


def main() -> None:
    try:
        from common.env import get_store_id, get_hub_url
        _d_store = get_store_id()
        _d_hub = get_hub_url()
    except ImportError:
        _d_store = os.environ.get("HOTPOT_STORE_ID", "store_yuhuan")
        _d_hub = os.environ.get("HOTPOT_HUB_URL", "http://127.0.0.1:8098")

    parser = argparse.ArgumentParser(description="SOP periodic scheduler")
    parser.add_argument("--store-id", default=_d_store)
    parser.add_argument("--hub-url", default=_d_hub)
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
