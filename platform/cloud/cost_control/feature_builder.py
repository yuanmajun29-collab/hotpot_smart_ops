"""Loss-feature snapshot builder (LOSS-504 · P1B skeleton).

Aggregates a store's cost snapshot into a per-SKU loss-feature snapshot and
persists it to ``store_snapshots(kind="loss_features")`` via the EventStore
persist hook. Pure builder + thin persist helper — no FastAPI dependency.

Per Codex PK convergence (docs/kitchen_loss_budget_solution.md §3): Phase 1
persists features (not temporary JSON); relational loss_features/loss_predictions
tables are deferred to LOSS-508.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional


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


def persist_loss_features(store: Any, features: Dict[str, Any]) -> None:
    """Persist a loss-feature snapshot through the store's persist hook."""
    store.set_loss_features(features)
