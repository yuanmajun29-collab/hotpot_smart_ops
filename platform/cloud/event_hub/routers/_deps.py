"""Shared dependencies, helper functions, and Pydantic body models for Event Hub routers."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel

from platform.cloud.event_hub.auth import AuthContext, can_read_store, enforce_store_read, enforce_action
from platform.cloud.event_hub.hub_core import DEFAULT_STORE_ID


def resolve_store_id(
    store_id: Optional[str],
    body: Any,
    header_store: Optional[str],
    auth: AuthContext,
) -> str:
    sid = header_store or store_id
    if not sid and isinstance(body, dict):
        sid = body.get("store_id")
    if not sid and isinstance(body, list) and body and isinstance(body[0], dict):
        sid = body[0].get("store_id")
    sid = sid or DEFAULT_STORE_ID
    enforce_store_read(auth, sid)
    return sid


def readable_store_ids(store_ids: List[str], auth: AuthContext) -> List[str]:
    return [sid for sid in store_ids if can_read_store(auth, sid)]


def _enforce_report_generate(auth: AuthContext) -> None:
    enforce_action(auth, "report_generate")


def _append_cost_item(store: Any, batch: Dict[str, Any], signatures: List[Dict[str, Any]]) -> None:
    cost = dict(store.cost_stats or {"store_id": store.store_id, "items": []})
    items = [dict(i) for i in cost.get("items", [])]
    var = batch.get("variance_pct")
    incoming = {
        "batch_id": batch["batch_id"],
        "po_id": batch["po_id"],
        "sku": batch["sku"],
        "weight_kg": batch["weight_kg"],
        "po_weight_kg": batch.get("po_weight_kg"),
        "variance_pct": var,
        "vlm_grade": batch.get("vlm_grade"),
        "temp_c": batch.get("temp_c"),
        "signatures": signatures,
        "submitted_at": batch.get("created_at"),
    }
    merged_items: List[Dict[str, Any]] = []
    merged = False
    for item in items:
        if item.get("batch_id") != batch["batch_id"]:
            merged_items.append(item)
            continue
        if merged:
            continue
        merged_item = {**item, **incoming}
        for key in ("vlm_grade", "temp_c"):
            if incoming.get(key) is None and item.get(key) is not None:
                merged_item[key] = item[key]
        merged_items.append(merged_item)
        merged = True
    if not merged:
        merged_items.append(incoming)
    cost["items"] = merged_items
    if var is not None:
        shorts = [i for i in merged_items if (i.get("variance_pct") or 0) < -3]
        cost["short_weight_count"] = len(shorts)
        cost["variance_rate_pct"] = var
    store.set_cost_stats(cost)


class SopAskBody(BaseModel):
    question: str
    backend: Optional[str] = "rule"
    top_k: int = 3


class AlertAckBody(BaseModel):
    event_id: str
    store_id: Optional[str] = None
    ack_by: Optional[str] = "店长"
    ack_note: Optional[str] = ""


class SignatureInput(BaseModel):
    role: str
    signed_by: str


class ReceivingSubmitBody(BaseModel):
    batch_id: Optional[str] = None
    store_id: Optional[str] = None
    po_id: str
    sku: str
    weight_kg: float
    po_weight_kg: Optional[float] = None
    vlm_grade: Optional[str] = None
    temp_c: Optional[float] = None
    signatures: List[SignatureInput]


class SopAssignBody(BaseModel):
    store_id: Optional[str] = None
    sop_id: str
    sop_name: Optional[str] = None
    assignee: str
    due_at: Optional[str] = None
    event_id: Optional[str] = None
    note: Optional[str] = ""


class SopAssignStatusBody(BaseModel):
    status: str
    store_id: Optional[str] = None


class IotReadingInput(BaseModel):
    sensor_id: str
    sensor_type: str
    value: float
    unit: Optional[str] = ""
    recorded_at: Optional[str] = None


class IotReadingsBatchBody(BaseModel):
    store_id: Optional[str] = None
    readings: List[IotReadingInput]


class DailyReportGenerateBody(BaseModel):
    store_id: Optional[str] = None
    push: bool = False
    report_date: Optional[str] = None


class AdminStoreCreate(BaseModel):
    store_name: str
    region_id: str = "region_taizhou"
    city: str = ""
    store_type: str = "direct"
    status: str = "preparing"


class AdminStoreUpdate(BaseModel):
    store_name: Optional[str] = None
    city: Optional[str] = None
    store_type: Optional[str] = None
    status: Optional[str] = None
    note: Optional[str] = None
    region_id: Optional[str] = None


class PipelineTickBody(BaseModel):
    store_id: Optional[str] = None
    mode: str = "inprocess"  # inprocess | subprocess
    inject_anomaly: bool = False
    hub_url: str = "http://127.0.0.1:8088"
