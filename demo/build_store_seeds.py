#!/usr/bin/env python3
"""Build per-store seed bundles for multi-tenant Event Hub."""

from __future__ import annotations

import copy
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "demo" / "data"
OUT = DATA / "stores"


def _load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _rewrite_store(obj, store_id: str, store_name: str):
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if k == "store_id":
                out[k] = store_id
            elif k == "store_name":
                out[k] = store_name
            else:
                out[k] = _rewrite_store(v, store_id, store_name)
        return out
    if isinstance(obj, list):
        return [_rewrite_store(x, store_id, store_name) for x in obj]
    return obj


def build_yuhuan_seed() -> dict:
    front = _load(DATA / "front_result.json")
    sid = "store_yuhuan"
    name = "冯校长火锅·玉环店"
    return {
        "store_id": sid,
        "pos_stats": {
            "store_id": sid,
            "store_name": name,
            "date": "2026-06-12",
            "turnover_rate": 2.6,
            "daily_revenue": 51200,
            "avg_ticket": 128,
            "table_count": 40,
            "dish_timeout_count": 4,
            "queue_count": 18,
            "queue_lost_rate": 0.12,
            "food_cost_rate": 0.32,
            "staff_count": 28,
        },
        "table_states": front.get("table_states", []),
        "sample_events": _rewrite_store(_load(DATA / "sample_events.json"), sid, name),
        "sop_stats": _rewrite_store(_load(DATA / "sop_result.json"), sid, name),
        "cost_stats": _rewrite_store(_load(DATA / "cost_result.json"), sid, name),
        "iot_stats": _rewrite_store(_load(DATA / "iot_lifecycle_result.json"), sid, name),
    }


def build_jiaojiang_seed(yuhuan: dict) -> dict:
    seed = copy.deepcopy(yuhuan)
    sid = "store_jiaojiang"
    name = "冯校长火锅·椒江店"
    seed = _rewrite_store(seed, sid, name)
    seed["store_id"] = sid

    seed["pos_stats"].update(
        {
            "turnover_rate": 2.9,
            "daily_revenue": 46800,
            "avg_ticket": 118,
            "dish_timeout_count": 2,
            "queue_count": 12,
            "queue_lost_rate": 0.08,
            "food_cost_rate": 0.30,
            "staff_count": 24,
        }
    )

    # 椒江店桌态更均衡：翻台压力较小
    seed["table_states"] = [
        {"table_id": "T01", "state": "empty", "confidence": 0.88, "updated_at": "2026-06-12T12:00:00+00:00"},
        {"table_id": "T02", "state": "dining", "confidence": 0.82, "updated_at": "2026-06-12T12:00:00+00:00"},
        {"table_id": "T03", "state": "dining", "confidence": 0.85, "updated_at": "2026-06-12T12:00:00+00:00"},
        {"table_id": "T04", "state": "empty", "confidence": 0.90, "updated_at": "2026-06-12T12:00:00+00:00"},
        {"table_id": "T05", "state": "checkout", "confidence": 0.91, "updated_at": "2026-06-12T12:00:00+00:00"},
        {"table_id": "T06", "state": "dining", "confidence": 0.80, "updated_at": "2026-06-12T12:00:00+00:00"},
        {"table_id": "T07", "state": "empty", "confidence": 0.87, "updated_at": "2026-06-12T12:00:00+00:00"},
        {"table_id": "T08", "state": "need_clean", "confidence": 0.84, "updated_at": "2026-06-12T12:00:00+00:00"},
    ]

    seed["sample_events"] = [
        {
            "event_type": "table_empty",
            "source": "vision",
            "level": "info",
            "store_id": sid,
            "zone": "front",
            "table_id": "T01",
            "message": "桌位 T01: 空桌可入座",
            "confidence": 0.93,
        },
        {
            "event_type": "table_checkout",
            "source": "vision",
            "level": "info",
            "store_id": sid,
            "zone": "front",
            "table_id": "T05",
            "message": "桌位 T05: 待结账",
            "confidence": 0.89,
        },
        {
            "event_type": "table_need_clean",
            "source": "vision",
            "level": "warn",
            "store_id": sid,
            "zone": "front",
            "table_id": "T08",
            "message": "桌位 T08: 待清台",
            "confidence": 0.86,
        },
        {
            "event_type": "cold_chain_warn",
            "source": "iot",
            "level": "warn",
            "store_id": sid,
            "zone": "kitchen",
            "message": "cold_storage_1 温度偏高: -16.2°C（建议巡检）",
            "metadata": {"sensor_id": "cold_storage_1", "value": -16.2},
        },
        {
            "event_type": "dish_timeout",
            "source": "pos",
            "level": "warn",
            "store_id": sid,
            "zone": "kitchen",
            "message": "订单 #9012 出餐超时 8 分钟",
            "metadata": {"order_id": "9012", "delay_min": 8},
        },
    ]

    sop = seed["sop_stats"]
    sop["passed"] = 4
    sop["failed"] = 1
    sop["compliance_rate"] = 80.0
    for r in sop.get("results", []):
        if r.get("sop_id") == "sop_opening":
            r["status"] = "passed"
            r["reason"] = "开档检查全部达标"
            for cp in r.get("checkpoints", []):
                if cp.get("id") == "kitchen_gear_ok":
                    cp["passed"] = True
                    cp["actual"] = True

    cost = seed["cost_stats"]
    cost["variance_rate_pct"] = 1.2
    cost["total_variance_amount"] = 42.5
    cost["reject_count"] = 0

    iot = seed["iot_stats"]
    if "summary" in iot:
        iot["summary"]["iot_alert_count"] = 1

    return seed


def main() -> None:
    yuhuan = build_yuhuan_seed()
    jiaojiang = build_jiaojiang_seed(yuhuan)

    for sid, seed in (("store_yuhuan", yuhuan), ("store_jiaojiang", jiaojiang)):
        out_dir = OUT / sid
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / "seed.json"
        out_path.write_text(json.dumps(seed, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[OK] wrote {out_path}")


if __name__ == "__main__":
    main()
