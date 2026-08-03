#!/usr/bin/env python3
"""
Hub 中间件包 — P0-B 统一主 Hub

模块:
- gateway: 强制Gateway中间件 (不可绕过)
- audit_schema: PG 审计表 DDL
"""

from .gateway import (
    HubGatewayMiddleware,
    ActionType,
    RiskLevel,
    AuditRecord,
    PERMISSION_MATRIX,
    CONTROLLED_ENDPOINTS,
    create_hub_gateway,
    get_gateway_stats,
)

__all__ = [
    "HubGatewayMiddleware",
    "ActionType",
    "RiskLevel",
    "AuditRecord",
    "PERMISSION_MATRIX",
    "CONTROLLED_ENDPOINTS",
    "create_hub_gateway",
    "get_gateway_stats",
]
