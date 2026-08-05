#!/usr/bin/env python3
"""火瞳 · Agent 跨角色协作场景 (D2-04)

实现三类预定义的多Agent协作流程:
1. WasteToPurchaseOrchestration: 废料检测 → 智能采购建议 → 店长审批
2. TableServiceLoop: 脏桌视觉检测 → 清台任务 → 服务KPI闭环
3. SOpViolationTrainingLoop: SOP违规检测 → 培训生成 → 班后复盘关联

每个场景类提供:
- orchestrate(input_data): 主入口方法
- get_pipeline_steps(): 返回步骤描述列表（用于UI展示）
- get_current_status(): 返回当前执行状态

作者: 火瞳AI团队
日期: 2026-08-05 (D2优化: 跨角色协作落地)
"""

from __future__ import annotations

import logging
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────
# 协作状态枚举
# ──────────────────────────────────────────────────────────────

class OrchestrationStatus(str, Enum):
    """协作流程状态"""
    PENDING = "pending"
    RUNNING = "running"
    STEP_COMPLETED = "step_completed"
    COMPLETED = "completed"
    FAILED = "failed"
    PARTIAL_SUCCESS = "partial_success"


# ──────────────────────────────────────────────────────────────
# 场景1: 废料→采购→审批 (三Agent协作)
# ──────────────────────────────────────────────────────────────

