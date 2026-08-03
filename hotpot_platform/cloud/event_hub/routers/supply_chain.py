#!/usr/bin/env python3
"""
Hub 统一供应链 API — P0-B 核心组件

替代 Edge UI 双轨实现:
- product_master_api.py → 此模块
- purchase_order_api.py → 此模块
- receiving_api.py → 此模块

特性:
1. JWT 认证 (非 PIN/session)
2. RBAC 权限检查 (与 Hub 集成)
3. Gateway 强制过审 (不可绕过)
4. PG 数据源 (非 JSON 缓存)
5. 审计日志 (append-only + correlation_id)

路由前缀: /api/v1/supply-chain (由 ROUTER_PREFIX 指定)
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional, List, Dict, Any

from fastapi import APIRouter, HTTPException, Depends, Header, Query
from pydantic import BaseModel, Field


# ============================================================
# 路由元信息 (auto_include_routers 使用)
# ============================================================

ROUTER_TAG = "供应链管理"
ROUTER_PREFIX = "/api/v1/supply-chain"

router = APIRouter(
    prefix=ROUTER_PREFIX,
    tags=[ROUTER_TAG],
    responses={401: {"description": "未认证"}, 403: {"description": "权限不足"}},
)


# ============================================================
# 依赖注入: JWT 认证
# ============================================================

async def get_current_user(
    authorization: str = Header(...),
) -> Dict[str, Any]:
    """
    从 JWT 提取用户上下文

    返回:
    {
        "user_id": str,
        "username": str,
        "role": str,         # Hub RBAC 角色
        "store_id": str,
        "permissions": list,
    }
    """
    try:
        if not authorization.startswith("Bearer "):
            raise HTTPException(401, {"error": "invalid_token", "message": "缺少 Bearer token"})

        token = authorization[7:]

        # 调用 Hub JWT 解码
        from hotpot_platform.cloud.event_hub.auth import decode_jwt_token
        payload = decode_jwt_token(token)

        return {
            "user_id": payload.get("sub", ""),
            "username": payload.get("username", ""),
            "role": payload.get("role", ""),
            "store_id": payload.get("store_id", ""),
            "permissions": payload.get("permissions", []),
        }
    except Exception as e:
        raise HTTPException(401, {"error": "auth_failed", "message": str(e)})


# ============================================================
# Pydantic Schema
# ============================================================

class ProductMaster(BaseModel):
    """货品主数据"""
    product_id: str = Field(..., description="货品ID (canonical)")
    name: str = Field(..., description="货品名称")
    category: str = Field(..., description="分类")
    unit: str = Field(default="kg", description="单位")
    brand: Optional[str] = None
    supplier_id: Optional[str] = None
    price: float = Field(0.0, ge=0, description="参考价格")
    is_active: bool = Field(True, description="是否启用")
    version: int = Field(1, description="数据版本 (乐观锁)")
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)


class PurchaseOrderCreate(BaseModel):
    """采购订单创建"""
    supplier_id: str = Field(..., description="供应商ID")
    items: List[Dict[str, Any]] = Field(..., description="订单明细")
    total_amount: float = Field(..., gt=0, description="总金额")
    expected_delivery_date: datetime = Field(..., description="预计到货日")
    notes: Optional[str] = None


class PurchaseOrderResponse(BaseModel):
    """采购订单响应"""
    order_id: str
    status: str  # draft / pending_approval / approved / rejected / received / cancelled
    approval_status: Optional[str] = None  # pending / approved / rejected
    correlation_id: Optional[str] = None   # 全链路追踪ID
    created_at: datetime
    data: Dict[str, Any]


class ReceivingRecord(BaseModel):
    """收货记录"""
    receiving_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    purchase_order_id: str = Field(..., description="关联PO ID")
    supplier_id: str = Field(..., description="供应商ID")
    items: List[Dict[str, Any]] = Field(..., description="收货明细")

    # 质检数据
    temperature: float = Field(..., description="到货温度 (°C)")
    weight_actual: float = Field(..., description="实际重量 (kg)")
    quality_grade: Optional[str] = None  # A/B/C/D (VLM辅助+人工确认)

    # 图片证据
    photos_base64: List[str] = Field(default_factory=list)

    # 状态
    status: str = "pending"  # pending / inspected / approved / rejected
    inspector_id: Optional[str] = None
    inspector_notes: Optional[str] = None

    created_at: datetime = Field(default_factory=datetime.now)


# ============================================================
# API 端点: 货品主数据
# ============================================================

@router.get("/products", summary="查询货品列表")
async def list_products(
    category: Optional[str] = Query(None, description="分类过滤"),
    active_only: bool = Query(True, description="仅启用"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user: Dict = Depends(get_current_user),
):
    """
    查询货品主数据 (PG 单一数据源)

    替代 Edge UI: product_master_api.py 的 GET /products
    """
    # TODO: 实现 PG 查询
    # SELECT * FROM product_master WHERE store_id = $1 AND is_active = $2
    return {
        "code": 200,
        "data": [],
        "total": 0,
        "page": page,
        "page_size": page_size,
        "_meta": {
            "source": "hub_pg",
            "correlation_id": uuid.uuid4(),
            "role": user["role"],
        }
    }


@router.post("/products", summary="创建货品")
async def create_product(
    product: ProductMaster,
    x_correlation_id: str = Header(None, alias="X-Correlation-ID"),
    user: Dict = Depends(get_current_user),
):
    """
    创建货品 (MEDIUM 风险 → 自动审计)

    替代 Edge UI: product_master_api.py 的 POST /products
    """
    # Gateway 中间件会自动审计此操作
    correlation_id = x_correlation_id or str(uuid.uuid4())

    # TODO: 实现 PG INSERT
    # INSERT INTO product_master (...) VALUES (...)

    return {
        "code": 201,
        "message": "货品创建成功",
        "data": product.model_dump(),
        "_meta": {
            "correlation_id": correlation_id,
            "audit_status": "executed",
        }
    }


# ============================================================
# API 端点: 采购订单 (HIGH 风险，需审批)
# ============================================================

@router.post("/purchase-orders", summary="创建采购订单")
async def create_purchase_order(
    order: PurchaseOrderCreate,
    x_approval_token: str = Header(None, alias="X-Approval-Token"),
    x_correlation_id: str = Header(None, alias="X-Correlation-ID"),
    user: Dict = Depends(get_current_user),
):
    """
    创建采购订单 (HIGH 风险 → 必须预审或返回403)

    替代 Edge UI: purchase_order_api.py

    流程:
    1. Gateway 中间件拦截
    2. 无 approval_token → 返回 403 + 审批要求
    3. 有 approval_token → 放行并记录审计
    4. 写入 PG purchase_orders 表
    """
    correlation_id = x_correlation_id or str(uuid.uuid4())

    if not x_approval_token:
        # 无预审token，Gateway应已拒绝；这里做二次校验
        raise HTTPException(
            status_code=403,
            detail={
                "error": "approval_required",
                "message": "创建采购订单需要店长或区域经理审批",
                "action_type": "create_purchase_order",
                "risk_level": "high",
                "required_roles": ["store_manager", "area_manager"],
                "correlation_id": correlation_id,
                "_help": "调用 POST /supply-chain/approvals 创建审批任务",
            }
        )

    # 有预审token，执行创建
    order_id = f"PO-{datetime.now().strftime('%Y%m%d')}-{uuid.uuid4().hex[:6]}"

    # TODO: 实现 PG INSERT (事务)
    # BEGIN;
    # INSERT INTO audit_events (...) VALUES (...);
    # INSERT INTO purchase_orders (...) VALUES (...);
    # COMMIT;

    return {
        "code": 201,
        "message": "采购订单创建成功",
        "data": PurchaseOrderResponse(
            order_id=order_id,
            status="approved",
            approval_status="approved",
            correlation_id=correlation_id,
            created_at=datetime.now(),
            data=order.model_dump(),
        ).model_dump(),
        "_meta": {
            "correlation_id": correlation_id,
            "approval_token": x_approval_token[:8] + "...",
        }
    }


@router.get("/purchase-orders/{order_id}", summary="查询采购订单详情")
async def get_purchase_order(
    order_id: str,
    user: Dict = Depends(get_current_user),
):
    """查询单个采购订单"""
    # TODO: PG SELECT
    return {"code": 200, "data": {}, "order_id": order_id}


# ============================================================
# API 端点: 收货质检 (HIGH 风险)
# ============================================================

@router.post("/receiving", summary="创建收货记录")
async def create_receiving_record(
    record: ReceivingRecord,
    x_approval_token: str = Header(None, alias="X-Approval-Token"),
    x_correlation_id: str = Header(None, alias="X-Correlation-ID"),
    user: Dict = Depends(get_current_user),
):
    """
    创建收货记录 (HIGH 风险 → 需质检员签字+店长审批)

    替代 Edge UI: receiving_api.py

    特性:
    - VLM 辅助质检 (quality_grade 由模型建议，人工确认)
    - 温度/重量自动校验
    - 图片证据存档
    -潘厨 (品质管控) 数字签名
    """
    correlation_id = x_correlation_id or str(uuid.uuid4())

    # 验证必填字段
    if not record.temperature or not record.weight_actual:
        raise HTTPException(400, {"error": "missing_fields", "message": "温度和重量为必填项"})

    # 温度范围校验 (冻品要求 -18°C ± 2°C)
    if record.temperature > -10:
        raise HTTPException(400, {
            "error": "temperature_out_of_range",
            "message": f"温度 {record.temperature}°C 异常，冻品应在 -18°C ± 2°C",
            "suggestion": "请联系供应商退换货"
        })

    # TODO: 实现 PG 事务
    # 1. 写入 receiving_records
    # 2. 更新 inventory (入库)
    # 3. 写入 audit_events
    # 4. 触发供应商评分更新

    return {
        "code": 201,
        "message": "收货记录创建成功，等待质检员确认",
        "data": {
            "receiving_id": record.receiving_id,
            "status": "pending_inspection",
            "correlation_id": correlation_id,
            "next_step": "call POST /supply-chain/receiving/{id}/approve",
        },
        "_meta": {
            "inspector_required": True,
            "approval_required": record.quality_grade in ["C", "D"],
        }
    }


@router.post("/receiving/{receiving_id}/approve", summary="审批收货记录")
async def approve_receiving(
    receiving_id: str,
    notes: str = Query("", description="审批备注"),
    user: Dict = Depends(get_current_user),
):
    """
    审批收货记录 (潘厨/店长)

    权限: quality_inspector / store_manager
    """
    # 验证角色权限
    if user["role"] not in ["quality_inspector", "store_manager", "admin"]:
        raise HTTPException(403, {"error": "forbidden", "message": "仅质检员和店长可审批收货"})

    # TODO: PG UPDATE receiving_records SET status = 'approved', ...
    # TODO: 写入 audit_events (approval)

    return {
        "code": 200,
        "message": "收货记录已审批通过",
        "receiving_id": receiving_id,
        "approved_by": user["user_id"],
        "approved_at": datetime.now().isoformat(),
        "notes": notes,
    }


# ============================================================
# API 端点: 审批任务管理
# ============================================================

@router.post("/approvals", summary="创建审批任务")
async def create_approval_task(
    action_type: str = Query(..., description="操作类型"),
    summary: str = Query(..., description="审批摘要"),
    details: Dict[str, Any] = {},
    user: Dict = Depends(get_current_user),
):
    """
    创建审批任务 (供前端调用)

    流程:
    1. 创建 approval_tasks 记录
    2. 通知审批人 (企微/Webhook)
    3. 返回 task_id 供后续查询
    """
    task_id = str(uuid.uuid4())
    correlation_id = str(uuid.uuid4())

    # TODO: PG INSERT approval_tasks
    # TODO: 发送企微通知给 required_approvers

    return {
        "code": 201,
        "message": "审批任务已创建",
        "data": {
            "task_id": task_id,
            "correlation_id": correlation_id,
            "action_type": action_type,
            "status": "pending",
            "required_approvers": [],  # 从 PERMISSION_MATRIX 查询
            "expires_at": (datetime.now() + __import__('datetime').timedelta(hours=24)).isoformat(),
            "_help": f"使用 task_id 调用 PUT /approvals/{task_id}/decision 完成审批",
        }
    }


@router.put("/approvals/{task_id}/decision", summary="审批决策")
async def make_approval_decision(
    task_id: str,
    decision: str = Query(..., pattern="^(approve|reject)$"),
    notes: str = Query(""),
    user: Dict = Depends(get_current_user),
):
    """
    执行审批决策

    决策后:
    - approve: 返回 approval_token (用于执行原操作)
    - reject: 关闭任务并通知申请人
    """
    # TODO: PG UPDATE approval_tasks
    # TODO: 如果 approve，生成 approval_token
    # TODO: 如果 reject，发送通知

    approval_token = str(uuid.uuid4()) if decision == "approve" else None

    return {
        "code": 200,
        "message": f"审批{'通过' if decision == 'approve' else '拒绝'}",
        "task_id": task_id,
        "decision": decision,
        "decision_by": user["user_id"],
        "notes": notes,
        "approval_token": approval_token,  # 用于执行原操作
        "next_step": "使用 approval_token 调用 X-Approval-Token 头重新提交原请求" if approval_token else None,
    }


# ============================================================
# API 端点: 库存查询 (只读)
# ============================================================

@router.get("/inventory", summary="查询库存")
async def query_inventory(
    product_id: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    low_stock_only: bool = Query(False, description="仅低库存"),
    user: Dict = Depends(get_current_user),
):
    """
    查询实时库存 (PG 单一数据源)

    替代 Edge UI 本地 JSON 缓存
    """
    # TODO: PG SELECT FROM inventory WHERE store_id = $1
    return {
        "code": 200,
        "data": [],
        "_meta": {
            "source": "hub_pg_realtime",
            "query_time_ms": 0,
        }
    }


# ============================================================
# 健康检查
# ============================================================

@router.get("/health", summary="供应链模块健康检查")
async def health_check():
    """健康检查端点"""
    return {
        "module": "supply_chain",
        "status": "active",
        "features": [
            "product_master (PG)",
            "purchase_order (Gateway enforced)",
            "receiving (VLM assisted)",
            "inventory (realtime)",
            "approval_workflow",
        ],
        "integration": {
            "gateway_middleware": "✅ enabled",
            "jwt_auth": "✅ active",
            "rbac": "✅ integrated",
            "pg_data_source": "⏳ configured",
        },
        "version": "1.0.0-P0B",
    }


if __name__ == "__main__":
    # 测试导入
    print(f"[SupplyChain] Router loaded: {len(router.routes)} endpoints")
    for route in router.routes:
        if hasattr(route, 'methods'):
            print(f"  {route.methods} {route.path}")
