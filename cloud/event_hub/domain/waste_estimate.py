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
    image_url: Optional[str] = None,
) -> Dict[str, Any]:
    """Return a structured waste estimate payload.

    Edge path: items non-empty → bypass mock, use directly (source from caller).
    Hub path: items None/empty → deterministic mock stub.
    image_url: 可选，边缘图片的静态文件 URL。
    """
    base: Dict[str, Any] = {
        "store_id": store_id,
        "source": source,
        "model": model,
        "image_ref": image_ref,
        "stream_id": stream_id,
        "zone": zone,
        "ts": ts,
    }
    # ── image_url: 优先用直接传入的 image_url，否则从 image_ref 提取静态路径 ──
    _url = image_url
    if not _url and image_ref:
        # 支持相对路径 /static/... 和完整 URL http://.../static/...
        if image_ref.startswith("/static/"):
            _url = image_ref
        elif "/static/" in image_ref:
            # 从完整 URL 中提取 /static/... 部分
            idx = image_ref.index("/static/")
            _url = image_ref[idx:]
    if _url:
        base["image_url"] = _url

    # ── edge inference path (Jetson/edge box already inferred) ──
    if items:
        base["items"] = items
        return base

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
    base["source"] = _source
    base["model"] = _model
    base["items"] = [item]
    return base
