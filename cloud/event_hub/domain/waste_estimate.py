"""VLM waste estimate domain (VLM-603 / kitchen_loss_budget_solution §2.3).

Edge path: when ``items`` is provided, use them directly (Jetson already inferred).
Mock path: deterministic stub when items is None/empty.
"""

from __future__ import annotations

import hashlib
import os
from typing import Any, Dict, List, Optional


_MOCK_SKUS = ("毛肚", "鸭肠", "黄喉", "午餐肉")
_WASTE_TYPES = ("备餐废弃", "边角料", "过期临界")


def _mock_confidence(seed: str) -> float:
    digest = hashlib.sha256(seed.encode()).hexdigest()
    return round(0.55 + (int(digest[:4], 16) % 300) / 1000, 2)


def compute_waste_estimate(
    *,
    store_id: str,
    image_ref: Optional[str] = None,
    stream_id: Optional[str] = None,
    zone: Optional[str] = None,
    ts: Optional[str] = None,
    items: Optional[List[Dict[str, Any]]] = None,
    source: str = "mock",
    model: str = "mock-rule",
) -> Dict[str, Any]:
    """Return a structured waste estimate payload.

    Edge path: items non-empty → bypass mock, use directly (source from caller).
    Hub path: items None/empty → deterministic mock stub.
    """
    # ── edge inference path (Jetson/edge box already inferred) ──
    if items:
        return {
            "store_id": store_id,
            "source": source,
            "model": model,
            "image_ref": image_ref,
            "stream_id": stream_id,
            "zone": zone,
            "ts": ts,
            "items": items,
        }

    # ── hub mock path ──
    ref = image_ref or stream_id or ""
    idx = int(hashlib.md5(ref.encode()).hexdigest(), 16)
    sku = _MOCK_SKUS[idx % len(_MOCK_SKUS)]
    waste_type = _WASTE_TYPES[idx % len(_WASTE_TYPES)]
    portion = round(0.4 + (idx % 5) * 0.15, 1)
    use_vlm = os.environ.get("HOTPOT_VLM_WASTE", "0") == "1"
    _source = "vlm-shadow" if use_vlm else "mock"
    _model = "qwen2.5-vl-3b" if use_vlm else "mock-rule"
    item: Dict[str, Any] = {
        "waste_type": waste_type,
        "sku": sku,
        "estimated_portion": portion,
        "unit": "份",
        "confidence": _mock_confidence(ref),
        "reason": f"{zone or '废弃区'} 检测到 {sku} {waste_type}（{_source}）",
        "suggested_action": "优先复称并记录供应商品质",
    }
    if zone:
        item["zone"] = zone
    return {
        "store_id": store_id,
        "source": _source,
        "model": _model,
        "image_ref": image_ref,
        "stream_id": stream_id,
        "zone": zone,
        "ts": ts,
        "items": [item],
    }
