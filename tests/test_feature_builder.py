"""Loss-feature snapshot builder + persistence (LOSS-504 · P1B skeleton).

Per Codex PK convergence: Phase 1 features persist to
store_snapshots(kind="loss_features"), not temporary JSON. Relational
loss_features/loss_predictions tables deferred to LOSS-508.
"""
from __future__ import annotations

import tempfile
from pathlib import Path


_COST = {
    "store_id": "store_yuhuan",
    "items": [
        {"batch_id": "B1", "sku": "毛肚", "variance_pct": -5.0, "vlm_grade": "D", "temp_c": -8.0},
        {"batch_id": "B2", "sku": "鸭肠", "variance_pct": 0.0, "vlm_grade": "A", "temp_c": -18.0},
    ],
}


def test_build_loss_features_shape():
    from cloud.cost_control.feature_builder import build_loss_features
    feats = build_loss_features(_COST, store_id="store_yuhuan", date="2026-06-21")
    assert feats["store_id"] == "store_yuhuan"
    assert feats["date"] == "2026-06-21"
    assert feats["generated_at"]
    assert feats["sku_count"] == 2
    skus = {i["sku"] for i in feats["items"]}
    assert skus == {"毛肚", "鸭肠"}
    mao = next(i for i in feats["items"] if i["sku"] == "毛肚")
    assert mao["batch_id"] == "B1" and mao["variance_pct"] == -5.0 and mao["vlm_grade"] == "D"


def test_loss_features_persist_roundtrip():
    from cloud.cost_control.feature_builder import build_loss_features, persist_loss_features
    from cloud.event_hub.db import create_hub_database
    from cloud.event_hub.hub_core import MultiTenantHub

    tmp = tempfile.mkdtemp()
    db_path = Path(tmp) / "feat.db"
    dbo = create_hub_database(db_path)
    hub = MultiTenantHub(on_persist=dbo.on_persist)

    feats = build_loss_features(_COST, store_id="store_yuhuan", date="2026-06-21")
    persist_loss_features(hub.get_store("store_yuhuan"), feats)

    # fresh hub hydrated from DB must see the persisted loss_features snapshot
    fresh = MultiTenantHub(on_persist=dbo.on_persist)
    dbo.load_store_into(fresh, "store_yuhuan")
    loaded = fresh.get_store("store_yuhuan").loss_features
    assert loaded["date"] == "2026-06-21"
    assert loaded["sku_count"] == 2