class WasteToPurchaseOrchestration:
    """废料检测触发智能采购建议 → 店长审批完整流程

    协作链路:
    KitchenAgent.analyze_waste() → ProcurementAgent.generate_purchase_suggestion()
    → StoreManagerAgent.approve_task() → KPI回写

    适用场景:
    - 后厨废料超标自动触发采购调整建议
    - VLM视觉识别到异常废料时联动采购补货
    - 损耗率预警触发的智能补货流程
    """

    def __init__(self):
        self._status = OrchestrationStatus.PENDING
        self._current_step = 0
        self._results: Dict[str, Any] = {}
        self._errors: List[str] = []
        self._started_at: Optional[datetime] = None
        self._completed_at: Optional[datetime] = None

    def get_pipeline_steps(self) -> List[Dict[str, str]]:
        """返回管道步骤描述（用于UI展示）"""
        return [
            {
                "step_id": 1,
                "name": "废料分析",
                "agent": "KitchenAgent",
                "action": "analyze_waste",
                "description": "分析废料数据（支持VLM视觉识别输入）",
                "expected_output": "废料分类、重量、成本",
            },
            {
                "step_id": 2,
                "name": "采购量预测",
                "agent": "ProcurementAgent",
                "action": "predict_purchase_quantity",
                "description": "基于废料分析结果预测调整后的采购量",
                "expected_output": "预测采购量、置信度、因子说明",
            },
            {
                "step_id": 3,
                "name": "生成采购建议",
                "agent": "ProcurementAgent",
                "action": "generate_purchase_suggestion",
                "description": "生成正式采购建议单（IP-5流程）",
                "expected_output": "采购建议ID、推荐供应商、预估金额",
            },
            {
                "step_id": 4,
                "name": "店长审批",
                "agent": "StoreManagerAgent",
                "action": "approve_task",
                "description": "店长审核并批准/驳回采购建议",
                "expected_output": "审批状态、审批意见",
            },
            {
                "step_id": 5,
                "name": "KPI回写",
                "agent": "System",
                "action": "write_kpi_feedback",
                "description": "将本次协作结果写入KPI反馈引擎",
                "expected_output": "KPI更新确认",
            },
        ]

    def get_current_status(self) -> Dict[str, Any]:
        """返回当前执行状态"""
        steps = self.get_pipeline_steps()
        return {
            "orchestration_type": "waste_to_purchase",
            "status": self._status.value,
            "current_step": self._current_step,
            "total_steps": len(steps),
            "current_step_name": steps[self._current_step]["name"] if self._current_step < len(steps) else "completed",
            "started_at": self._started_at.isoformat() if self._started_at else None,
            "completed_at": self._completed_at.isoformat() if self._completed_at else None,
            "results_count": len(self._results),
            "errors_count": len(self._errors),
            "errors": self._errors if self._errors else None,
        }

    def orchestrate(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """执行废料→采购→审批完整流程

        Args:
            input_data: {
                "store_id": "store_jiaojiang",
                "vlm_waste_events": [...],  # 可选: VLM废料识别事件
                "item_id": "FP-HNRC-001",   # 需要调整采购的商品
                "auto_approve": False,       # 是否自动审批（测试用）
            }

        Returns:
            完整的协作执行结果
        """
        self._status = OrchestrationStatus.RUNNING
        self._started_at = datetime.now()
        self._errors = []
        self._results = {}

        try:
            # Step 1: KitchenAgent 分析废料
            self._current_step = 0
            logger.info(f"[WasteToPurchase] Step 1: 分析废料数据...")
            waste_result = self._step1_analyze_waste(input_data)
            self._results["step1_waste_analysis"] = waste_result
            self._current_step = 1

            # Step 2: ProcurementAgent 预测采购量
            logger.info("[WasteToPurchase] Step 2: 预测调整后采购量...")
            purchase_qty_result = self._step2_predict_quantity(input_data, waste_result)
            self._results["step2_purchase_prediction"] = purchase_qty_result
            self._current_step = 2

            # Step 3: ProcurementAgent 生成采购建议
            logger.info("[WasteToPurchase] Step 3: 生成采购建议...")
            suggestion_result = self._step3_generate_suggestion(input_data, purchase_qty_result)
            self._results["step3_purchase_suggestion"] = suggestion_result
            self._current_step = 3

            # Step 4: StoreManagerAgent 审批
            logger.info("[WasteToPurchase] Step 4: 提交店长审批...")
            approval_result = self._step4_approve(input_data, suggestion_result)
            self._results["step4_approval"] = approval_result
            self._current_step = 4

            # Step 5: KPI回写
            logger.info("[WasteToPurchase] Step 5: 写入KPI反馈...")
            kpi_result = self._step5_write_kpi(waste_result, approval_result)
            self._results["step5_kpi_feedback"] = kpi_result
            self._current_step = 5

            # 完成
            self._status = OrchestrationStatus.COMPLETED
            self._completed_at = datetime.now()

            return {
                "orchestration_type": "waste_to_purchase",
                "status": self._status.value,
                "message": "废料→采购→审批流程完成",
                "pipeline_steps": len(self.get_pipeline_steps()),
                "steps_completed": self._current_step,
                "results": self._results,
                "execution_time_sec": round((self._completed_at - self._started_at).total_seconds(), 2),
                "generated_at": datetime.now().isoformat(),
            }

        except Exception as e:
            self._status = OrchestrationStatus.FAILED
            self._errors.append(str(e))
            logger.error(f"[WasteToPurchase] 流程失败: {e}")
            return {
                "orchestration_type": "waste_to_purchase",
                "status": self._status.value,
                "error": str(e),
                "steps_completed": self._current_step,
                "errors": self._errors,
                "generated_at": datetime.now().isoformat(),
            }

    def _step1_analyze_waste(self, input_data: Dict) -> Dict:
        """Step 1: 调用KitchenAgent分析废料"""
        from .agents import KitchenAgent

        kitchen = KitchenAgent()
        waste_input = {
            "store_id": input_data.get("store_id", "store_jiaojiang"),
            "days": input_data.get("days", 7),
            "vlm_waste_events": input_data.get("vlm_waste_events", []),
        }
        return kitchen._execute_task("analyze_waste", waste_input)

    def _step2_predict_quantity(self, input_data: Dict, waste_result: Dict) -> Dict:
        """Step 2: 基于废料分析结果预测采购量"""
        from .agents import ProcurementAgent

        procurement = ProcurementAgent()
        item_id = input_data.get("item_id", "FP-HNRC-001")

        # 根据废料情况调整预测参数
        total_waste = waste_result.get("total_waste_kg", 0)
        has_promo = total_waste > 15  # 废料高时假设需要促销清理库存

        predict_input = {
            "item_id": item_id,
            "days": 7,
            "has_promo": has_promo,
            "waste_adjustment": round(total_waste * 0.3, 2),  # 废料30%转化为额外需求
        }
        return procurement._execute_task("predict_purchase_quantity", predict_input)

    def _step3_generate_suggestion(self, input_data: Dict, qty_result: Dict) -> Dict:
        """Step 3: 生成正式采购建议"""
        from .agents import ProcurementAgent

        procurement = ProcurementAgent()
        predicted_qty = qty_result.get("prediction", {}).get("predicted_qty", 10)

        suggestion_input = {
            "items": [{"sku": input_data.get("item_id", "FP-HNRC-001"), "qty": predicted_qty}],
            "supplier": "王总(一级)",
            "reason": f"基于废料分析和智能预测，建议采购{predicted_qty}kg",
        }
        return procurement._execute_task("generate_purchase_suggestion", suggestion_input)

    def _step4_approve(self, input_data: Dict, suggestion_result: Dict) -> Dict:
        """Step 4: 提交店长审批"""
        from .agents import StoreManagerAgent

        manager = StoreManagerAgent()
        auto_approve = input_data.get("auto_approve", False)

        if auto_approve:
            # 测试模式/Demo模式: 自动批准（跳过真实审批流程）
            return {
                "approval_status": "approved",
                "approved_by": "system_auto_demo",
                "message": "Demo模式自动批准",
                "suggestion_id": suggestion_result.get("suggestion_id", "DEMO-001"),
                "timestamp": datetime.now().isoformat(),
            }
        else:
            # 正常模式: 创建待审批任务
            try:
                approval_input = {
                    "task_type": "review_pending_approvals",
                    "suggestion_id": suggestion_result.get("suggestion_id"),
                    "auto_approve": auto_approve,
                }
                result = manager._execute_task("review_pending_approvals", approval_input)
                result["approval_status"] = "pending_review"
                return result
            except Exception as e:
                logger.warning(f"审批流程异常（使用降级方案）: {e}")
                return {
                    "approval_status": "pending_review_fallback",
                    "message": f"审批已提交(降级模式): {str(e)[:100]}",
                    "suggestion_id": suggestion_result.get("suggestion_id", "UNKNOWN"),
                    "timestamp": datetime.now().isoformat(),
                }

    def _step5_write_kpi(self, waste_result: Dict, approval_result: Dict) -> Dict:
        """Step 5: 将协作结果写入KPI反馈引擎"""
        try:
            from .kpi_feedback_engine import KPIFeedbackEngine

            # 尝试获取引擎实例（兼容不同版本）
            try:
                engine = KPIFeedbackEngine.get_instance()
            except (AttributeError, TypeError):
                # 降级: 直接实例化
                engine = KPIFeedbackEngine()

            feedback_record = {
                "source": "waste_to_purchase_orchestration",
                "timestamp": datetime.now().isoformat(),
                "metrics": {
                    "waste_total_kg": waste_result.get("total_waste_kg", 0),
                    "waste_total_cost": waste_result.get("total_cost", 0),
                    "approval_status": approval_result.get("approval_status", "unknown"),
                },
                "tags": ["orchestration", "waste", "procurement"],
            }

            # 尝试写入KPI引擎
            engine.record_feedback(feedback_record)

            return {
                "kpi_write_status": "success",
                "record_id": f"KP-{datetime.now().strftime('%H%M%S')}",
                "feedback_record": feedback_record,
            }
        except Exception as e:
            logger.warning(f"KPI写入失败（非致命）: {e}")
            return {
                "kpi_write_status": "skipped",
                "reason": f"KPI引擎不可用: {e}",
            }


# ──────────────────────────────────────────────────────────────
# 场景2: 脏桌→清台→服务KPI (FrontHallAgent内部闭环)
# ──────────────────────────────────────────────────────────────

class TableServiceLoop:
    """视觉检测脏桌 → 自动创建清台任务 → 跟踪响应时间 → 写入服务KPI

    协作链路（FrontHallAgent内部闭环）:
    vision.table.dirty事件 → FrontHallAgent._detect_dirty_tables()
    → _create_cleaning_task() → _check_response_time() → kpi_feedback_engine

    适用场景:
    - 视觉系统检测到脏桌自动派发清台任务
    - 服务响应时间监控与KPI考核
    - 翻台率优化的自动化支撑
    """

    def __init__(self):
        self._status = OrchestrationStatus.PENDING
        self._current_step = 0
        self._results: Dict[str, Any] = {}
        self._errors: List[str] = []
        self._started_at: Optional[datetime] = None
        self._completed_at: Optional[datetime] = None
        self._detected_tables: List[Dict] = []
        self._created_tasks: List[Dict] = []

    def get_pipeline_steps(self) -> List[Dict[str, str]]:
        """返回管道步骤描述（用于UI展示）"""
        return [
            {
                "step_id": 1,
                "name": "脏桌检测",
                "agent": "VisionSystem + FrontHallAgent",
                "action": "_detect_dirty_tables",
                "description": "接收视觉事件，检测需要清理的餐桌",
                "expected_output": "脏桌列表（桌号、脏污时长、置信度）",
            },
            {
                "step_id": 2,
                "name": "创建清台任务",
                "agent": "FrontHallAgent",
                "action": "_create_cleaning_task",
                "description": "为每张脏桌创建清台任务并推送到PDA",
                "expected_output": "任务ID列表、截止时间",
            },
            {
                "step_id": 3,
                "name": "响应跟踪",
                "agent": "FrontHallAgent",
                "action": "_check_response_time",
                "description": "监控任务接单和完成情况，计算响应时间",
                "expected_output": "平均响应时间、超时任务数",
            },
            {
                "step_id": 4,
                "name": "服务KPI写入",
                "agent": "KPIFeedbackEngine",
                "action": "write_service_kpi",
                "description": "将响应时间等指标写入服务KPI体系",
                "expected_output": "KPI更新确认、趋势标记",
            },
        ]

    def get_current_status(self) -> Dict[str, Any]:
        """返回当前执行状态"""
        steps = self.get_pipeline_steps()
        return {
            "orchestration_type": "table_service_loop",
            "status": self._status.value,
            "current_step": self._current_step,
            "total_steps": len(steps),
            "current_step_name": steps[self._current_step]["name"] if self._current_step < len(steps) else "completed",
            "detected_tables_count": len(self._detected_tables),
            "created_tasks_count": len(self._created_tasks),
            "started_at": self._started_at.isoformat() if self._started_at else None,
            "completed_at": self._completed_at.isoformat() if self._completed_at else None,
            "errors": self._errors if self._errors else None,
        }

    def orchestrate(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """执行脏桌→清台→服务KPI完整闭环

        Args:
            input_data: {
                "store_id": "store_jiaojiang",
                "vision_event": {...},      # 视觉检测结果事件
                "tables_override": [...],    # 可选: 手动指定脏桌（测试用）
                "response_target_sec": 180,  # 响应时间目标（秒）
            }

        Returns:
            完整的服务闭环执行结果
        """
        self._status = OrchestrationStatus.RUNNING
        self._started_at = datetime.now()
        self._errors = []
        self._results = {}

        try:
            # Step 1: 检测脏桌
            self._current_step = 0
            logger.info("[TableServiceLoop] Step 1: 检测脏桌...")
            detection_result = self._step1_detect_dirty_tables(input_data)
            self._detected_tables = detection_result.get("tables", [])
            self._results["step1_detection"] = detection_result
            self._current_step = 1

            if not self._detected_tables:
                self._status = OrchestrationStatus.COMPLETED
                self._completed_at = datetime.now()
                return {
                    **self._build_result(),
                    "message": "未检测到脏桌，流程提前结束",
                }

            # Step 2: 创建清台任务
            logger.info("[TableServiceLoop] Step 2: 创建清台任务...")
            tasks_result = self._step2_create_cleaning_tasks(input_data)
            self._created_tasks = tasks_result.get("tasks", [])
            self._results["step2_task_creation"] = tasks_result
            self._current_step = 2

            # Step 3: 跟踪响应时间
            logger.info("[TableServiceLoop] Step 3: 跟踪响应时间...")
            response_result = self._step3_check_response_time(input_data)
            self._results["step3_response_tracking"] = response_result
            self._current_step = 3

            # Step 4: 写入服务KPI
            logger.info("[TableServiceLoop] Step 4: 写入服务KPI...")
            kpi_result = self._step4_write_service_kpi(detection_result, response_result)
            self._results["step4_kpi_write"] = kpi_result
            self._current_step = 4

            # 完成
            self._status = OrchestrationStatus.COMPLETED
            self._completed_at = datetime.now()

            return self._build_result()

        except Exception as e:
            self._status = OrchestrationStatus.FAILED
            self._errors.append(str(e))
            logger.error(f"[TableServiceLoop] 流程失败: {e}")
            return {
                **self._build_base_result(),
                "status": self._status.value,
                "error": str(e),
                "errors": self._errors,
            }

    def _build_result(self) -> Dict:
        """构建成功结果"""
        base = self._build_base_result()
        base.update({
            "status": self._status.value,
            "message": f"服务闭环完成，处理{len(self._detected_tables)}张脏桌，创建{len(self._created_tasks)}个任务",
            "detected_tables": self._detected_tables,
            "created_tasks": self._created_tasks,
            "results": self._results,
        })
        return base

    def _build_base_result(self) -> Dict:
        """构建基础结果结构"""
        return {
            "orchestration_type": "table_service_loop",
            "current_step": self._current_step,
            "total_steps": len(self.get_pipeline_steps()),
            "started_at": self._started_at.isoformat() if self._started_at else None,
            "completed_at": self._completed_at.isoformat() if self._completed_at else None,
            "execution_time_sec": round(
                (self._completed_at - self._started_at).total_seconds(), 2
            ) if self._started_at and self._completed_at else None,
            "generated_at": datetime.now().isoformat(),
        }

    def _step1_detect_dirty_tables(self, input_data: Dict) -> Dict:
        """Step 1: 调用FrontHallAgent检测脏桌"""
        from .agents import FrontHallAgent

        front_hall = FrontHallAgent()
        detect_input = {
            **input_data.get("vision_event", {}),
            "store_id": input_data.get("store_id", "store_jiaojiang"),
        }

        # 如果有手动指定的脏桌（测试用），直接使用
        if input_data.get("tables_override"):
            detect_input["_test_tables"] = input_data["tables_override"]

        return front_hall._execute_task("detect_dirty_tables", detect_input)

    def _step2_create_cleaning_tasks(self, input_data: Dict) -> Dict:
        """Step 2: 为每张脏桌创建清台任务"""
        from .agents import FrontHallAgent

        front_hall = FrontHallAgent()
        tasks = []

        for table in self._detected_tables:
            table_id = table.get("table_id")
            dirty_since_min = table.get("dirty_since_min", 0)

            # 根据脏污时长确定紧急程度
            urgency = "urgent" if dirty_since_min > 10 else "normal"

            task_input = {
                "table_id": table_id,
                "urgency": urgency,
                "source": "vision_auto",
                "dirty_since_min": dirty_since_min,
            }
            task = front_hall._execute_task("create_cleaning_task", task_input)
            tasks.append(task)

        return {
            "tasks": tasks,
            "total_created": len(tasks),
            "urgent_count": sum(1 for t in tasks if t.get("urgency") == "urgent"),
        }

    def _step3_check_response_time(self, input_data: Dict) -> Dict:
        """Step 3: 检查服务响应时间"""
        from .agents import FrontHallAgent

        front_hall = FrontHallAgent()
        target_sec = input_data.get("response_target_sec", 180)

        check_input = {
            "hours": 2,  # 检查最近2小时的响应情况
            "target_sec": target_sec,
            "task_ids": [t.get("task_id") for t in self._created_tasks],
        }

        return front_hall._execute_task("check_response_time", check_input)

    def _step4_write_service_kpi(self, detection_result: Dict, response_result: Dict) -> Dict:
        """Step 4: 写入服务KPI"""
        try:
            from .kpi_feedback_engine import KPIFeedbackEngine

            engine = KPIFeedbackEngine.get_instance()

            kpi_record = {
                "source": "table_service_loop",
                "timestamp": datetime.now().isoformat(),
                "metrics": {
                    "dirty_tables_detected": len(self._detected_tables),
                    "cleaning_tasks_created": len(self._created_tasks),
                    "avg_response_sec": response_result.get("avg_response_sec", 0),
                    "target_sec": response_result.get("target_sec", 180),
                    "within_target": response_result.get("tasks", {}).get("within_target", 0),
                    "overdue": response_result.get("tasks", {}).get("overdue", 0),
                },
                "tags": ["service", "cleaning", "response_time"],
            }

            engine.record_feedback(kpi_record)

            return {
                "kpi_write_status": "success",
                "record_id": f"KPI-SVC-{datetime.now().strftime('%H%M%S')}",
                "key_metrics": {
                    "avg_response_sec": response_result.get("avg_response_sec"),
                    "achievement_rate": round(
                        response_result.get("tasks", {}).get("within_target", 0) /
                        max(response_result.get("tasks", {}).get("total", 1), 1) * 100, 1
                    ),
                },
            }
        except Exception as e:
            logger.warning(f"服务KPI写入失败（非致命）: {e}")
            return {
                "kpi_write_status": "skipped",
                "reason": str(e),
            }


# ──────────────────────────────────────────────────────────────
# 场景3: SOP违规→培训→复盘 (Kitchen→FrontHall协作)
# ──────────────────────────────────────────────────────────────

class SOpViolationTrainingLoop:
    """SOP违规检测 → 生成针对性培训内容 → 班后复盘关联

    协作链路（KitchenAgent → FrontHallAgent）:
    iot.temperature.violation / sop.compliance.fail 事件
    → KitchenAgent._check_sop_compliance()
    → FrontHallAgent._generate_pre_shift_training()
    → _generate_post_shift_review() (关联违规事件)

    适用场景:
    - IoT温度传感器检测到冷库温度异常
    - SOP合规检查未通过时的培训联动
    - 班后复盘自动关联当日违规记录
    """

    def __init__(self):
        self._status = OrchestrationStatus.PENDING
        self._current_step = 0
        self._results: Dict[str, Any] = {}
        self._errors: List[str] = []
        self._started_at: Optional[datetime] = None
        self._completed_at: Optional[datetime] = None
        self._violations: List[Dict] = []
        self._training_content: Dict = {}

    def get_pipeline_steps(self) -> List[Dict[str, str]]:
        """返回管道步骤描述（用于UI展示）"""
        return [
            {
                "step_id": 1,
                "name": "SOP违规检测",
                "agent": "KitchenAgent + IoT/Vision",
                "action": "_check_sop_compliance",
                "description": "接收IoT温度告警或SOP检查失败事件，评估违规严重程度",
                "expected_output": "SOP评分、违规项列表、严重等级",
            },
            {
                "step_id": 2,
                "name": "根因分析",
                "agent": "KitchenAgent",
                "action": "_analyze_violation_root_cause",
                "description": "分析违规原因（设备故障/人为操作/流程缺陷）",
                "expected_output": "根因分类、改进建议",
            },
            {
                "step_id": 3,
                "name": "生成培训内容",
                "agent": "FrontHallAgent",
                "action": "_generate_pre_shift_training",
                "description": "基于违规类型生成针对性的班前培训材料",
                "expected_output": "培训议程、重点话术、目标设定",
            },
            {
                "step_id": 4,
                "name": "班后复盘关联",
                "agent": "FrontHallAgent",
                "action": "_generate_post_shift_review",
                "description": "生成班后复盘报告，自动关联当日SOP违规事件",
                "expected_output": "复盘报告、违规关联、改进计划",
            },
        ]

    def get_current_status(self) -> Dict[str, Any]:
        """返回当前执行状态"""
        steps = self.get_pipeline_steps()
        return {
            "orchestration_type": "sop_violation_training_loop",
            "status": self._status.value,
            "current_step": self._current_step,
            "total_steps": len(steps),
            "current_step_name": steps[self._current_step]["name"] if self._current_step < len(steps) else "completed",
            "violations_count": len(self._violations),
            "training_generated": bool(self._training_content),
            "started_at": self._started_at.isoformat() if self._started_at else None,
            "completed_at": self._completed_at.isoformat() if self._completed_at else None,
            "errors": self._errors if self._errors else None,
        }

    def orchestrate(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """执行SOP违规→培训→复盘完整流程

        Args:
            input_data: {
                "store_id": "store_jiaojiang",
                "violation_event": {           # SOP违规事件
                    "type": "temperature",      # 违规类型
                    "severity": "warning",      # 严重程度
                    "source": "iot_sensor",     # 来源
                    "details": {...},
                },
                "shift": "evening",            # 班次
                "custom_check_items": [...],    # 自定义SOP检查项（可选）
            }

        Returns:
            完整的培训协作执行结果
        """
        self._status = OrchestrationStatus.RUNNING
        self._started_at = datetime.now()
        self._errors = []
        self._results = {}

        try:
            # Step 1: SOP违规检测
            self._current_step = 0
            logger.info("[SOpViolationTraining] Step 1: 检测SOP违规...")
            sop_result = self._step1_check_sop_compliance(input_data)
            self._violations = sop_result.get("violations", [])
            self._results["step1_sop_check"] = sop_result
            self._current_step = 1

            if not self._violations and sop_result.get("status") == "pass":
                self._status = OrchestrationStatus.COMPLETED
                self._completed_at = datetime.now()
                return {
                    **self._build_result(),
                    "message": "SOP检查通过，无需启动培训流程",
                }

            # Step 2: 根因分析
            logger.info("[SOpViolationTraining] Step 2: 分析违规根因...")
            root_cause_result = self._step2_analyze_root_cause(sop_result)
            self._results["step2_root_cause"] = root_cause_result
            self._current_step = 2

            # Step 3: 生成培训内容
            logger.info("[SOpViolationTraining] Step 3: 生成针对性培训...")
            training_result = self._step3_generate_training(input_data, root_cause_result)
            self._training_content = training_result
            self._results["step3_training"] = training_result
            self._current_step = 3

            # Step 4: 班后复盘关联
            logger.info("[SOpViolationTraining] Step 4: 生成班后复盘报告...")
            review_result = self._step4_generate_review(input_data, training_result)
            self._results["step4_review"] = review_result
            self._current_step = 4

            # 完成
            self._status = OrchestrationStatus.COMPLETED
            self._completed_at = datetime.now()

            return self._build_result()

        except Exception as e:
            self._status = OrchestrationStatus.FAILED
            self._errors.append(str(e))
            logger.error(f"[SOpViolationTraining] 流程失败: {e}")
            return {
                **self._build_base_result(),
                "status": self._status.value,
                "error": str(e),
                "errors": self._errors,
            }

    def _build_result(self) -> Dict:
        """构建成功结果"""
        base = self._build_base_result()
        base.update({
            "status": self._status.value,
            "message": f"SOP违规培训流程完成，发现{len(self._violations)}项违规，已生成针对性培训",
            "violations": self._violations,
            "training_content": self._training_content,
            "results": self._results,
        })
        return base

    def _build_base_result(self) -> Dict:
        """构建基础结果结构"""
        return {
            "orchestration_type": "sop_violation_training_loop",
            "current_step": self._current_step,
            "total_steps": len(self.get_pipeline_steps()),
            "started_at": self._started_at.isoformat() if self._started_at else None,
            "completed_at": self._completed_at.isoformat() if self._completed_at else None,
            "execution_time_sec": round(
                (self._completed_at - self._started_at).total_seconds(), 2
            ) if self._started_at and self._completed_at else None,
            "generated_at": datetime.now().isoformat(),
        }

    def _step1_check_sop_compliance(self, input_data: Dict) -> Dict:
        """Step 1: 调用KitchenAgent检查SOP合规性"""
        from .agents import KitchenAgent

        kitchen = KitchenAgent()
        sop_input = {
            "store_id": input_data.get("store_id", "store_jiaojiang"),
            "custom_check_items": input_data.get("custom_check_items"),
        }

        # 如果有违规事件信息，传入以增强检查
        violation_event = input_data.get("violation_event")
        if violation_event:
            sop_input["violation_event"] = violation_event

        return kitchen._execute_task("check_sop_compliance", sop_input)

    def _step2_analyze_root_cause(self, sop_result: Dict) -> Dict:
        """Step 2: 分析违规根因"""
        violations = sop_result.get("violations", [])

        root_causes = []
        for v in violations:
            vtype = v.get("type", "unknown")

            # 基于违规类型的根因分析规则
            if vtype == "temperature":
                cause_category = "设备或操作"
                possible_causes = [
                    "冷库门未关闭严实",
                    "制冷设备故障",
                    "频繁开关冷库导致温度波动",
                    "温度传感器漂移（需校准）",
                ]
                recommendation = "立即检查冷库门密封性和制冷设备运行状态"
            elif vtype == "visual":
                cause_category = "人员操作"
                possible_causes = [
                    "员工未按规范佩戴防护用品",
                    "清洁流程执行不到位",
                    "培训不足导致操作不规范",
                ]
                recommendation = "加强员工培训和现场监督"
            else:
                cause_category = "未知"
                possible_causes = ["需进一步调查"]
                recommendation = "安排专项检查"

            root_causes.append({
                "violation_type": vtype,
                "cause_category": cause_category,
                "possible_causes": possible_causes,
                "recommendation": recommendation,
                "severity": v.get("severity", "warning"),
            })

        return {
            "root_causes": root_causes,
            "summary": {
                "total_violations": len(violations),
                "categories": list(set(rc["cause_category"] for rc in root_causes)),
                "most_common_cause": root_causes[0]["cause_category"] if root_causes else None,
            },
        }

    def _step3_generate_training(self, input_data: Dict, root_cause_result: Dict) -> Dict:
        """Step 3: 基于违规根因生成针对性培训"""
        from .agents import FrontHallAgent

        front_hall = FrontHallAgent()
        shift = input_data.get("shift", "evening")

        # 从根因分析中提取培训要点
        root_causes = root_cause_result.get("root_causes", [])
        training_focus = [rc["recommendation"] for rc in root_causes]

        training_input = {
            "shift": shift,
            "yesterday_issues": training_focus if training_focus else ["SOP合规性待提升"],
            "sop_related": True,
            "violation_types": list(set(rc["violation_type"] for rc in root_causes)),
        }

        return front_hall._execute_task("pre_shift_training", training_input)

    def _step4_generate_review(self, input_data: Dict, training_result: Dict) -> Dict:
        """Step 4: 生成班后复盘报告（关联违规事件）"""
        from .agents import FrontHallAgent

        front_hall = FrontHallAgent()
        shift = input_data.get("shift", "evening")

        review_input = {
            "shift": shift,
            "date": datetime.now().strftime("%Y-%m-%d"),
            "store_id": input_data.get("store_id", "store_jiaojiang"),
            "actual_revenue": input_data.get("actual_revenue", 12800),
            "total_tables": input_data.get("total_tables", 42),
            # 关联违规信息
            "sop_violations": self._violations,
            "violation_count": len(self._violations),
            "training_conducted": bool(training_result),
            "training_topics": training_result.get("agenda", []) if training_result else [],
        }

        review = front_hall._execute_task("post_shift_review", review_input)

        # 在复盘报告中增加违规关联字段
        review["sop_correlation"] = {
            "violations_detected": len(self._violations),
            "training_generated": True,
            "root_cause_addressed": True,
            "follow_up_required": any(v.get("severity") == "critical" for v in self._violations),
        }

        return review


# ──────────────────────────────────────────────────────────────
# 协作场景注册表
# ──────────────────────────────────────────────────────────────

ORCHESTRATION_SCENARIOS: Dict[str, type] = {
    "waste_to_purchase": WasteToPurchaseOrchestration,
    "table_service_loop": TableServiceLoop,
    "sop_violation_training": SOpViolationTrainingLoop,
}


def create_orchestration(scenario_type: str) -> Any:
    """工厂函数: 创建协作场景实例

    Args:
        scenario_type: 场景类型名称
            - waste_to_purchase: 废料→采购→审批
            - table_service_loop: 脏桌→清台→服务KPI
            - sop_violation_training: SOP违规→培训→复盘

    Returns:
        协作场景实例

    Raises:
        ValueError: 如果场景类型不在注册表中
    """
    scenario_cls = ORCHESTRATION_SCENARIOS.get(scenario_type)
    if not scenario_cls:
        available = ", ".join(ORCHESTRATION_SCENARIOS.keys())
        raise ValueError(f"未知协作场景: {scenario_type}, 可用: {available}")

    instance = scenario_cls()
    logger.info(f"🔥火瞳 协作场景创建成功: {scenario_type}")
    return instance


def run_quick_orchestration(scenario_type: str, input_data: Dict[str, Any]) -> Dict[str, Any]:
    """快速执行协作场景（一步到位）

    Args:
        scenario_type: 场景类型
        input_data: 场景输入参数

    Returns:
        执行结果
    """
    scenario = create_orchestration(scenario_type)
    return scenario.orchestrate(input_data)
