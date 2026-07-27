#!/usr/bin/env python3
"""Run a traceable L1 moving-average backtest on an original POS CSV."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path
from statistics import mean
from typing import Any, Dict, List, Tuple

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from hotpot_platform.cloud.integrations.pos_bridge import load_sku_sales_csv


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run_backtest(csv_path: Path, store_id: str, lookback_days: int, eval_days: int, min_covered_days: int) -> Dict[str, Any]:
    records = load_sku_sales_csv(csv_path, store_id)
    by_sku: Dict[str, List[Tuple[date, float]]] = defaultdict(list)
    seen: set[Tuple[str, str]] = set()
    for record in records:
        key = (record["business_date"], record["sku"])
        if key in seen:
            raise ValueError(f"duplicate business_date+sku: {key[0]} / {key[1]}")
        seen.add(key)
        by_sku[record["sku"]].append((date.fromisoformat(record["business_date"]), record["qty_sold"]))
    covered_days = {d for series in by_sku.values() for d, _ in series}
    if len(covered_days) < min_covered_days:
        raise ValueError(f"only {len(covered_days)} covered business days; require at least {min_covered_days}")

    details: List[Dict[str, Any]] = []
    for sku, series in sorted(by_sku.items()):
        series.sort(key=lambda item: item[0])
        for index in range(lookback_days, len(series)):
            target_date, actual = series[index]
            if index < len(series) - eval_days or actual == 0:
                continue
            predicted = mean(quantity for _, quantity in series[index - lookback_days:index])
            details.append({"sku": sku, "business_date": target_date.isoformat(), "actual_qty": actual,
                            "predicted_qty": round(predicted, 4), "absolute_error": round(abs(actual - predicted), 4)})
    if not details:
        raise ValueError("not enough non-zero history for the requested backtest window")

    mape = mean(item["absolute_error"] / item["actual_qty"] for item in details) * 100
    total_actual = sum(item["actual_qty"] for item in details)
    wape = sum(item["absolute_error"] for item in details) / total_actual * 100
    sku_metrics: Dict[str, Dict[str, Any]] = {}
    for sku in sorted({item["sku"] for item in details}):
        rows = [item for item in details if item["sku"] == sku]
        sku_metrics[sku] = {"prediction_count": len(rows), "mape_pct": round(mean(r["absolute_error"] / r["actual_qty"] for r in rows) * 100, 2)}
    verdict = "GO" if mape <= 45 else "GO_WITH_CALIBRATION" if mape <= 55 else "NO_GO"
    return {"evidence_type": "real_pos_l1_backtest", "store_id": store_id, "source_file": csv_path.name,
            "source_sha256": _sha256(csv_path), "model": f"L1_{lookback_days}day_moving_average",
            "covered_business_days": len(covered_days), "evaluation_window_days": eval_days,
            "prediction_count": len(details), "mape_pct": round(mape, 2), "wape_pct": round(wape, 2),
            "go_no_go": verdict, "sku_metrics": sku_metrics, "details": details}


def main() -> None:
    parser = argparse.ArgumentParser(description="Traceable real-POS L1 Sprint 0 backtest")
    parser.add_argument("--csv", required=True, type=Path)
    parser.add_argument("--store-id", required=True)
    parser.add_argument("--lookback-days", type=int, default=7)
    parser.add_argument("--eval-days", type=int, default=15)
    parser.add_argument("--min-covered-days", type=int, default=90)
    parser.add_argument("--report", required=True, type=Path)
    args = parser.parse_args()
    if min(args.lookback_days, args.eval_days, args.min_covered_days) < 1:
        raise SystemExit("lookback-days, eval-days and min-covered-days must be positive")
    report = run_backtest(args.csv, args.store_id, args.lookback_days, args.eval_days, args.min_covered_days)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key not in {"details", "sku_metrics"}}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
