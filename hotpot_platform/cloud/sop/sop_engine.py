#!/usr/bin/env python3
"""Back-of-kitchen SOP compliance engine."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from common.schemas import EventLevel, EventSource, OpsEvent, utc_now_iso

DEFAULT_SOP_PATH = PROJECT_ROOT / "demo" / "data" / "sop_checklist.json"


class SOPComplianceEngine:
    """Evaluate kitchen SOP checklist against vision/IoT/manual inputs."""

    def __init__(self, sop_config: Optional[Dict[str, Any]] = None) -> None:
        self.config = sop_config or self.load_default()
        self.sops: List[Dict[str, Any]] = self.config.get("sops", [])

    @staticmethod
    def load_default() -> Dict[str, Any]:
        if DEFAULT_SOP_PATH.exists():
            return json.loads(DEFAULT_SOP_PATH.read_text(encoding="utf-8"))
        return {"sops": []}

    def evaluate_shift(
        self,
        store_id: str,
        shift: str,
        signals: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Evaluate all SOPs for a shift. signals: vision/iot/manual evidence."""
        signals = signals or {}
        results: List[Dict[str, Any]] = []
        events: List[Dict[str, Any]] = []

        for sop in self.sops:
            if shift not in sop.get("shifts", ["morning", "noon", "evening"]):
                continue
            item_result = self._evaluate_one(sop, signals)
            results.append(item_result)
            if item_result["status"] == "failed":
                ev = OpsEvent(
                    event_type="sop_violation",
                    source=EventSource.SYSTEM.value,
                    level=EventLevel.WARN.value if sop.get("severity") != "critical" else EventLevel.CRITICAL.value,
                    store_id=store_id,
                    zone="kitchen",
                    message=f"SOP违规: {sop['name']} - {item_result['reason']}",
                    metadata={
                        "sop_id": sop["id"],
                        "sop_name": sop["name"],
                        "category": sop.get("category", ""),
                        "shift": shift,
                        "checkpoints": item_result["checkpoints"],
                    },
                )
                events.append(ev.to_dict())
            elif item_result["status"] == "passed":
                ev = OpsEvent(
                    event_type="sop_completed",
                    source=EventSource.SYSTEM.value,
                    level=EventLevel.INFO.value,
                    store_id=store_id,
                    zone="kitchen",
                    message=f"SOP已完成: {sop['name']}",
                    metadata={"sop_id": sop["id"], "shift": shift},
                )
                events.append(ev.to_dict())

        passed = sum(1 for r in results if r["status"] == "passed")
        failed = sum(1 for r in results if r["status"] == "failed")
        pending = sum(1 for r in results if r["status"] == "pending")
        total = len(results)
        compliance_rate = round(passed / total * 100, 1) if total else 100.0

        return {
            "store_id": store_id,
            "shift": shift,
            "evaluated_at": utc_now_iso(),
            "total": total,
            "passed": passed,
            "failed": failed,
            "pending": pending,
            "compliance_rate": compliance_rate,
            "results": results,
            "events": events,
        }

    def _evaluate_one(self, sop: Dict[str, Any], signals: Dict[str, Any]) -> Dict[str, Any]:
        checkpoints_out = []
        failed_reasons = []
        pending_count = 0

        for cp in sop.get("checkpoints", []):
            cp_id = cp["id"]
            cp_type = cp.get("type", "manual")
            expected = cp.get("expected")
            actual = signals.get(cp_id)
            passed = False
            reason = ""

            if cp_type == "vision":
                passed = bool(signals.get(cp_id, False))
                if not passed:
                    reason = cp.get("fail_message", f"视觉检查未通过: {cp_id}")
            elif cp_type == "iot":
                if actual is None:
                    pending_count += 1
                    reason = "IoT 数据缺失"
                elif "range" in cp:
                    lo, hi = cp["range"]
                    passed = lo <= float(actual) <= hi
                    if not passed:
                        reason = cp.get("fail_message", f"IoT读数 {actual} 超出范围 [{lo}, {hi}]")
                else:
                    passed = bool(actual)
                    if not passed:
                        reason = cp.get("fail_message", f"IoT检查未通过: {cp_id}")
            elif cp_type == "manual":
                passed = signals.get(cp_id) is True
                if not passed and signals.get(cp_id) is False:
                    reason = cp.get("fail_message", "人工确认未通过")
                elif signals.get(cp_id) is None:
                    pending_count += 1
                    reason = "待人工确认"

            checkpoints_out.append(
                {
                    "id": cp_id,
                    "name": cp.get("name", cp_id),
                    "type": cp_type,
                    "passed": passed,
                    "actual": actual,
                    "expected": expected,
                }
            )
            if reason and not passed:
                failed_reasons.append(reason)

        if pending_count == len(sop.get("checkpoints", [])):
            status = "pending"
        elif failed_reasons:
            status = "failed"
        else:
            status = "passed"

        return {
            "sop_id": sop["id"],
            "sop_name": sop["name"],
            "category": sop.get("category", ""),
            "status": status,
            "reason": "; ".join(failed_reasons) if failed_reasons else "",
            "checkpoints": checkpoints_out,
        }

    def get_sop_catalog(self) -> List[Dict[str, Any]]:
        return [
            {
                "id": s["id"],
                "name": s["name"],
                "category": s.get("category", ""),
                "frequency": s.get("frequency", ""),
                "shifts": s.get("shifts", []),
            }
            for s in self.sops
        ]


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Kitchen SOP compliance evaluator")
    parser.add_argument("--store-id", default="store_yuhuan")
    parser.add_argument("--shift", choices=("morning", "noon", "evening"), default="noon")
    parser.add_argument("--signals-file", default="", help="JSON file with checkpoint signals")
    parser.add_argument("--hub-url", default="", help="POST events to event hub")
    args = parser.parse_args()

    signals: Dict[str, Any] = {}
    if args.signals_file:
        signals = json.loads(Path(args.signals_file).read_text(encoding="utf-8"))

    engine = SOPComplianceEngine()
    result = engine.evaluate_shift(args.store_id, args.shift, signals)
    print(json.dumps(result, ensure_ascii=False, indent=2))

    if args.hub_url:
        import urllib.request

        hub = args.hub_url.rstrip("/")
        for ev in result["events"]:
            req = urllib.request.Request(
                f"{hub}/events",
                data=json.dumps(ev).encode(),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            urllib.request.urlopen(req, timeout=5)
        stats_req = urllib.request.Request(
            f"{hub}/sop",
            data=json.dumps(result).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        urllib.request.urlopen(stats_req, timeout=5)
        print(f"[OK] Posted {len(result['events'])} SOP events to hub", file=sys.stderr)


if __name__ == "__main__":
    main()
