"""VLM routes — waste estimate (VLM-603 · LOSS-431 / §2.3).

Edge path: ``items`` present → use directly (Jetson already inferred).
Hub path:  no items → deterministic mock.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, model_validator

from cloud.event_hub import runtime
from cloud.event_hub.auth import AuthContext, get_auth_context, enforce_store_write
from cloud.event_hub.domain.waste_estimate import compute_waste_estimate
from cloud.event_hub.hub_core import DEFAULT_STORE_ID
from cloud.cost_control.feature_builder import build_loss_features, persist_loss_features
from shared.schemas import utc_now_iso

router = APIRouter()


class WasteEstimateBody(BaseModel):
    store_id: Optional[str] = None
    image_ref: Optional[str] = None
    stream_id: Optional[str] = None
    zone: Optional[str] = None
    ts: Optional[str] = None
    # ── edge inference fields ──
    items: Optional[List[Dict[str, Any]]] = None
    source: str = "mock"
    model: str = "mock-rule"

    @model_validator(mode="after")
    def require_input_source(self) -> "WasteEstimateBody":
        # 允许三种输入源：image_ref / stream_id / items（边缘已推理）
        if not self.image_ref and not self.stream_id and not self.items:
            raise ValueError("至少需要 image_ref、stream_id 或 items 之一")
        return self


@router.post("/v1/vlm/waste-estimate")
def vlm_waste_estimate(
    body: WasteEstimateBody,
    auth: AuthContext = Depends(get_auth_context),
) -> Dict[str, Any]:
    """废料识别。

    items 非空（Jetson 桥接）→ 走真实 VLM 路径（source 由调用方标注）；
    否则走 mock。始终写入事件并刷新 loss_features snapshot。
    """
    sid = body.store_id or auth.store_id or DEFAULT_STORE_ID
    enforce_store_write(auth, sid)

    result = compute_waste_estimate(
        store_id=sid,
        image_ref=body.image_ref,
        stream_id=body.stream_id,
        zone=body.zone,
        ts=body.ts,
        items=body.items,
        source=body.source,
        model=body.model,
    )
    store = runtime.hub.get_store(sid)
    event = store.add_event(
        {
            "event_type": "vlm_waste_estimate",
            "source": result["source"],
            "level": "info",
            "message": (
                f"VLM 废料识别 {len(result['items'])} 项"
                f" · {result['source']}"
            ),
            "metadata": {
                **result,
                "ref_type": "waste_estimate",
                "ref_id": body.image_ref or body.stream_id or "edge-inferred",
            },
        }
    )

    cost = store.cost_stats or {"store_id": sid, "items": []}
    features = build_loss_features(cost, store_id=sid)
    features["waste_evidence"] = result["items"]
    features["waste_source"] = result["source"]
    persist_loss_features(store, features)

    return {
        "ok": True,
        "event_id": event.get("event_id"),
        "generated_at": utc_now_iso(),
        **result,
    }
