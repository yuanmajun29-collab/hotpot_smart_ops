#!/usr/bin/env python3
"""
火瞳 · P0-C Demo 数据种子生成器
==============================

预置完整的采购闭环示例数据，用于：
1. 展会演示 (2026-10重庆展会)
2. 前端开发调试
3. 端到端测试

包含3个典型场景:
  例1: 正常流程 (建议→审批→PO→收货) ✅
  例2: 审批拒绝流程 ❌
  例3: 质检异常流程(D级品) ⚠️

使用方式:
    # 生成所有Demo数据
    python scripts/seed_demo_data.py --all

    # 仅生成正常流程
    python scripts/seed_demo_data.py --scenario normal

    # 输出JSON格式 (供前端使用)
    python scripts/seed_demo_data.py --format json > demo_trace.json

作者: 火瞳AI团队
日期: 2026-08-03 (P0-C Phase 4)
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional

# 导入PurchaseCycle组件
sys.path.insert(0, '.')
from hotpot_platform.cloud.event_hub.routers.purchase_cycle import (
    PurchaseCycle,
    SuggestionData,
    ApprovalTaskData,
    PurchaseOrderData,
    ReceivingRecordData,
    AuditEventData,
    CyclePhase,
    CycleStatus,
    create_purchase_cycle,
)
from hotpot_platform.cloud.agent_framework.action_types import ActionType, RiskLevel


class DemoDataGenerator:
    """Demo数据生成器"""

    def __init__(self):
        self.scenarios = {}

    def generate_scenario_1_normal(self) -> Dict[str, Any]:
        """
        场景1: 正常完整流程
        AI建议 → 审批通过 → PO创建 → 收货质检(A级) → 完成
        """
        correlation_id = f"DEMO-NORMAL-{datetime.now().strftime('%Y%m%d-%H%M%S')}"

        scenario = {
            "scenario_id": "SCENARIO-001",
            "scenario_name": "正常采购流程",
            "description": "完整的4环节闭环，所有步骤顺利通过",
            "correlation_id": correlation_id,
            "status": CycleStatus.COMPLETED.value,

            # 环节1: AI建议
            "suggestion": {
                "suggestion_id": "SUG-NORMAL-001",
                "correlation_id": correlation_id,
                "store_id": "store_jiaojiang",
                "created_at": (datetime.now() - timedelta(days=3)).isoformat(),
                "created_by": "ai_system",
                "status": "accepted",
                "items": [
                    {"sku_code": "FP-HNRC-001", "name": "汉拿山肥牛卷", "qty": 20, "unit_price": 68.0, "unit": "kg"},
                    {"sku_code": "FP-HNRC-002", "name": "精品羊肉卷", "qty": 15, "unit_price": 78.0, "unit": "kg"},
                    {"sku_code": "FP-HNRC-003", "name": "虾滑", "qty": 10, "unit_price": 45.0, "unit": "kg"},
                ],
                "total_amount": 2690.0 + 1170.0 + 450.0,  # 4310.0
                "priority": "normal",
                "reason": "库存低于安全水位，预计3天后耗尽。基于近7天销售预测。",
                "confidence_score": 0.92,
                "ai_model_version": "hotpot-v1.0-purchase",
                "data_sources": ["inventory", "sales_forecast", "seasonal_trend"],
            },

            # 环节2: 审批
            "approval": {
                "task_id": "APV-NORMAL-001",
                "correlation_id": correlation_id,
                "suggestion_id": "SUG-NORMAL-001",
                "action_type": ActionType.APPROVE_PURCHASE.value,
                "risk_level": RiskLevel.HIGH.value,
                "status": "approved",
                "created_at": (datetime.now() - timedelta(days=3, hours=1)).isoformat(),
                "created_by": "purchaser_zhangsan",
                "assigned_to": "purchaser",
                "required_approvers": ["purchaser"],
                "summary": "采购审批: 汉拿山肥牛卷等3项，总金额¥4310.00",
                "details": {},
                "decided_at": (datetime.now() - timedelta(days=3, hours=2)).isoformat(),
                "decided_by": "purchaser_lisi",
                "decision": "approve",
                "decision_notes": "同意补货，供应商价格合理，库存确实偏低",
                "approval_token": f"TOKEN-NORMAL-{uuid_short()}",
                "expires_at": (datetime.now() + timedelta(days=21)).isoformat(),
            },

            # 环节3: PO创建
            "purchase_order": {
                "order_id": f"PO-{(datetime.now() - timedelta(days=3)).strftime('%Y%m%d')}-NORMAL01",
                "correlation_id": correlation_id,
                "approval_task_id": "APV-NORMAL-001",
                "suggestion_id": "SUG-NORMAL-001",
                "status": "received",  # 已收货
                "created_at": (datetime.now() - timedelta(days=3, hours=2, minutes=5)).isoformat(),
                "created_by": "system",
                "supplier_id": "SUPPLIER-CHONGQING-001",
                "supplier_name": "重庆冻品供应链有限公司",
                "items": [
                    {"product_id": "FP-HNRC-001", "name": "汉拿山肥牛卷", "qty": 20, "unit_price": 68.0},
                    {"product_id": "FP-HNRC-002", "name": "精品羊肉卷", "qty": 15, "unit_price": 78.0},
                    {"product_id": "FP-HNRC-003", "name": "虾滑", "qty": 10, "unit_price": 45.0},
                ],
                "total_amount": 4310.0,
                "currency": "CNY",
                "expected_delivery_date": (datetime.now() - timedelta(days=1)).isoformat(),
                "actual_delivery_date": (datetime.now() - timedelta(days=1)).isoformat(),
                "approved_by": "purchaser_lisi",
                "approved_at": (datetime.now() - timedelta(days=3, hours=2, minutes=5)).isoformat(),
                "receiving_id": "RCV-NORMAL-001",
                "receiving_status": "approved",
                "notes": "常规补货订单",
            },

            # 环节4: 收货确认
            "receiving": {
                "receiving_id": "RCV-NORMAL-001",
                "correlation_id": correlation_id,
                "purchase_order_id": f"PO-{(datetime.now() - timedelta(days=3)).strftime('%Y%m%d')}-NORMAL01",
                "status": "approved",
                "created_at": (datetime.now() - timedelta(days=1, hours=10)).isoformat(),
                "created_by": "inspector_panchu",
                "supplier_id": "SUPPLIER-CHONGQING-001",
                "supplier_name": "重庆冻品供应链有限公司",
                "items": [
                    {"product_id": "FP-HNRC-001", "name": "汉拿山肥牛卷", "qty_received": 20, "qty_expected": 20},
                    {"product_id": "FP-HNRC-002", "name": "精品羊肉卷", "qty_received": 15, "qty_expected": 15},
                    {"product_id": "FP-HNRC-003", "name": "虾滑", "qty_received": 10, "qty_expected": 10},
                ],
                "temperature": -18.5,  # ✅ 正常
                "weight_expected": 45.0,
                "weight_actual": 44.8,  # 轻微误差(-0.4%)
                "quality_grade": "A",  # ✅ A级
                "quality_notes": "包装完好，温度达标，无化冻迹象",
                "inspector_id": "inspector_panchu",
                "inspector_name": "潘厨",
                "inspected_at": (datetime.now() - timedelta(days=1, hours=10)).isoformat(),
                "inspector_notes": "质量优秀，建议继续合作",
                "approver_id": "store_manager_wang",
                "approved_at": (datetime.now() - timedelta(days=1, hours=11)).isoformat(),
                "approval_notes": "确认收货，入库完成",
            },

            # 时间线
            "timeline": [
                {"phase": "suggestion", "phase_label": "AI采购建议", "timestamp": (datetime.now() - timedelta(days=3)).isoformat(), "actor": "ai_system", "action": "生成采购建议 (3项, ¥4310.00)", "icon": "🤖", "color": "#378ADD", "status": "accepted"},
                {"phase": "approval", "phase_label": "人工审批", "timestamp": (datetime.now() - timedelta(days=3, hours=1)).isoformat(), "actor": "purchaser_zhangsan", "action": "创建审批任务", "icon": "📝", "color": "#BA7517", "status": "pending"},
                {"phase": "approval", "phase_label": "审批决策", "timestamp": (datetime.now() - timedelta(days=3, hours=2)).isoformat(), "actor": "purchaser_lisi", "action": "✅ 审批通过", "icon": "✓", "color": "#639922", "status": "approved"},
                {"phase": "purchase_order", "phase_label": "PO创建", "timestamp": (datetime.now() - timedelta(days=3, hours=2, minutes=5)).isoformat(), "actor": "system", "action": "创建采购订单 PO-20260801-NORMAL01 (¥4310.00)", "icon": "📋", "color": "#639922", "status": "approved"},
                {"phase": "receiving", "phase_label": "收货确认", "timestamp": (datetime.now() - timedelta(days=1, hours=10)).isoformat(), "actor": "潘厨", "action": "收货质检 (等级:A, 温度:-18.5°C)", "icon": "📦", "color": "#639922", "status": "inspected"},
                {"phase": "receiving", "phase_label": "收货审批", "timestamp": (datetime.now() - timedelta(days=1, hours=11)).isoformat(), "actor": "store_manager_wang", "action": "店长审批通过，入库完成", "icon": "✓", "color": "#639922", "status": "completed"},
            ],

            # 统计
            "statistics": {
                "total_phases": 4,
                "completed_phases": 4,
                "total_audit_events": 6,
                "total_duration_hours": 53.25,  # 约2.2天
                "adr_compliant": True,
            },
        }

        self.scenarios["normal"] = scenario
        return scenario

    def generate_scenario_2_rejected(self) -> Dict[str, Any]:
        """
        场景2: 审批拒绝流程
        AI建议 → 审批拒绝 → 流程终止
        """
        correlation_id = f"DEMO-REJECTED-{datetime.now().strftime('%Y%m%d-%H%M%S')}"

        scenario = {
            "scenario_id": "SCENARIO-002",
            "scenario_name": "审批拒绝流程",
            "description": "采购建议被审批人拒绝，展示异常处理流程",
            "correlation_id": correlation_id,
            "status": CycleStatus.REJECTED.value,

            "suggestion": {
                "suggestion_id": "SUG-REJECTED-001",
                "correlation_id": correlation_id,
                "store_id": "store_jiaojiang",
                "created_at": (datetime.now() - timedelta(hours=6)).isoformat(),
                "created_by": "ai_system",
                "status": "rejected",
                "items": [
                    {"sku_code": "FP-LUXURY-001", "name": "澳洲和牛", "qty": 5, "unit_price": 280.0, "unit": "kg"},
                ],
                "total_amount": 1400.0,
                "priority": "low",
                "reason": "高端产品推荐，可提升门店档次",
                "confidence_score": 0.65,
                "ai_model_version": "hotpot-v1.0-purchase",
                "data_sources": ["market_analysis", "competitor_research"],
            },

            "approval": {
                "task_id": "APV-REJECTED-001",
                "correlation_id": correlation_id,
                "suggestion_id": "SUG-REJECTED-001",
                "action_type": ActionType.APPROVE_PURCHASE.value,
                "risk_level": RiskLevel.HIGH.value,
                "status": "rejected",
                "created_at": (datetime.now() - timedelta(hours=5)).isoformat(),
                "created_by": "purchaser_zhangsan",
                "assigned_to": "store_manager",
                "required_approvers": ["store_manager"],
                "summary": "采购审批: 澳洲和牛5kg，总金额¥1400.00（高单价）",
                "details": {},
                "decided_at": (datetime.now() - timedelta(hours=4)).isoformat(),
                "decided_by": "store_manager_wang",
                "decision": "reject",
                "decision_notes": "当前门店定位不需要如此高价产品，且库存周转率低。建议暂不采购。",
                "approval_token": None,
                "expires_at": (datetime.now() + timedelta(hours=19)).isoformat(),
            },

            "purchase_order": None,
            "receiving": None,

            "timeline": [
                {"phase": "suggestion", "phase_label": "AI采购建议", "timestamp": (datetime.now() - timedelta(hours=6)).isoformat(), "actor": "ai_system", "action": "生成采购建议 (1项, ¥1400.00)", "icon": "🤖", "color": "#378ADD", "status": "rejected"},
                {"phase": "approval", "phase_label": "人工审批", "timestamp": (datetime.now() - timedelta(hours=5)).isoformat(), "actor": "purchaser_zhangsan", "action": "创建审批任务（需店长审批）", "icon": "📝", "color": "#BA7517", "status": "pending"},
                {"phase": "approval", "phase_label": "审批决策", "timestamp": (datetime.now() - timedelta(hours=4)).isoformat(), "actor": "store_manager_wang", "action": "❌ 审批拒绝", "icon": "✗", "color": "#E24B4A", "status": "rejected"},
            ],

            "statistics": {
                "total_phases": 2,  # 仅完成前2个环节
                "completed_phases": 2,
                "total_audit_events": 3,
                "total_duration_hours": 2.0,
                "adr_compliant": True,  # 即使拒绝也合规（未自动创建PO）
            },
        }

        self.scenarios["rejected"] = scenario
        return scenario

    def generate_scenario_3_quality_issue(self) -> Dict[str, Any]:
        """
        场景3: 质检异常流程 (D级品)
        AI建议 → 审批 → PO → 收货(D级) → 店长二次审批 → 退换货
        """
        correlation_id = f"DEMO-QUALITY-{datetime.now().strftime('%Y%m%d-%H%M%S')}"

        scenario = {
            "scenario_id": "SCENARIO-003",
            "scenario_name": "质检异常流程",
            "description": "收货时发现D级质量问题，触发店长二次审批和退换货流程",
            "correlation_id": correlation_id,
            "status": CycleStatus.COMPLETED.value,  # 最终完成(退换货)

            "suggestion": {
                "suggestion_id": "SUG-QUALITY-001",
                "correlation_id": correlation_id,
                "store_id": "store_jiaojiang",
                "created_at": (datetime.now() - timedelta(days=5)).isoformat(),
                "created_by": "ai_system",
                "status": "accepted",
                "items": [
                    {"sku_code": "FP-HNRC-004", "name": "毛肚", "qty": 8, "unit_price": 55.0, "unit": "kg"},
                ],
                "total_amount": 440.0,
                "priority": "urgent",
                "reason": "毛肚库存告急，仅剩2天用量",
                "confidence_score": 0.95,
                "ai_model_version": "hotpot-v1.0-purchase",
                "data_sources": ["inventory_alert"],
            },

            "approval": {
                "task_id": "APV-QUALITY-001",
                "correlation_id": correlation_id,
                "suggestion_id": "SUG-QUALITY-001",
                "action_type": ActionType.APPROVE_PURCHASE.value,
                "risk_level": RiskLevel.HIGH.value,
                "status": "approved",
                "created_at": (datetime.now() - timedelta(days=5, hours=1)).isoformat(),
                "created_by": "purchaser_zhangsan",
                "assigned_to": "purchaser",
                "required_approvers": ["purchaser"],
                "summary": "紧急采购: 毛肚8kg，¥440.00",
                "details": {"urgency": "high", "reason": "库存告急"},
                "decided_at": (datetime.now() - timedelta(days=5, hours=1, minutes=10)).isoformat(),
                "decided_by": "purchaser_lisi",
                "decision": "approve",
                "decision_notes": "紧急补货，立即批准",
                "approval_token": f"TOKEN-QUALITY-{uuid_short()}",
                "expires_at": (datetime.now() + timedelta(days=19)).isoformat(),
            },

            "purchase_order": {
                "order_id": f"PO-{(datetime.now() - timedelta(days=5)).strftime('%Y%m%d')}-QUAL01",
                "correlation_id": correlation_id,
                "approval_task_id": "APV-QUALITY-001",
                "suggestion_id": "SUG-QUALITY-001",
                "status": "received",
                "created_at": (datetime.now() - timedelta(days=5, hours=1, minutes=15)).isoformat(),
                "created_by": "system",
                "supplier_id": "SUPPLIER-CHENGDU-002",
                "supplier_name": "成都鲜毛肚专供",
                "items": [
                    {"product_id": "FP-HNRC-004", "name": "毛肚", "qty": 8, "unit_price": 55.0},
                ],
                "total_amount": 440.0,
                "expected_delivery_date": (datetime.now() - timedelta(days=2)).isoformat(),
                "actual_delivery_date": (datetime.now() - timedelta(days=2)).isoformat(),
                "approved_by": "purchaser_lisi",
                "approved_at": (datetime.now() - timedelta(days=5, hours=1, minutes=15)).isoformat(),
                "receiving_id": "RCV-QUALITY-001",
                "receiving_status": "approved",
                "notes": "紧急补货订单",
            },

            "receiving": {
                "receiving_id": "RCV-QUALITY-001",
                "correlation_id": correlation_id,
                "purchase_order_id": f"PO-{(datetime.now() - timedelta(days=5)).strftime('%Y%m%d')}-QUAL01",
                "status": "approved",  # 最终审批通过(但做了退换货处理)
                "created_at": (datetime.now() - timedelta(days=2, hours=9)).isoformat(),
                "created_by": "inspector_panchu",
                "supplier_id": "SUPPLIER-CHENGDU-002",
                "supplier_name": "成都鲜毛肚专供",
                "items": [
                    {"product_id": "FP-HNRC-004", "name": "毛肚", "qty_received": 8, "qty_expected": 8},
                ],
                "temperature: -8.5,  # ⚠️ 异常！温度过高
                "weight_expected": 8.0,
                "weight_actual": 7.5,  # ⚠️ 重量不足
                "quality_grade": "D",  # ⚠️ D级！严重质量问题的
                "quality_notes": "包装有化冻迹象，毛肚颜色偏暗，有异味，疑似运输途中脱冷",
                "photos_base64": [],  # 应包含问题照片
                "inspector_id": "inspector_panchu",
                "inspector_name": "潘厨",
                "inspected_at": (datetime.now() - timedelta(days=2, hours=9)).isoformat(),
                "inspector_notes": "⚠️ 严重质量问题！建议拒收或退换货",
                "approver_id": "store_manager_wang",
                "approved_at": (datetime.now() - timedelta(days=2, hours=10)).isoformat(),
                "approval_notes": "同意潘厨判断，已联系供应商退换货。扣减供应商评分。",
            },

            "timeline": [
                {"phase": "suggestion", "phase_label": "AI采购建议", "timestamp": (datetime.now() - timedelta(days=5)).isoformat(), "actor": "ai_system", "action": "⚡ 紧急采购建议 (毛肚8kg, ¥440.00)", "icon": "🤖", "color": "#378ADD", "status": "accepted"},
                {"phase": "approval", "phase_label": "人工审批", "timestamp": (datetime.now() - timedelta(days=5, hours=1)).isoformat(), "actor": "purchaser_zhangsan", "action": "创建审批任务", "icon": "📝", "color": "#BA7517", "status": "pending"},
                {"phase": "approval", "phase_label": "审批决策", "timestamp": (datetime.now() - timedelta(days=5, hours=1, minutes=10)).isoformat(), "actor": "purchaser_lisi", "action": "✅ 紧急批准", "icon": "✓", "color": "#639922", "status": "approved"},
                {"phase": "purchase_order", "phase_label": "PO创建", "timestamp": (datetime.now() - timedelta(days=5, hours=1, minutes=15)).isoformat(), "actor": "system", "action": "创建紧急采购订单", "icon": "📋", "color": "#639922", "status": "approved"},
                {"phase": "receiving", "phase_label": "收货确认", "timestamp": (datetime.now() - timedelta(days=2, hours=9)).isoformat(), "actor": "潘厨", "action": "⚠️ 收货质检 (等级:D, 温度:-8.5°C异常!)", "icon": "📦", "color": "#E24B4A", "status": "pending_approval"},
                {"phase": "receiving", "phase_label": "收货审批+退换货", "timestamp": (datetime.now() - timedelta(days=2, hours=10)).isoformat(), "actor": "store_manager_wang", "action": "店长审批: 同意退换货，扣分供应商", "icon": "✓", "color": "#E24B4A", "status": "completed"},
            ],

            "statistics": {
                "total_phases": 4,
                "completed_phases": 4,
                "total_audit_events": 7,
                "total_duration_hours": 71.0,  # 约3天
                "adr_compliant": True,
                "quality_issues": 1,  # 1个质量问题
                "supplier_penalty": True,  # 供应商被扣分
            },
        }

        self.scenarios["quality_issue"] = scenario
        return scenario

    def generate_all(self) -> Dict[str, Dict[str, Any]]:
        """生成所有场景"""
        print("[DemoData] 生成场景1: 正常流程...")
        self.generate_scenario_1_normal()

        print("[DemoData] 生成场景2: 审批拒绝...")
        self.generate_scenario_2_rejected()

        print("[DemoData] 生成场景3: 质检异常...")
        self.generate_scenario_3_quality_issue()

        return self.scenarios


def uuid_short() -> str:
    """生成短UUID"""
    import uuid
    return uuid.uuid4().hex[:8].upper()


def main():
    parser = argparse.ArgumentParser(description='P0-C Demo数据种子生成器')
    parser.add_argument('--all', action='store_true', help='生成所有场景')
    parser.add_argument('--scenario', choices=['normal', 'rejected', 'quality_issue'], help='指定单个场景')
    parser.add_argument('--format', choices=['json', 'dict'], default='dict', help='输出格式')

    args = parser.parse_args()

    generator = DemoDataGenerator()

    if args.all:
        scenarios = generator.generate_all()
    elif args.scenario:
        method_map = {
            'normal': generator.generate_scenario_1_normal,
            'rejected': generator.generate_scenario_2_rejected,
            'quality_issue': generator.generate_scenario_3_quality_issue,
        }
        scenario = method_map[args.scenario]()
        scenarios = {args.scenario: scenario}
    else:
        # 默认生成正常流程
        scenario = generator.generate_scenario_1_normal()
        scenarios = {'normal': scenario}

    # 输出结果
    if args.format == 'json':
        print(json.dumps(scenarios, ensure_ascii=False, indent=2))
    else:
        for name, data in scenarios.items():
            print(f"\n{'='*60}")
            print(f"📋 场景: {data['scenario_name']}")
            print(f"   ID: {data['scenario_id']}")
            print(f"   correlation_id: {data['correlation_id']}")
            print(f"   状态: {data['status']}")
            print(f"   统计: {data['statistics']}")
            print(f"   时间线节点: {len(data.get('timeline', []))}个")
            print(f"{'='*60}")


if __name__ == "__main__":
    main()
