#!/usr/bin/env python3
"""Validate a real POS history export before Sprint 0 uses it."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Dict, List

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from hotpot_platform.cloud.integrations.pos_bridge import load_sku_sales_csv


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _missing_days(first: date, last: date, present: set[date]) -> List[str]:
    missing: List[str] = []
    current = first
    while current <= last:
        if current not in present:
            missing.append(current.isoformat())
        current += timedelta(days=1)
    return missing


def validate(csv_path: Path, store_id: str) -> Dict[str, Any]:
    records = load_sku_sales_csv(csv_path, store_id)
    if not records:
        raise ValueError("POS CSV contains no sales records")
    parsed_dates = [date.fromisoformat(row["business_date"]) for row in records]
    present_dates = set(parsed_dates)
    first, last = min(present_dates), max(present_dates)
    duplicate_keys = [
        {"business_date": key[0], "sku": key[1], "count": count}
        for key, count in Counter((r["business_date"], r["sku"]) for r in records).items()
        if count > 1
    ]
    missing = _missing_days(first, last, present_dates)
    return {
        "evidence_type": "real_pos_source_validation",
        "store_id": store_id,
        "source_file": csv_path.name,
        "source_sha256": _file_sha256(csv_path),
        "row_count": len(records),
        "sku_count": len({r["sku"] for r in records}),
        "business_date_range": {"start": first.isoformat(), "end": last.isoformat()},
        "covered_day_count": len(present_dates),
        "missing_days": missing,
        "duplicate_store_date_sku": duplicate_keys,
        "status": "PASS" if not missing and not duplicate_keys else "FAIL",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate a real POS history CSV")
    parser.add_argument("--csv", required=True, type=Path)
    parser.add_argument("--store-id", required=True)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    report = validate(args.csv, args.store_id)
    output = json.dumps(report, ensure_ascii=False, indent=2)
    print(output)
    if args.report:
        args.report.write_text(output + "\n", encoding="utf-8")
    if report["status"] != "PASS":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
