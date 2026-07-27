"""Loss-feature snapshot builder (LOSS-504 · P1B skeleton).

Aggregates a store's cost snapshot into a per-SKU loss-feature snapshot and
persists it to ``store_snapshots(kind="loss_features")`` via the EventStore
persist hook. Pure builder + thin persist helper — no FastAPI dependency.

Per Codex PK convergence (docs/kitchen_loss_budget_solution.md §3): Phase 1
persists features (not temporary JSON); relational loss_features/loss_predictions
tables are deferred to LOSS-508.

Phase 1 extension: now also aggregates waste cost data from visual AI
detection and inventory snapshot data for the data engine.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def build_loss_features(
    cost_stats: Dict[str, Any], *, store_id: str, date: Optional[str] = None
) -> Dict[str, Any]:
    """Build a loss-feature snapshot from a cost snapshot (pure function)."""
    items = (cost_stats or {}).get("items") or []
    feat_items = [
        {
            "batch_id": i.get("batch_id"),
            "sku": i.get("sku"),
            "variance_pct": i.get("variance_pct"),
            "vlm_grade": i.get("vlm_grade"),
            "temp_c": i.get("temp_c"),
        }
        for i in items
    ]
    return {
        "store_id": store_id,
        "date": date,
        "generated_at": _now_iso(),
        "items": feat_items,
        "sku_count": len({i["sku"] for i in feat_items if i.get("sku")}),
    }


def build_waste_cost_features(
    waste_cost_report: Dict[str, Any],
    *,
    store_id: str,
    date: Optional[str] = None,
) -> Dict[str, Any]:
    """Build waste cost features from a WasteCostCalculator report.

    Extends the loss-features concept with visual AI waste detection data:
    - per-SKU waste count, weight, cost
    - category breakdown
    - top loss SKUs
    """
    report = waste_cost_report or {}
    return {
        "store_id": store_id,
        "date": date,
        "generated_at": _now_iso(),
        "source": "waste_vision",
        "summary": report.get("summary", {}),
        "items": [
            {
                "sku": i.get("sku"),
                "category": i.get("category"),
                "waste_count": i.get("total_count"),
                "waste_weight_kg": i.get("total_weight_kg"),
                "waste_cost": i.get("total_cost"),
                "unit_cost": i.get("unit_cost"),
                "waste_types": i.get("waste_types", []),
            }
            for i in report.get("items", [])
        ],
        "category_breakdown": report.get("category_breakdown", {}),
        "top_loss_skus": report.get("top_loss_skus", []),
    }


def build_inventory_features(
    inventory_items: List[Dict[str, Any]],
    *,
    store_id: str,
    date: Optional[str] = None,
) -> Dict[str, Any]:
    """Build inventory features from inventory snapshot data.

    Captures current stock levels, low-stock alerts, and days-of-supply
    for each SKU — feeds into the prediction and ordering pipeline.
    """
    items = inventory_items or []
    low_stock = [i for i in items if i.get("is_low_stock")]

    return {
        "store_id": store_id,
        "date": date,
        "generated_at": _now_iso(),
        "source": "inventory_snapshot",
        "total_skus": len(items),
        "low_stock_count": len(low_stock),
        "items": [
            {
                "sku": i.get("sku"),
                "on_hand_qty": i.get("on_hand_qty"),
                "unit": i.get("unit", "kg"),
                "avg_daily_consumption": i.get("avg_daily_consumption"),
                "days_of_supply": i.get("days_of_supply"),
                "is_low_stock": i.get("is_low_stock", False),
            }
            for i in items
        ],
        "low_stock_skus": [i.get("sku") for i in low_stock],
    }


def build_combined_features(
    cost_stats: Dict[str, Any],
    waste_cost_report: Optional[Dict[str, Any]] = None,
    inventory_items: Optional[List[Dict[str, Any]]] = None,
    *,
    store_id: str,
    date: Optional[str] = None,
) -> Dict[str, Any]:
    """Build a combined feature snapshot from all available data sources.

    Merges:
    1. Cost control features (from receiving analysis)
    2. Waste cost features (from visual AI detection)
    3. Inventory features (from stock snapshot)
    """
    loss_feats = build_loss_features(cost_stats, store_id=store_id, date=date)
    waste_feats = build_waste_cost_features(waste_cost_report or {}, store_id=store_id, date=date)
    inv_feats = build_inventory_features(inventory_items or [], store_id=store_id, date=date)

    return {
        "store_id": store_id,
        "date": date,
        "generated_at": _now_iso(),
        "sources": ["cost_control", "waste_vision", "inventory"],
        "loss_features": loss_feats,
        "waste_cost_features": waste_feats,
        "inventory_features": inv_feats,
        "combined_sku_count": len(
            set(
                (i.get("sku") for i in loss_feats.get("items", []))
            ) | set(
                (i.get("sku") for i in waste_feats.get("items", []))
            ) | set(
                (i.get("sku") for i in inv_feats.get("items", []))
            )
        ),
    }


def persist_loss_features(store: Any, features: Dict[str, Any]) -> None:
    """Persist a loss-feature snapshot through the store's persist hook."""
    store.set_loss_features(features)
