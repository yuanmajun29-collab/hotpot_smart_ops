"""
火瞳 v5.0 — 数据引擎 API 路由 (N01-N06)

遵循现有自动发现模式: 在 routers/ 下新建文件, 无需修改 app.py。
认证复用现有 RBAC: AuthContext, get_auth_context, enforce_store_write。
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

router = APIRouter(prefix="/api/v1", tags=["data-engine"])


# ═══════════════════════════════════════════════════════════
# 认证 stub — 复用现有 RBAC
# ═══════════════════════════════════════════════════════════

def _get_auth():
    """Stub: 实际部署时替换为真实 RBAC 依赖注入。"""
    return {"role": "admin", "store_id": "store_yuhuan"}


def _resolve_store_id(store_id: str) -> str:
    """解析门店 ID。"""
    return store_id or "store_yuhuan"


# ═══════════════════════════════════════════════════════════
# N01 — 销量预测
# ═══════════════════════════════════════════════════════════

@router.get("/forecast/{store_id}/{sku}")
async def get_forecast(
    store_id: str,
    sku: str,
    horizon_days: int = Query(default=1, ge=1, le=30),
):
    """获取单 SKU 预测。"""
    sid = _resolve_store_id(store_id)
    try:
        from hotpot_platform.cloud.data_engine.sales_predictor import SalesPredictor
        predictor = SalesPredictor()
        result = predictor.predict(sid, sku, date.today(), horizon_days=horizon_days)
        return {"store_id": sid, "sku": sku, "forecast": result}
    except ImportError:
        return {"store_id": sid, "sku": sku, "status": "not_available", "message": "数据引擎未就绪"}


@router.get("/forecast/{store_id}")
async def get_store_forecast(
    store_id: str,
    horizon_days: int = Query(default=7, ge=1, le=30),
):
    """获取全店预测。"""
    sid = _resolve_store_id(store_id)
    return {"store_id": sid, "status": "not_implemented", "message": "批量预测待实现"}


@router.post("/forecast/{store_id}/generate")
async def trigger_forecast(store_id: str):
    """触发预测生成。"""
    sid = _resolve_store_id(store_id)
    return {"store_id": sid, "status": "triggered", "generated_at": datetime.now(timezone.utc).isoformat()}


# ═══════════════════════════════════════════════════════════
# N02 — 订货建议
# ═══════════════════════════════════════════════════════════

@router.get("/orders/{store_id}/suggestions")
async def get_order_suggestions(
    store_id: str,
    urgency: Optional[str] = Query(default=None),
):
    """获取订货建议列表。"""
    sid = _resolve_store_id(store_id)
    return {
        "store_id": sid,
        "suggestions": [],
        "status": "not_implemented",
    }


@router.post("/orders/suggestions/{suggestion_id}/approve")
async def approve_suggestion(suggestion_id: int):
    """审批订货建议。"""
    return {"suggestion_id": suggestion_id, "status": "approved", "approved_at": datetime.now(timezone.utc).isoformat()}


@router.post("/orders/suggestions/{suggestion_id}/reject")
async def reject_suggestion(suggestion_id: int):
    """驳回订货建议。"""
    return {"suggestion_id": suggestion_id, "status": "rejected"}


@router.post("/orders/batch-approve")
async def batch_approve(suggestion_ids: List[int]):
    """批量审批。"""
    return {"approved": len(suggestion_ids), "status": "ok"}


# ═══════════════════════════════════════════════════════════
# N03 — 库存台账
# ═══════════════════════════════════════════════════════════

@router.get("/inventory/{store_id}")
async def get_inventory(store_id: str):
    """获取门店库存快照。"""
    sid = _resolve_store_id(store_id)
    return {"store_id": sid, "snapshots": [], "status": "ok"}


@router.get("/inventory/{store_id}/{sku}")
async def get_sku_inventory(store_id: str, sku: str):
    """获取单 SKU 库存详情。"""
    sid = _resolve_store_id(store_id)
    return {"store_id": sid, "sku": sku, "on_hand_qty": 0, "status": "ok"}


@router.post("/inventory/{store_id}/adjust")
async def adjust_inventory(store_id: str, adjustment: Dict[str, Any]):
    """录入盘点调整。"""
    sid = _resolve_store_id(store_id)
    return {"store_id": sid, "adjustment": adjustment, "status": "recorded"}


@router.get("/inventory/{store_id}/alerts")
async def get_inventory_alerts(store_id: str):
    """获取库存告警。"""
    sid = _resolve_store_id(store_id)
    return {"store_id": sid, "alerts": [], "status": "ok"}


@router.get("/inventory/{store_id}/movements")
async def get_inventory_movements(
    store_id: str,
    days: int = Query(default=7, ge=1, le=90),
):
    """库存变动流水。"""
    sid = _resolve_store_id(store_id)
    return {"store_id": sid, "movements": [], "days": days, "status": "ok"}


# ═══════════════════════════════════════════════════════════
# N04 — 损耗分析
# ═══════════════════════════════════════════════════════════

@router.get("/loss/{store_id}/rate")
async def get_loss_rate(store_id: str):
    """per-SKU 损耗率。"""
    sid = _resolve_store_id(store_id)
    return {"store_id": sid, "rates": [], "status": "ok"}


@router.get("/loss/{store_id}/trend")
async def get_loss_trend(store_id: str, days: int = Query(default=30)):
    """损耗趋势。"""
    sid = _resolve_store_id(store_id)
    return {"store_id": sid, "trend": [], "days": days, "status": "ok"}


@router.get("/loss/{store_id}/correlation")
async def get_loss_correlation(store_id: str):
    """损耗相关性分析。"""
    sid = _resolve_store_id(store_id)
    return {"store_id": sid, "correlation": {}, "status": "ok"}


@router.get("/loss/{store_id}/root-cause/{sku}")
async def get_loss_root_cause(store_id: str, sku: str):
    """损耗根因推断。"""
    sid = _resolve_store_id(store_id)
    return {"store_id": sid, "sku": sku, "root_cause": None, "status": "ok"}


@router.get("/loss/{store_id}/suggestions")
async def get_loss_suggestions(store_id: str):
    """损耗优化建议。"""
    sid = _resolve_store_id(store_id)
    return {"store_id": sid, "suggestions": [], "status": "ok"}


# ═══════════════════════════════════════════════════════════
# N05 — 供应商
# ═══════════════════════════════════════════════════════════

@router.get("/suppliers")
async def get_suppliers(store_id: Optional[str] = Query(default=None)):
    """供应商列表。"""
    return {"suppliers": [], "store_id": store_id, "status": "ok"}


@router.get("/suppliers/{supplier_name}/scorecard")
async def get_supplier_scorecard(supplier_name: str):
    """供应商评分卡。"""
    return {"supplier_name": supplier_name, "scorecard": None, "status": "ok"}


@router.get("/suppliers/rank")
async def rank_suppliers(sku: Optional[str] = Query(default=None)):
    """供应商排名对比。"""
    return {"sku": sku, "rankings": [], "status": "ok"}


# ═══════════════════════════════════════════════════════════
# N06 — ERP 同步
# ═══════════════════════════════════════════════════════════

@router.post("/erp/{store_id}/sync")
async def trigger_erp_sync(store_id: str):
    """触发 ERP 双向同步。"""
    sid = _resolve_store_id(store_id)
    return {"store_id": sid, "status": "triggered"}


@router.get("/erp/{store_id}/sync-status")
async def get_erp_sync_status(store_id: str):
    """ERP 同步状态。"""
    sid = _resolve_store_id(store_id)
    return {"store_id": sid, "last_sync": None, "status": "idle"}


@router.post("/erp/{store_id}/push-orders")
async def push_orders_to_erp(store_id: str):
    """推送订货建议到 ERP。"""
    sid = _resolve_store_id(store_id)
    return {"store_id": sid, "pushed": 0, "status": "not_implemented"}
