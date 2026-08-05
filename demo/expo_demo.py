#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""火瞳 · 重庆展会 Demo 脚本
=====================================
基于 D2 岗位AI助理的 3 个协作场景，构建完整的展会演示流程。

使用方式:
    # 在椒江店 Jetson 上运行
    cd /opt/hotpot-smart-ops && python3 demo/expo_demo.py

    # 仅运行指定场景
    python3 demo/expo_demo.py --scene waste_to_purchase

    # 输出 JSON 结果
    python3 demo/expo_demo.py --format json

    # 快速模式（跳过延迟）
    python3 demo/expo_demo.py --fast

场景列表:
  1. waste_to_purchase  - 废料→智能采购→审批闭环 (5步)
  2. table_service_loop - 脏桌检测→清台→服务KPI闭环 (4步)
  3. sop_violation_training - SOP违规→培训→复盘闭环 (4步)

作者: 火瞳AI团队
日期: 2026-08-05 (基于 D2 Orchestration 场景落地)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

# 确保项目根目录在路径中
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# ──────────────────────────────────────────────────────────────
# ANSI 颜色定义 (兼容 Python 3.8+)
# ──────────────────────────────────────────────────────────────

class C:
    """终端颜色常量"""
    RED = "\033[91m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    BLUE = "\033[94m"
    MAGENTA = "\033[95m"
    CYAN = "\033[96m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    UNDERLINE = "\033[4m"
    END = "\033[0m"

# ──────────────────────────────────────────────────────────────
# Demo 配置
# ──────────────────────────────────────────────────────────────

DEMO_CONFIG = {
    "title": "火瞳 · AI运营中台",
    "subtitle": "视觉 + 数据双引擎 | 冯校长火锅连锁",
    "event": "2026重庆市政府「AI+火锅」展会",
    "version": "v1.0 (D2 Orchestration)",
    "store_name": "椒江店",
    "store_id": "store_jiaojiang",
    # 延迟配置（秒），fast 模式下会缩短
    "delays": {
        "step": 0.8,      # 步骤间延迟
        "scene": 1.5,     # 场景间延迟
        "typing": 0.05,   # 打字机效果字符间隔
        "summary": 2.0,   # 汇总展示时间
    },
}

# 场景模拟数据
SCENE_DATA = {
    "waste_to_purchase": {
        "store_id": "store_jiaojiang",
        "item_id": "FP-HNRC-001",  # 毛肚
        "vlm_waste_events": [
            {"item": "毛肚", "count": 3, "reason": "过期变质", "weight_kg": 1.5},
            {"item": "鸭肠", "count": 2, "reason": "解冻过度", "weight_kg": 0.8},
        ],
        "auto_approve": True,  # Demo 模式自动审批
        "days": 7,
    },
    "table_service_loop": {
        "store_id": "store_jiaojiang",
        "tables_override": [
            {"table_id": "A05", "dirty_since_min": 12, "confidence": 0.95},
            {"table_id": "B03", "dirty_since_min": 5, "confidence": 0.88},
            {"table_id": "C07", "dirty_since_min": 18, "confidence": 0.97},
        ],
        "response_target_sec": 180,
    },
    "sop_violation_training": {
        "store_id": "store_jiaojiang",
        "violation_event": {
            "type": "temperature",
            "severity": "warning",
            "source": "iot_sensor",
            "details": {
                "sensor_id": "TEMP-COLD-01",
                "location": "冷库A区",
                "current_temp": -12.5,  # 应该 ≤ -18°C
                "threshold": -18.0,
                "duration_min": 25,
            }
        },
        "shift": "evening",
        "actual_revenue": 12800,
        "total_tables": 42,
    },
}


# ──────────────────────────────────────────────────────────────
# 工具函数
# ──────────────────────────────────────────────────────────────

def print_banner():
    """打印开场 Banner"""
    banner = f"""
{C.BOLD}{C.MAGENTA}
╔══════════════════════════════════════════════════════════════╗
║                                                              ║
║   🔥 火 瞳 · AI 运 营 中 台                                ║
║                                                              ║
║   视觉 + 数据 双引擎                                        ║
║   冯校长火锅连锁 · 浙江总代                                  ║
║                                                              ║
║   {C.CYAN}2026重庆市政府「AI+火锅」展会{C.MAGENTA}                        ║
║   {C.DIM}Demo v1.0 | 基于 D2 Agent 协作场景{C.MAGENTA}                         ║
║                                                              ║
╚══════════════════════════════════════════════════════════════╝
{C.END}
"""
    print(banner)


def print_separator(char="─", length=60):
    """打印分隔线"""
    print(f"{C.DIM}{char * length}{C.END}")


def print_typing(text: str, delay: float = 0.02):
    """打字机效果输出"""
    for char in text:
        sys.stdout.write(char)
        sys.stdout.flush()
        time.sleep(delay)
    print()


def print_step_header(step_num: int, total: int, name: str, agent: str = ""):
    """打印步骤标题"""
    agent_info = f" | {C.CYAN}{agent}{C.END}" if agent else ""
    print(f"\n{C.BOLD}▶ Step {step_num}/{total}: {name}{agent_info}{C.END}")


def print_result(label: str, value: any, color: str = C.GREEN):
    """打印键值对结果"""
    if isinstance(value, float):
        formatted = f"{value:.2f}"
    elif isinstance(value, dict):
        formatted = json.dumps(value, ensure_ascii=False, indent=2)
    else:
        formatted = str(value)
    print(f"  {color}✓{C.END} {label}: {C.BOLD}{formatted}{C.END}")


def print_error(label: str, error: str):
    """打印错误信息"""
    print(f"  {C.RED}✗{C.END} {label}: {error}")


def progress_bar(current: int, total: int, width:30, prefix=""):
    """生成进度条字符串"""
    if total == 0:
        return f"{prefix}[{'█' * width}] 100%"
    filled = int(width * current / total)
    bar = "█" * filled + "░" * (width - filled)
    pct = int(100 * current / total)
    return f"{prefix}[{C.GREEN}{bar}{C.END}] {pct}%"


# ──────────────────────────────────────────────────────────────
# Demo 运行器主类
# ──────────────────────────────────────────────────────────────

class ExpoDemoRunner:
    """火瞳展会 Demo 运行器

    基于 D2 的 3 个 Orchestration 协作场景，构建完整的展会演示流程。
    """

    def __init__(self, fast_mode: bool = False, output_format: str = "terminal"):
        self.fast_mode = fast_mode
        self.output_format = output_format
        self.results: Dict[str, Any] = {}
        self.start_time: Optional[datetime] = None
        self.end_time: Optional[datetime] = None

        # 根据模式调整延迟
        if fast_mode:
            self.delays = {k: v * 0.1 for k, v in DEMO_CONFIG["delays"].items()}
        else:
            self.delays = DEMO_CONFIG["delays"].copy()

    def _delay(self, key: str = "step"):
        """执行延迟"""
        time.sleep(self.delays.get(key, 0.5))

    # ── 开场 ────────────────────────────────────────────────

    def show_opening(self) -> Dict:
        """Demo 开场：品牌展示 + 核心价值主张"""
        print_banner()
        self._delay("summary")

        opening = {
            "timestamp": datetime.now().isoformat(),
            "narrative": [
                "看得见的损失：后厨摄像头实时检测废料，算出每盘菜浪费了多少钱",
                "算得清的订货：AI 预测明天卖多少，自动生成采购清单，店长手机确认",
                "管得住的连锁：两家店数据同屏对比，哪里异常一目了然",
                "融得了的资：单店年省≥15万，真实 ROI 数据，可复制可扩张",
            ],
            "key_metrics": {
                "prediction_mape": "10.6%",
                "waste_rate_improvement": "12% → 7.2%",
                "annual_saving": "¥15万+",
                "stores_count": "2家（椒江+玉环）",
            }
        }

        print(f"\n{C.BOLD}{C.BLUE}📖 展会叙事线{C.END}")
        for i, line in enumerate(opening["narrative"], 1):
            print(f"  {C.CYAN}{i}.{C.END} {line}")
            self._delay("typing")

        print(f"\n{C.BOLD}📊 核心指标（椒江店 90 天验证）:{C.END}")
        for k, v in opening["key_metrics"].items():
            print_result(k, v, C.YELLOW)

        self._delay("scene")
        return opening

    # ── 场景1: 废料→采购→审批 ─────────────────────────────

    def run_scene_waste_to_purchase(self) -> Dict:
        """场景1: 废料检测 → 智能采购建议 → 店长审批完整流程"""
        print_separator()
        print(f"\n{C.BOLD}{C.MAGENTA}🎬 场景1: 废料→智能采购→审批闭环{C.END}")
        print(f"{C.DIM}演示时长: ~2分钟 | 协作链路: KitchenAgent → ProcurementAgent → StoreManagerAgent{C.END}")
        print_separator()

        scene_result = {
            "scene_id": "S1",
            "scene_name": "废料→智能采购→审批",
            "orchestration_type": "waste_to_purchase",
            "steps_results": [],
            "key_metrics": {},
        }

        try:
            # 导入并创建场景
            from hotpot_platform.cloud.agent_framework.orchestration_scenarios import (
                create_orchestration, WasteToPurchaseOrchestration
            )
            orch = create_orchestration("waste_to_purchase")

            # 显示管道步骤概览
            steps = orch.get_pipeline_steps()
            print(f"\n{C.CYAN}📋 管道步骤 ({len(steps)}步):{C.END}")
            for s in steps:
                print(f"  {C.DIM}{s['step_id']}. {s['name']} [{s['agent']}] — {s['description']}{C.END}")

            self._delay("step")

            # 执行场景
            input_data = SCENE_DATA["waste_to_purchase"]
            print(f"\n{C.BOLD}🚀 开始执行...{C.END}")
            self._delay("step")

            result = orch.orchestrate(input_data)
            scene_result["execution_result"] = result
            scene_result["status"] = result.get("status", "unknown")

            # 展示结果
            if result.get("status") == "completed":
                print(f"\n{C.GREEN}✅ 场景1 执行完成!{C.END}")
                print_result("状态", "COMPLETED")
                print_result("执行耗时", f"{result.get('execution_time_sec', 0):.2f}s")

                # 展示各步骤结果
                results_dict = result.get("results", {})
                step_names = {
                    "step1_waste_analysis": "废料分析",
                    "step2_purchase_prediction": "采购量预测",
                    "step3_purchase_suggestion": "采购建议",
                    "step4_approval": "审批结果",
                    "step5_kpi_feedback": "KPI回写",
                }

                print(f"\n{C.CYAN}📝 各步骤详情:{C.END}")
                for step_key, step_name in step_names.items():
                    step_data = results_dict.get(step_key, {})
                    if step_data:
                        scene_result["steps_results"].append({
                            "step": step_name,
                            "data": step_data
                        })
                        # 提取关键信息显示
                        if step_key == "step1_waste_analysis":
                            print(f"\n  {C.BOLD}▸ {step_name}:{C.END}")
                            print_result("废料总量", f"{step_data.get('total_waste_kg', 0)} kg")
                            print_result("损耗金额", f"¥{step_data.get('total_cost', 0)}")
                            scene_result["key_metrics"]["废料总量"] = f"{step_data.get('total_waste_kg', 0)} kg"
                            scene_result["key_metrics"]["损耗金额"] = f"¥{step_data.get('total_cost', 0)}"

                        elif step_key == "step2_purchase_prediction":
                            print(f"\n  {C.BOLD}▸ {step_name}:{C.END}")
                            pred = step_data.get("prediction", {})
                            print_result("预测采购量", f"{pred.get('predicted_qty', 0)} kg")
                            print_result("置信度", f"{pred.get('confidence', 0)}%")
                            scene_result["key_metrics"]["预测采购量"] = f"{pred.get('predicted_qty', 0)} kg"

                        elif step_key == "step3_purchase_suggestion":
                            print(f"\n  {C.BOLD}▸ {step_name}:{C.END}")
                            print_result("建议ID", step_data.get("suggestion_id", "N/A"))
                            print_result("推荐供应商", step_data.get("supplier", "N/A"))
                            print_result("预估金额", f"¥{step_data.get('estimated_amount', 0)}")
                            scene_result["key_metrics"]["预估金额"] = f"¥{step_data.get('estimated_amount', 0)}"

                        elif step_key == "step4_approval":
                            print(f"\n  {C.BOLD}▸ {step_name}:{C.END}")
                            print_result("审批状态", step_data.get("approval_status", "N/A"))
                            scene_result["key_metrics"]["审批状态"] = step_data.get("approval_status", "N/A")

                        elif step_key == "step5_kpi_feedback":
                            print(f"\n  {C.BOLD}▸ {step_name}:{C.END}")
                            print_result("KPI写入状态", step_data.get("kpi_write_status", "N/A"))
                            scene_result["key_metrics"]["KPI回写"] = step_data.get("kpi_write_status", "N/A")

                # 如果有部分结果，也展示
                if not scene_result["key_metrics"] and results_dict:
                    print(f"\n{C.YELLOW}⚠ 部分步骤返回数据（可能存在非致命错误）:{C.END}")
                    for step_key, step_data in results_dict.items():
                        if step_data and isinstance(step_data, dict):
                            print(f"  • {step_key}: {list(step_data.keys())[:3]}...")
                    # 尝试从 error 中提取信息
                    if result.get("error"):
                        scene_result["key_metrics"]["备注"] = f"流程执行到第{result.get('steps_completed', 0)}步"

            else:
                # 部分成功：即使整体状态不是 completed，也可能有部分结果
                partial_results = result.get("results", {})
                steps_done = result.get("steps_completed", 0)
                total_steps = result.get("pipeline_steps", len(steps) if 'steps' in dir() else 5)

                if partial_results and steps_done > 0:
                    print(f"\n{C.YELLOW}⚠️ 场景1 部分完成 ({steps_done}/{total_steps}步){C.END}")
                    print_result("执行进度", f"{steps_done}/{total_steps} 步")

                    # 展示已完成步骤的数据
                    for step_key, step_data in partial_results.items():
                        if step_data:
                            print(f"  ✓ {step_key}: 数据已获取")
                            if "total_waste_kg" in str(step_data):
                                scene_result["key_metrics"]["废料总量"] = f"{step_data.get('total_waste_kg', '?')} kg"
                            if "prediction" in str(step_data):
                                pred = step_data.get("prediction", {})
                                scene_result["key_metrics"]["预测采购量"] = f"{pred.get('predicted_qty', '?')} kg"

                    scene_result["status"] = "partial_success"
                else:
                    print(f"\n{C.RED}❌ 场景1 执行失败: {result.get('error', 'Unknown')}{C.END}")
                    scene_result["status"] = "failed"
                    scene_result["error"] = result.get("error")

        except Exception as e:
            print(f"\n{C.RED}❌ 场景1 异常: {e}{C.END}")
            scene_result["status"] = "error"
            scene_result["error"] = str(e)

        self.results["scene1_waste_to_purchase"] = scene_result
        self._delay("scene")
        return scene_result

    # ── 场景2: 脏桌→清台→服务KPI ──────────────────────────

    def run_scene_table_service(self) -> Dict:
        """场景2: 脏桌视觉检测 → 清台任务 → 服务KPI闭环"""
        print_separator()
        print(f"\n{C.BOLD}{C.MAGENTA}🎬 场景2: 脏桌检测→清台→服务KPI闭环{C.END}")
        print(f"{C.DIM}演示时长: ~1.5分钟 | 协作链路: VisionSystem → FrontHallAgent → KPIEngine{C.END}")
        print_separator()

        scene_result = {
            "scene_id": "S2",
            "scene_name": "脏桌检测→清台→服务KPI",
            "orchestration_type": "table_service_loop",
            "steps_results": [],
            "key_metrics": {},
        }

        try:
            from hotpot_platform.cloud.agent_framework.orchestration_scenarios import (
                create_orchestration, TableServiceLoop
            )
            orch = create_orchestration("table_service_loop")

            steps = orch.get_pipeline_steps()
            print(f"\n{C.CYAN}📋 管道步骤 ({len(steps)}步):{C.END}")
            for s in steps:
                print(f"  {C.DIM}{s['step_id']}. {s['name']} [{s['agent']}] — {s['description']}{C.END}")

            self._delay("step")

            input_data = SCENE_DATA["table_service_loop"]
            print(f"\n{C.BOLD}🚀 开始执行...{C.END}")
            print(f"{C.DIM}模拟输入: {len(input_data.get('tables_override', []))} 张脏桌 detected{C.END}")
            self._delay("step")

            result = orch.orchestrate(input_data)
            scene_result["execution_result"] = result
            scene_result["status"] = result.get("status", "unknown")

            if result.get("status") == "completed":
                print(f"\n{C.GREEN}✅ 场景2 执行完成!{C.END}")
                print_result("状态", "COMPLETED")
                print_result("执行耗时", f"{result.get('execution_time_sec', 0):.2f}s")

                # 脏桌检测结果
                detected = result.get("detected_tables", [])
                print(f"\n{C.CYAN}📹 脏桌检测结果:{C.END}")
                for t in detected:
                    urgency_marker = "🔴" if t.get("urgency") == "urgent" else "🟡"
                    print(f"  {urgency_marker} 桌号 {t.get('table_id')} | "
                          f"脏污时长: {t.get('dirty_since_min', 0)}min | "
                          f"置信度: {t.get('confidence', 0)}")

                scene_result["key_metrics"]["检测脏桌数"] = len(detected)
                scene_result["key_metrics"]["紧急任务数"] = sum(
                    1 for t in result.get("created_tasks", []) if t.get("urgency") == "urgent"
                )

                # 任务创建结果
                tasks = result.get("created_tasks", [])
                print(f"\n{C.CYAN}📋 清台任务创建 ({len(tasks)}个):{C.END}")
                for task in tasks[:5]:  # 最多显示5个
                    print(f"  ✓ 任务ID: {task.get('task_id', 'N/A')} | "
                          f"桌号: {task.get('table_id', 'N/A')} | "
                          f"紧急度: {task.get('urgency', 'N/A')}")

                scene_result["key_metrics"]["创建任务数"] = len(tasks)

                # KPI 结果
                results_dict = result.get("results", {})
                kpi_data = results_dict.get("step4_kpi_write", {})
                if kpi_data:
                    key_metrics = kpi_data.get("key_metrics", {})
                    print(f"\n{C.CYAN}📊 服务KPI:{C.END}")
                    print_result("平均响应时间", f"{key_metrics.get('avg_response_sec', 0)}s")
                    print_result("目标达成率", f"{key_metrics.get('achievement_rate', 0)}%")
                    scene_result["key_metrics"]["平均响应时间"] = f"{key_metrics.get('avg_response_sec', 0)}s"
                    scene_result["key_metrics"]["目标达成率"] = f"{key_metrics.get('achievement_rate', 0)}%"

                print(f"\n{C.BOLD}💡 亮点: 视觉系统自动发现脏桌 → AI秒级派单 → 服务员PDA接单 → 响应时间实时追踪{C.END}")

            else:
                print(f"\n{C.RED}❌ 场景2 执行失败: {result.get('error', 'Unknown')}{C.END}")
                scene_result["status"] = "failed"

        except Exception as e:
            print(f"\n{C.RED}❌ 场景2 异常: {e}{C.END}")
            scene_result["status"] = "error"
            scene_result["error"] = str(e)

        self.results["scene2_table_service"] = scene_result
        self._delay("scene")
        return scene_result

    # ── 场景3: SOP违规→培训→复盘 ───────────────────────────

    def run_scene_sop_violation(self) -> Dict:
        """场景3: SOP违规检测 → 培训生成 → 班后复盘关联"""
        print_separator()
        print(f"\n{C.BOLD}{C.MAGENTA}🎬 场景3: SOP违规→培训→复盘闭环{C.END}")
        print(f"{C.DIM}演示时长: ~1.5分钟 | 协作链路: KitchenAgent → FrontHallAgent{C.END}")
        print_separator()

        scene_result = {
            "scene_id": "S3",
            "scene_name": "SOP违规→培训→复盘",
            "orchestration_type": "sop_violation_training",
            "steps_results": [],
            "key_metrics": {},
        }

        try:
            from hotpot_platform.cloud.agent_framework.orchestration_scenarios import (
                create_orchestration, SOpViolationTrainingLoop
            )
            orch = create_orchestration("sop_violation_training")

            steps = orch.get_pipeline_steps()
            print(f"\n{C.CYAN}📋 管道步骤 ({len(steps)}步):{C.END}")
            for s in steps:
                print(f"  {C.DIM}{s['step_id']}. {s['name']} [{s['agent']}] — {s['description']}{C.END}")

            self._delay("step")

            input_data = SCENE_DATA["sop_violation_training"]
            violation_event = input_data.get("violation_event", {})
            print(f"\n{C.BOLD}🚀 开始执行...{C.END}")
            print(f"{C.DIM}模拟输入: IoT温度告警 | 当前: {violation_event.get('details', {}).get('current_temp', 'N/A')}°C "
                  f"(阈值: {violation_event.get('details', {}).get('threshold', 'N/A')}°C){C.END}")
            self._delay("step")

            result = orch.orchestrate(input_data)
            scene_result["execution_result"] = result
            scene_result["status"] = result.get("status", "unknown")

            if result.get("status") == "completed":
                print(f"\n{C.GREEN}✅ 场景3 执行完成!{C.END}")
                print_result("状态", "COMPLETED")
                print_result("执行耗时", f"{result.get('execution_time_sec', 0):.2f}s")

                # SOP违规检测结果
                violations = result.get("violations", [])
                print(f"\n{C.CYAN}🔍 SOP违规检测结果 ({len(violations)}项):{C.END}")
                for v in violations[:5]:
                    sev_emoji = {"critical": "🔴", "major": "🟠", "warning": "🟡", "minor": "🔵"}.get(
                        v.get("severity", "info"), "⚪"
                    )
                    print(f"  {sev_emoji} [{v.get('type', 'N/A')}] {v.get('rule_name', v.get('description', 'N/A'))}")

                scene_result["key_metrics"]["违规项数"] = len(violations)

                # 根因分析
                results_dict = result.get("results", {})
                root_cause = results_dict.get("step2_root_cause", {})
                if root_cause:
                    summary = root_cause.get("summary", {})
                    print(f"\n{C.CYAN}🔬 根因分析:{C.END}")
                    print_result("违规分类", ", ".join(summary.get("categories", [])))
                    print_result("主要根因", summary.get("most_common_cause", "N/A"))

                    causes = root_cause.get("root_causes", [])
                    if causes:
                        print(f"\n  可能原因:")
                        for c in causes[:3]:
                            for cause in c.get("possible_causes", [])[:2]:
                                print(f"    • {cause}")

                # 培训内容
                training = results_dict.get("step3_training", {})
                if training:
                    print(f"\n{C.CYAN}📚 生成的培训内容:{C.END}")
                    agenda = training.get("agenda", [])
                    if agenda:
                        print(f"  培训议程:")
                        for item in agenda[:5]:
                            print(f"    • {item}")
                    scene_result["key_metrics"]["培训议程数"] = len(agenda)

                # 复盘报告
                review = results_dict.get("step4_review", {})
                if review:
                    print(f"\n{C.CYAN}📋 班后复盘报告:{C.END}")
                    sop_corr = review.get("sop_correlation", {})
                    print_result("违规关联", f"{sop_corr.get('violations_detected', 0)}项已关联")
                    print_result("培训已执行", sop_corr.get("training_generated", False))
                    print_result("需跟进", "是" if sop_corr.get("follow_up_required", False) else "否")

                print(f"\n{C.BOLD}💡 亮点: IoT传感器实时监控 → AI自动识别违规根因 → 生成针对性培训材料 → 班后复盘自动关联{C.END}")

            else:
                print(f"\n{C.RED}❌ 场景3 执行失败: {result.get('error', 'Unknown')}{C.END}")
                scene_result["status"] = "failed"

        except Exception as e:
            print(f"\n{C.RED}❌ 场景3 异常: {e}{C.END}")
            scene_result["status"] = "error"
            scene_result["error"] = str(e)

        self.results["scene3_sop_violation"] = scene_result
        self._delay("scene")
        return scene_result

    # ── 数据看板汇总 ────────────────────────────────────────

    def show_dashboard(self) -> Dict:
        """汇总所有场景的关键指标"""
        print_separator()
        print(f"\n{C.BOLD}{C.MAGENTA}📊 火瞳数字座舱 — 三场景关键指标汇总{C.END}")
        print_separator()

        dashboard = {
            "timestamp": datetime.now().isoformat(),
            "store": DEMO_CONFIG["store_name"],
            "scenes_summary": {},
            "total_metrics": {},
        }

        # 汇总各场景指标
        scenes = [
            ("scene1_waste_to_purchase", "废料→采购闭环"),
            ("scene2_table_service", "脏桌→服务闭环"),
            ("scene3_sop_violation", "SOP→培训闭环"),
        ]

        all_passed = True
        for scene_key, scene_name in scenes:
            scene_data = self.results.get(scene_key, {})
            status = scene_data.get("status", "unknown")
            status_emoji = "✅" if status == "completed" else ("⚠️" if status == "partial_success" else "❌")
            metrics = scene_data.get("key_metrics", {})

            print(f"\n{C.BOLD}{status_emoji} {scene_name}:{C.END}")
            if metrics:
                for k, v in metrics.items():
                    print_result(k, v)
            else:
                print(f"  {C.DIM}(无指标数据){C.END}")

            if status != "completed":
                all_passed = False

            dashboard["scenes_summary"][scene_key] = {
                "name": scene_name,
                "status": status,
                "metrics": metrics,
            }

        # 总体状态
        dashboard["total_metrics"]["all_scenes_passed"] = all_passed
        dashboard["total_metrics"]["total_scenes"] = 3
        dashboard["total_metrics"]["passed_scenes"] = sum(
            1 for s in self.results.values() if s.get("status") == "completed"
        )

        # 计算总执行时间
        if self.start_time and self.end_time:
            total_sec = (self.end_time - self.start_time).total_seconds()
            dashboard["total_metrics"]["total_execution_time_sec"] = round(total_sec, 2)

        print_separator()
        overall_status = f"{C.GREEN}全部通过 🎉{C.END}" if all_passed else f"{C.YELLOW}部分通过 ⚠️{C.END}"
        print(f"\n{C.BOLD}总体状态: {overall_status}{C.END}")

        self.results["dashboard"] = dashboard
        self._delay("summary")
        return dashboard

    # ── 收尾: ROI 总结 ─────────────────────────────────────

    def show_closing(self) -> Dict:
        """Demo 收尾：ROI 总结 + 融资亮点"""
        print_separator()
        print(f"\n{C.BOLD}{C.MAGENTA}💰 火瞳价值主张 — ROI 总结{C.END}")
        print_separator()

        closing = {
            "roi_summary": {
                "单店年节省": "≥ ¥15万",
                "节省来源": {
                    "损耗降低": "年省 ~¥8万 (损耗率从12%降至7%)",
                    "采购优化": "年省 ~¥4万 (智能预测减少积压)",
                    "人效提升": "年省 ~¥3万 (自动化减少人工工时)",
                },
                "投资回报周期": "6-8个月",
                "可复制性": "标准化部署流程，新店上线<1周",
            },
            "investment_highlights": [
                "双引擎闭环：视觉检测 + 数据预测 已在椒江店验证",
                "岗位AI助理：店长/后厨/采购 三大角色全覆盖",
                "多店管控：椒江+玉环 两店数据同屏对比",
                "真实数据：90天运营数据支撑，非概念产品",
            ],
            "contact": {
                "company": "火瞳科技",
                "product": "火瞳AI运营中台",
                "target": "火锅连锁/餐饮品牌数字化升级合作伙伴",
            }
        }

        roi = closing["roi_summary"]
        print(f"\n{C.BOLD}{C.YELLOW}💎 单店年节省: {roi['单店年节省']}{C.END}")
        print(f"\n{C.CYAN}节省来源:{C.END}")
        for source, desc in roi["节省来源"].items():
            print(f"  • {source}: {desc}")
        print(f"\n  • 投资回报周期: {roi['投资回报周期']}")
        print(f"  • 可复制性: {roi['可复制性']}")

        print(f"\n{C.CYAN}🚀 融资亮点:{C.END}")
        for i, highlight in enumerate(closing["investment_highlights"], 1):
            print(f"  {i}. {highlight}")

        print(f"\n{C.DIM}{'─' * 50}{C.END}")
        print(f"{C.BOLD}{C.GREEN}感谢观看！火瞳 — 让每一家火锅店都拥有AI超能力{C.END}")
        print(f"{C.DIM}{'═' * 50}{C.END}\n")

        self.results["closing"] = closing
        return closing

    # ── 主运行流程 ─────────────────────────────────────────

    def run_all(self) -> Dict:
        """运行完整的 Demo 流程"""
        self.start_time = datetime.now()

        print(f"\n{C.BOLD}⏱️  Demo 开始时间: {self.start_time.strftime('%H:%M:%S')}{C.END}")

        # 1. 开场
        self.show_opening()

        # 2. 场景1: 废料→采购
        self.run_scene_waste_to_purchase()

        # 3. 场景2: 脏桌→服务
        self.run_scene_table_service()

        # 4. 场景3: SOP→培训
        self.run_scene_sop_violation()

        # 5. 数据看板
        self.show_dashboard()

        # 6. 收尾
        self.show_closing()

        self.end_time = datetime.now()
        total_sec = (self.end_time - self.start_time).total_seconds()
        print(f"{C.DIM}⏱️  Demo 总耗时: {total_sec:.1f}s ({total_sec/60:.1f}分钟){C.END}")

        # 添加元数据
        self.results["_meta"] = {
            "demo_version": DEMO_CONFIG["version"],
            "start_time": self.start_time.isoformat(),
            "end_time": self.end_time.isoformat(),
            "total_duration_sec": round(total_sec, 2),
            "fast_mode": self.fast_mode,
            "store": DEMO_CONFIG["store_name"],
        }

        return self.results

    def run_single_scene(self, scene_type: str) -> Dict:
        """运行单个场景"""
        self.start_time = datetime.now()
        print_banner()

        scene_runners = {
            "waste_to_purchase": self.run_scene_waste_to_purchase,
            "table_service_loop": self.run_scene_table_service,
            "sop_violation_training": self.run_scene_sop_violation,
        }

        runner = scene_runners.get(scene_type)
        if not runner:
            print(f"{C.RED}未知场景类型: {scene_type}{C.END}")
            print(f"{C.DIM}可用场景: {', '.join(scene_runners.keys())}{C.END}")
            return {}

        result = runner()

        self.end_time = datetime.now()
        total_sec = (self.end_time - self.start_time).total_seconds()
        print(f"\n{C.DIM}⏱️  耗时: {total_sec:.1f}s{C.END}")

        return result


# ──────────────────────────────────────────────────────────────
# CLI 入口
# ──────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="火瞳 · 重庆展会 Demo 脚本 (基于 D2 Agent 协作场景)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python3 expo_demo.py                  # 运行全部 3 个场景
  python3 expo_demo.py --scene waste_to_purchase  # 仅运行场景1
  python3 expo_demo.py --fast --format json      # 快速模式 + JSON 输出
        """,
    )

    parser.add_argument(
        "--scene", "-s",
        choices=["waste_to_purchase", "table_service_loop", "sop_violation_training"],
        help="仅运行指定场景",
    )
    parser.add_argument(
        "--fast", "-f",
        action="store_true",
        help="快速模式（缩短延迟）",
    )
    parser.add_argument(
        "--format", "-o",
        choices=["terminal", "json"],
        default="terminal",
        help="输出格式 (default: terminal)",
    )

    args = parser.parse_args()

    runner = ExpoDemoRunner(fast_mode=args.fast, output_format=args.format)

    if args.scene:
        result = runner.run_single_scene(args.scene)
    else:
        result = runner.run_all()

    # JSON 输出模式
    if args.format == "json":
        print("\n" + "="*60)
        print("JSON OUTPUT:")
        print("="*60)
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
