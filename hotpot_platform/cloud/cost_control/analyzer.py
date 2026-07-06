#!/usr/bin/env python3
"""Incoming ingredient cost control analyzer."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from common.schemas import EventLevel, EventSource, OpsEvent, utc_now_iso

DEFAULT_MATERIALS_PATH = PROJECT_ROOT / "demo" / "data" / "incoming_materials.json"

# Standard yield rates for hotpot key ingredients (% usable after trim)
STANDARD_YIELD = {
    "毛肚": 0.92,
    "鲜牛肉": 0.88,
    "鸭血": 0.98,
    "虾滑": 0.95,
    "蔬菜拼盘": 0.85,
    "底料": 0.99,
    "蘸料": 0.98,
}


class CostControlAnalyzer:
    """Analyze incoming material records for cost anomalies."""

    def __init__(
        self,
        price_tolerance: float = 0.05,
        weight_tolerance: float = 0.03,
        yield_tolerance: float = 0.05,
    ) -> None:
        self.price_tolerance = price_tolerance
        self.weight_tolerance = weight_tolerance
        self.yield_tolerance = yield_tolerance

    def analyze_batch(
        self,
        records: List[Dict[str, Any]],
        store_id: str = "store_yuhuan",
        iot_enrichments: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        iot_map = {e["batch_id"]: e for e in (iot_enrichments or [])}
        analyzed: List[Dict[str, Any]] = []
        events: List[Dict[str, Any]] = []
        total_po_amount = 0.0
        total_actual_amount = 0.0
        total_variance = 0.0
        reject_count = 0

        for rec in records:
            iot = iot_map.get(rec.get("batch_id", ""), {})
            item = self._analyze_one(rec, iot)
            analyzed.append(item)
            total_po_amount += item["po_amount"]
            total_actual_amount += item["actual_amount"]
            total_variance += item["variance_amount"]
            if item["action"] == "reject":
                reject_count += 1

            for alert in item["alerts"]:
                level = EventLevel.CRITICAL.value if alert["severity"] == "critical" else EventLevel.WARN.value
                ev = OpsEvent(
                    event_type=alert["type"],
                    source=EventSource.SYSTEM.value,
                    level=level,
                    store_id=store_id,
                    zone="kitchen",
                    message=alert["message"],
                    metadata={
                        "batch_id": rec.get("batch_id", ""),
                        "sku": rec.get("sku", ""),
                        "supplier": rec.get("supplier", ""),
                        **alert.get("details", {}),
                    },
                )
                events.append(ev.to_dict())

        variance_rate = round(total_variance / total_po_amount * 100, 2) if total_po_amount else 0.0
        return {
            "store_id": store_id,
            "analyzed_at": utc_now_iso(),
            "batch_count": len(records),
            "total_po_amount": round(total_po_amount, 2),
            "total_actual_amount": round(total_actual_amount, 2),
            "total_variance_amount": round(total_variance, 2),
            "variance_rate_pct": variance_rate,
            "reject_count": reject_count,
            "items": analyzed,
            "events": events,
            "recommendations": self._recommendations(analyzed, variance_rate),
        }

    def _analyze_one(self, rec: Dict[str, Any], iot: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        iot = iot or {}
        sku = rec.get("sku", "未知")
        po_qty = float(rec.get("po_qty_kg", 0))
        # Prefer IoT scale reading over manual entry when available
        actual_qty = float(iot.get("iot_actual_qty_kg", rec.get("actual_qty_kg", po_qty)))
        po_price = float(rec.get("po_unit_price", 0))
        actual_price = float(rec.get("actual_unit_price", po_price))
        usable_qty = float(iot.get("iot_usable_qty_kg", rec.get("usable_qty_kg", actual_qty)))
        quality_grade = rec.get("quality_grade", "A")  # A/B/C from VLM
        iot_probe = iot.get("iot_probe_temp")
        iot_rfid_ok = iot.get("iot_rfid_ok")

        po_amount = po_qty * po_price
        actual_amount = actual_qty * actual_price
        variance_amount = actual_amount - po_amount

        alerts: List[Dict[str, Any]] = []
        action = "accept"

        # Price variance
        if po_price > 0:
            price_diff = (actual_price - po_price) / po_price
            if price_diff > self.price_tolerance:
                alerts.append(
                    {
                        "type": "cost_price_over",
                        "severity": "warn",
                        "message": f"{sku} 来料单价超 PO {price_diff*100:.1f}%（PO ¥{po_price}/kg → 实收 ¥{actual_price}/kg）",
                        "details": {"price_diff_pct": round(price_diff * 100, 2), "po_price": po_price, "actual_price": actual_price},
                    }
                )

        # Weight shortage
        if po_qty > 0:
            weight_diff = (po_qty - actual_qty) / po_qty
            if weight_diff > self.weight_tolerance:
                alerts.append(
                    {
                        "type": "cost_weight_short",
                        "severity": "warn",
                        "message": f"{sku} 来料短重 {weight_diff*100:.1f}%（PO {po_qty}kg → 实收 {actual_qty}kg）",
                        "details": {"short_pct": round(weight_diff * 100, 2), "po_qty": po_qty, "actual_qty": actual_qty},
                    }
                )

        # Yield rate (出成率)
        if actual_qty > 0:
            yield_rate = usable_qty / actual_qty
            std_yield = STANDARD_YIELD.get(sku, 0.90)
            if yield_rate < std_yield - self.yield_tolerance:
                alerts.append(
                    {
                        "type": "cost_yield_low",
                        "severity": "warn",
                        "message": f"{sku} 出成率 {yield_rate*100:.1f}% 低于标准 {std_yield*100:.0f}%",
                        "details": {"yield_rate": round(yield_rate, 3), "standard_yield": std_yield},
                    }
                )

        # VLM quality grade
        if quality_grade in ("C", "D"):
            alerts.append(
                {
                    "type": "cost_quality_reject",
                    "severity": "critical",
                    "message": f"{sku} VLM 质检评级 {quality_grade}，建议拒收或降价入库",
                    "details": {"quality_grade": quality_grade},
                }
            )
            action = "reject"
        elif quality_grade == "B" and variance_amount > po_amount * 0.03:
            action = "negotiate"

        # Expiry risk
        shelf_days = rec.get("remaining_shelf_days")
        if shelf_days is not None and shelf_days < 2:
            alerts.append(
                {
                    "type": "cost_near_expiry",
                    "severity": "warn",
                    "message": f"{sku} 临期风险：剩余保质期 {shelf_days} 天",
                    "details": {"remaining_shelf_days": shelf_days},
                }
            )

        # IoT temperature at receiving (quality proxy)
        if iot_probe is not None and float(iot_probe) > 4:
            alerts.append(
                {
                    "type": "iot_temp_abnormal",
                    "severity": "critical" if float(iot_probe) > 8 else "warn",
                    "message": f"{sku} IoT探针到货温度 {iot_probe}°C 超标，品质风险",
                    "details": {"iot_probe_temp": iot_probe, "source": "iot"},
                }
            )

        if iot_rfid_ok is False:
            alerts.append(
                {
                    "type": "iot_rfid_missing",
                    "severity": "warn",
                    "message": f"{sku} IoT RFID 未扫描，数量/批次无法追溯",
                    "details": {"source": "iot"},
                }
            )

        return {
            "batch_id": rec.get("batch_id", ""),
            "sku": sku,
            "supplier": rec.get("supplier", ""),
            "po_amount": round(po_amount, 2),
            "actual_amount": round(actual_amount, 2),
            "variance_amount": round(variance_amount, 2),
            "variance_pct": round(variance_amount / po_amount * 100, 2) if po_amount else 0,
            "yield_rate": round(usable_qty / actual_qty, 3) if actual_qty else 0,
            "quality_grade": quality_grade,
            "action": action,
            "alerts": alerts,
            "iot_actual_qty_kg": actual_qty if iot.get("iot_actual_qty_kg") else None,
            "iot_usable_qty_kg": usable_qty if iot.get("iot_usable_qty_kg") else None,
            "data_sources": {
                "quantity": "iot" if iot.get("iot_actual_qty_kg") else "manual",
                "quality": "vlm+iot" if iot_probe is not None else "vlm",
            },
        }

    def _recommendations(self, items: List[Dict[str, Any]], variance_rate: float) -> List[str]:
        recs = []
        over_price = [i for i in items if any(a["type"] == "cost_price_over" for a in i["alerts"])]
        low_yield = [i for i in items if any(a["type"] == "cost_yield_low" for a in i["alerts"])]
        rejects = [i for i in items if i["action"] == "reject"]

        if variance_rate > 3:
            recs.append(f"本批次来料综合成本偏差 {variance_rate:.1f}%，建议启动供应商复核与议价")
        if over_price:
            recs.append(f"{len(over_price)} 个 SKU 单价超 PO，联动采购中心更新协议价或更换供应商")
        if low_yield:
            recs.append(f"{len(low_yield)} 个 SKU 出成率偏低，排查分拣/解冻 SOP 执行与刀工损耗")
        if rejects:
            recs.append(f"{len(rejects)} 批来料建议拒收，触发 VLM 质检复核与退货流程")
        if not recs:
            recs.append("来料成本在控，继续保持收货秤重 + 质检双人复核")
        return recs


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Incoming material cost control analyzer")
    parser.add_argument("--input", default=str(DEFAULT_MATERIALS_PATH))
    parser.add_argument("--store-id", default="store_yuhuan")
    parser.add_argument("--hub-url", default="")
    parser.add_argument("--iot-enrichments", default="", help="JSON from ingredient IoT bridge")
    args = parser.parse_args()

    records = json.loads(Path(args.input).read_text(encoding="utf-8"))
    iot_enrichments = []
    if args.iot_enrichments:
        iot_data = json.loads(Path(args.iot_enrichments).read_text(encoding="utf-8"))
        iot_enrichments = iot_data.get("cost_enrichments", iot_data if isinstance(iot_data, list) else [])

    analyzer = CostControlAnalyzer()
    result = analyzer.analyze_batch(records, args.store_id, iot_enrichments)
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
            f"{hub}/cost",
            data=json.dumps(result).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        urllib.request.urlopen(stats_req, timeout=5)
        print("[OK] Posted cost analysis to hub", file=sys.stderr)


if __name__ == "__main__":
    main()
