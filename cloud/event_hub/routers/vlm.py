"""VLM routes — waste estimate mock-first (VLM-603 · LOSS-431 / §2.3)."""

from __future__ import annotations

from typing import Any, Dict, Optional

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

    @model_validator(mode="after")
    def require_image_or_stream(self) -> "WasteEstimateBody":
        if not self.image_ref and not self.stream_id:
            raise ValueError("image_ref or stream_id is required")
        return self


@router.post("/v1/vlm/waste-estimate")
def vlm_waste_estimate(
    body: WasteEstimateBody,
    auth: AuthContext = Depends(get_auth_context),
) -> Dict[str, Any]:
    """废料识别 mock-first（P1C/P2）。契约见 kitchen_loss_budget_solution.md §2.3。

    无边缘 VLM 时 ``source=mock`` 且不 500；写入 ``vlm_waste_estimate`` 事件并
    刷新 ``loss_features`` snapshot（waste_evidence 入口）。
    """
    sid = body.store_id or auth.store_id or DEFAULT_STORE_ID
    enforce_store_write(auth, sid)

    result = compute_waste_estimate(
        store_id=sid,
        image_ref=body.image_ref,
        stream_id=body.stream_id,
        zone=body.zone,
        ts=body.ts,
    )
    store = runtime.hub.get_store(sid)
    event = store.add_event(
        {
            "event_type": "vlm_waste_estimate",
            "source": result["source"],
            "level": "info",
            "message": f"VLM 废料识别 {result['items'][0].get('sku')} · {result['source']}",
            "metadata": {
                **result,
                "ref_type": "waste_estimate",
                "ref_id": body.image_ref or body.stream_id,
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
