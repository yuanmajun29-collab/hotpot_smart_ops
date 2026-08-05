"""SC01 供应链场景编排器 — 端到端供应链场景编排。

设计目的：
    - 协调采购、收货、质检、入库的全生命周期
    - 封装 Agent Gateway 调用链路
    - 支持 3 大展会演示场景：端到端采购 / 质量退货 / 紧急补货

Usage:
    orchestrator = SupplyChainScenarioOrchestrator(supply_chain_manager, agent_gateway)
    result = await orchestrator.end_to_end_procurement(store_id="store_yuhuan")
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from .manager import SupplyChainManager
    from ..agent_framework.agent_gateway import AgentGateway

logger = logging.getLogger(__name__)


# ── Enums ────────────────────────────────────────────────────────────────────

class ScenarioStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    AWAITING_APPROVAL = "awaiting_approval"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ScenarioType(str, Enum):
    END_TO_END_PROCUREMENT = "end_to_end_procurement"
    QUALITY_REJECTION = "quality_rejection"
    EMERGENCY_RESTOCK = "emergency_restock"


# ── Data models ──────────────────────────────────────────────────────────────

@dataclass
class ScenarioStep:
    """场景编排中的单步执行记录。"""
    step_id: str
    name: str
    status: str = "pending"  # pending / running / success / failed / skipped
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    result: Optional[dict] = None
    error: Optional[str] = None
    metadata: dict = field(default_factory=dict)


@dataclass
class ScenarioRun:
    """一次场景编排的运行记录。"""
    run_id: str
    scenario_type: ScenarioType
    store_id: str
    status: ScenarioStatus = ScenarioStatus.PENDING
    steps: list[ScenarioStep] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    completed_at: Optional[str] = None
    final_result: Optional[dict] = None
    error: Optional[str] = None


# ── Orchestrator ─────────────────────────────────────────────────────────────

class SupplyChainScenarioOrchestrator:
    """供应链场景编排器。

    负责端到端编排供应链场景，将单个 API 调用组装为完整的业务流程。
    每个场景定义为一系列有序的 Step，每个 Step 携带 Agent Gateway 审批信息。
    """

    def __init__(
        self,
        supply_chain_manager: "SupplyChainManager",
        agent_gateway: Optional["AgentGateway"] = None,
    ) -> None:
        self.scm = supply_chain_manager
        self.gateway = agent_gateway
        self._runs: dict[str, ScenarioRun] = {}

    # ── Scenario 1: 端到端采购流程 ────────────────────────────────────────

    async def end_to_end_procurement(
        self,
        store_id: str,
        sku_list: Optional[list[str]] = None,
        *,
        skip_approval: bool = False,
    ) -> ScenarioRun:
        """端到端采购流程：预测建议 → 审批 → 下单 → 收货 → 质检 → 入库。

        展会 Demo 核心场景，展示 AI 驱动的全链路采购闭环。
        """
        run = self._create_run(ScenarioType.END_TO_END_PROCUREMENT, store_id)
        run.status = ScenarioStatus.RUNNING

        # Step 1: 销售预测 → 采购建议
        step1 = self._start_step(run, "forecast_procurement_suggestion")
        try:
            suggestion = self.scm.generate_procurement_suggestion(store_id)
            if not suggestion or not suggestion.get("items"):
                raise ValueError("No items in procurement suggestion")
            step1.result = suggestion
            self._complete_step(step1, "success")
        except Exception as e:
            self._complete_step(step1, "failed", error=str(e))
            self._fail_run(run, str(e))
            return run

        # Step 2: 审批确认（走 Agent Gateway）
        step2 = self._start_step(run, "approve_procurement")
        if skip_approval:
            step2.status = "skipped"
            step2.result = {"approved": True, "approver": "auto_skip"}
        else:
            try:
                approved = await self._gateway_approve(
                    "PO_CREATE",
                    context={"store_id": store_id, "suggestion": suggestion},
                    risk_level="medium",
                )
                step2.result = approved
                self._complete_step(step2, "success" if approved.get("approved") else "failed",
                                    error=None if approved.get("approved") else "Approval denied")
                if not approved.get("approved"):
                    self._fail_run(run, "Procurement not approved")
                    return run
            except Exception as e:
                self._complete_step(step2, "failed", error=str(e))
                self._fail_run(run, str(e))
                return run

        # Step 3: 创建采购订单
        step3 = self._start_step(run, "create_purchase_order")
        try:
            po = self.scm.create_purchase_order(
                store_id=store_id,
                items=suggestion.get("items", []),
                creator="scenario_orchestrator",
            )
            step3.result = {"po_id": po.get("po_id"), "status": po.get("status")}
            self._complete_step(step3, "success")
        except Exception as e:
            self._complete_step(step3, "failed", error=str(e))
            self._fail_run(run, str(e))
            return run

        # Step 4: 模拟收货（触发质检）
        step4 = self._start_step(run, "receive_and_inspect")
        try:
            po_id = step3.result.get("po_id", "")
            receive_result = self.scm.receive_purchase_order(
                po_id=po_id,
                store_id=store_id,
                zone="收货区",
            )
            step4.result = receive_result
            self._complete_step(step4, "success")
        except Exception as e:
            self._complete_step(step4, "failed", error=str(e))
            self._fail_run(run, str(e))
            return run

        # Step 5: 入库确认
        step5 = self._start_step(run, "confirm_inventory")
        try:
            inventory_result = self.scm.confirm_inventory_receipt(
                store_id=store_id,
                po_id=step3.result.get("po_id", ""),
            )
            step5.result = inventory_result
            self._complete_step(step5, "success")
        except Exception as e:
            self._complete_step(step5, "failed", error=str(e))
            # 入库失败不阻断整体流程
            pass

        # Success
        run.status = ScenarioStatus.COMPLETED
        run.completed_at = datetime.now(timezone.utc).isoformat()
        run.final_result = {
            "po_id": step3.result.get("po_id", "") if step3.result else "",
            "passed_quality": step4.result.get("quality_pass", False) if step4.result else False,
            "steps_completed": sum(1 for s in run.steps if s.status == "success"),
            "steps_total": len(run.steps),
        }
        logger.info(f"[SC01] end_to_end_procurement completed: {run.final_result}")
        return run

    # ── Scenario 2: 质量退货流程 ──────────────────────────────────────────

    async def quality_rejection(
        self,
        store_id: str,
        po_id: str,
        *,
        rejection_reason: str = "",
    ) -> ScenarioRun:
        """质量退货流程：质检不合格 → 发起退货 → 供应商通知 → 替换订单。

        展会展示 AI 在品质异常时的闭环处理能力。
        """
        run = self._create_run(ScenarioType.QUALITY_REJECTION, store_id)
        run.status = ScenarioStatus.RUNNING

        # Step 1: 触发质量检查
        step1 = self._start_step(run, "quality_check")
        try:
            quality_result = self.scm.inspect_received_goods(
                po_id=po_id, store_id=store_id
            )
            step1.result = quality_result
            if quality_result.get("pass_check", True):
                run.status = ScenarioStatus.COMPLETED
                run.final_result = {"action": "quality_passed", "reason": "No rejection needed"}
                return run
            self._complete_step(step1, "success")
        except Exception as e:
            self._complete_step(step1, "failed", error=str(e))
            self._fail_run(run, str(e))
            return run

        # Step 2: 发起退货审批
        step2 = self._start_step(run, "rejection_approval")
        try:
            approved = await self._gateway_approve(
                "RETURN_ORDER",
                context={
                    "store_id": store_id,
                    "po_id": po_id,
                    "quality_result": step1.result,
                    "reason": rejection_reason or "品质不达标，自动检测不合格",
                },
                risk_level="high",
            )
            step2.result = approved
            if not approved.get("approved"):
                self._complete_step(step2, "failed", error="Return request denied")
                self._fail_run(run, "Return request denied")
                return run
            self._complete_step(step2, "success")
        except Exception as e:
            self._complete_step(step2, "failed", error=str(e))
            self._fail_run(run, str(e))
            return run

        # Step 3: 创建退货单
        step3 = self._start_step(run, "create_return_order")
        try:
            return_order = self.scm.create_return_order(
                po_id=po_id,
                store_id=store_id,
                reason=rejection_reason or "品质不达标",
            )
            step3.result = return_order
            self._complete_step(step3, "success")
        except Exception as e:
            self._complete_step(step3, "failed", error=str(e))
            self._fail_run(run, str(e))
            return run

        # Step 4: 创建替换订单
        step4 = self._start_step(run, "create_replacement_order")
        try:
            replacement = self.scm.create_replacement_order(
                po_id=po_id,
                store_id=store_id,
                return_order_id=step3.result.get("return_id", ""),
            )
            step4.result = replacement
            self._complete_step(step4, "success")
        except Exception as e:
            self._complete_step(step4, "failed", error=str(e))
            # 替换订单失败不阻断整体流程
            pass

        run.status = ScenarioStatus.COMPLETED
        run.completed_at = datetime.now(timezone.utc).isoformat()
        run.final_result = {
            "po_id": po_id,
            "return_order_id": step3.result.get("return_id", "") if step3.result else "",
            "replacement_po_id": step4.result.get("po_id", "") if step4.result else "",
            "quality_grade": step1.result.get("overall_grade", "D"),
        }
        return run

    # ── Scenario 3: 紧急补货流程 ──────────────────────────────────────────

    async def emergency_restock(
        self,
        store_id: str,
        alert: dict,
    ) -> ScenarioRun:
        """紧急补货流程：低库存告警 → 快速下单 → 加急配送。

        展会演示 AI 对突发库存短缺的快速响应。
        """
        run = self._create_run(ScenarioType.EMERGENCY_RESTOCK, store_id)
        run.status = ScenarioStatus.RUNNING

        # Step 1: 验证告警并生成补货清单
        step1 = self._start_step(run, "validate_and_generate_restock")
        try:
            restock_items = self.scm.generate_emergency_restock(
                store_id=store_id,
                alert_items=alert.get("items", []),
            )
            if not restock_items or not restock_items.get("items"):
                raise ValueError("No restock items generated")
            step1.result = restock_items
            self._complete_step(step1, "success")
        except Exception as e:
            self._complete_step(step1, "failed", error=str(e))
            self._fail_run(run, str(e))
            return run

        # Step 2: 紧急审批（快速通道）
        step2 = self._start_step(run, "emergency_approval")
        try:
            approved = await self._gateway_approve(
                "EMERGENCY_PO",
                context={
                    "store_id": store_id,
                    "alert": alert,
                    "restock_items": step1.result,
                },
                risk_level="high",
                urgent=True,
            )
            step2.result = approved
            if not approved.get("approved"):
                self._complete_step(step2, "failed", error="Emergency restock denied")
                self._fail_run(run, "Emergency restock denied")
                return run
            self._complete_step(step2, "success")
        except Exception as e:
            self._complete_step(step2, "failed", error=str(e))
            self._fail_run(run, str(e))
            return run

        # Step 3: 创建紧急订单（加急标记）
        step3 = self._start_step(run, "create_emergency_po")
        try:
            emergency_po = self.scm.create_emergency_purchase_order(
                store_id=store_id,
                items=step1.result.get("items", []),
                urgency="high",
            )
            step3.result = emergency_po
            self._complete_step(step3, "success")
        except Exception as e:
            self._complete_step(step3, "failed", error=str(e))
            self._fail_run(run, str(e))
            return run

        run.status = ScenarioStatus.COMPLETED
        run.completed_at = datetime.now(timezone.utc).isoformat()
        run.final_result = {
            "emergency_po_id": step3.result.get("po_id", "") if step3.result else "",
            "reason": alert.get("reason", "库存紧急不足"),
            "items_count": len(step1.result.get("items", [])),
        }
        return run

    # ── Run management ────────────────────────────────────────────────────

    def get_run(self, run_id: str) -> Optional[ScenarioRun]:
        """获取指定运行记录。"""
        return self._runs.get(run_id)

    def get_store_runs(self, store_id: str) -> list[ScenarioRun]:
        """获取某门店的所有运行记录。"""
        return [r for r in self._runs.values() if r.store_id == store_id]

    # ── Internal helpers ──────────────────────────────────────────────────

    def _create_run(self, scenario_type: ScenarioType, store_id: str) -> ScenarioRun:
        run_id = f"{scenario_type.value}_{datetime.now().strftime('%Y%m%d%H%M%S%f')[:-3]}"
        run = ScenarioRun(run_id=run_id, scenario_type=scenario_type, store_id=store_id)
        self._runs[run_id] = run
        return run

    def _start_step(self, run: ScenarioRun, name: str) -> ScenarioStep:
        step = ScenarioStep(
            step_id=f"{run.run_id}_{name}",
            name=name,
            status="running",
            started_at=datetime.now(timezone.utc).isoformat(),
        )
        run.steps.append(step)
        return step

    def _complete_step(
        self, step: ScenarioStep, status: str, *, result: Optional[dict] = None, error: Optional[str] = None
    ) -> None:
        step.status = status
        step.completed_at = datetime.now(timezone.utc).isoformat()
        if result is not None:
            step.result = result
        if error:
            step.error = error

    def _fail_run(self, run: ScenarioRun, error: str) -> None:
        run.status = ScenarioStatus.FAILED
        run.completed_at = datetime.now(timezone.utc).isoformat()
        run.error = error
        logger.error(f"[SC01] Scenario {run.run_id} failed: {error}")

    async def _gateway_approve(
        self,
        action_type: str,
        context: dict,
        risk_level: str = "medium",
        urgent: bool = False,
    ) -> dict:
        """通过 Agent Gateway 发送审批请求。

        如果 Gateway 不可用，返回默认通过（demo 容错模式）。
        """
        if self.gateway is None:
            logger.warning(f"[SC01] No AgentGateway configured, auto-approving {action_type}")
            return {"approved": True, "approver": "auto_fallback", "gateway_unavailable": True}

        try:
            result = await self.gateway.execute_action(
                action_type=action_type,
                context=context,
                risk_level=risk_level,
                urgent=urgent,
            )
            return result
        except Exception as e:
            logger.error(f"[SC01] Gateway approval failed for {action_type}: {e}")
            # Demo 容错：Gateway 不可用时默认通过
            return {"approved": True, "approver": "auto_fallback", "error": str(e)}
