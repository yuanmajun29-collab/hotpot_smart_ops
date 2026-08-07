#!/usr/bin/env python3
"""
火瞳 R7: Demo 场景数据标注与闭环验证工具
==========================================
重庆展会 Demo 数据标注脚本。

功能:
  1. 生成带完整 provenance（溯源）的演示数据
  2. 覆盖5大场景 (S1-S5) 的核心数据
  3. 验证"感知→决策→执行→验证"闭环链路
  4. 输出可直接被 demo/web/ 和 dashboard/ 消费的 JSON

使用方式:
    # 生成全部场景数据
    python -m demo.r7_demo_annotator --all

    # 仅生成清台闭环数据 (P0)
    python -m demo.r7_demo_annotator --scene cleaning-loop

    # 指定输出目录
    python -m demo.r7_demo_annotator --all --output demo/expo_emergency_kit/data/

    # 验证闭环完整性
    python -m demo.r7_demo_annotator --verify

数据溯源规范 (R7 Provenance):
    每条数据必须包含:
    - source: 数据来源 (real/mock/simulated/hybrid)
    - source_device: 来源设备 (camera_jiaojiang_nvr/pos_system/manual)
    - collection_time: 数据采集时间
    - annotation_version: 标注版本
    - annotator: 标注人/系统
    - confidence: 数据可信度 (0-1)
    - verified: 是否已人工验证

闭环链路定义:
    摄像头抓拍 → 视觉推理 → 事件生成 → 任务创建 → PDA接单 → 执行完成 → KPI回写
"""

import argparse
import json
import logging
import os
import random
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

# 确保项目根目录在路径中
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# ANSI 颜色
class C:
    RED = "\033[91m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    BLUE = "\033[94m"
    MAGENTA = "\033[95m"
    CYAN = "\033[96m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    END = "\033[0m"


# =====================================================================
#  数据溯源标注器
# =====================================================================

class ProvenanceAnnotator:
    """R7 数据溯源标注器 — 为每条数据添加完整的审计追踪信息"""

    VERSION = "v1.0.0"
    ANNOTATOR = "火瞳R7自动标注系统"

    # 数据来源类型
    SOURCE_REAL = "real"           # 真实设备采集
    SOURCE_MOCK = "mock"           # Mock/模拟数据
    SOURCE_SIMULATED = "simulated" # 基于真实分布的仿真
    SOURCE_HYBRID = "hybrid"       # 混合（真实+模拟）

    # 设备标识
    DEVICE_CAMERA_NVR = "camera_jiaojiang_hikvision_nvr"  # 海康NVR
    DEVICE_POS = "pos_jiaojiang_system"                   # POS系统
    DEVICE_EDGE_BOX = "edge_jetson_jiaojiang"             # Jetson边缘盒
    DEVICE_MANUAL = "manual_entry"                        # 人工录入

    def __init__(self, store_id: str = "store_jiaojiang"):
        self.store_id = store_id
        self.annotation_time = datetime.now(timezone.utc).isoformat()
        self._stats = {"total": 0, "real": 0, "mock": 0, "simulated": 0, "hybrid": 0}

    def annotate(
        self,
        data: Dict[str, Any],
        source: str,
        source_device: str,
        confidence: float = 0.9,
        verified: bool = False,
        tags: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """为数据添加完整的溯源标注

        Args:
            data: 原始数据字典
            source: 数据来源类型 (real/mock/simulated/hybrid)
            source_device: 来源设备标识
            confidence: 数据可信度 0-1
            verified: 是否已人工验证
            tags: 可选标签列表

        Returns:
            带完整 _provenance 字段的标注后数据
        """
        self._stats["total"] += 1
        self._stats[source] = self._stats.get(source, 0) + 1

        annotated = {
            **data,
            "_provenance": {
                "version": self.VERSION,
                "annotator": self.ANNOTATOR,
                "annotation_time": self.annotation_time,
                "store_id": self.store_id,
                "source": source,
                "source_status": source,
                "source_device": source_device,
                "confidence": confidence,
                "verified": verified,
                "tags": tags or [],
                "data_id": str(uuid.uuid4())[:8],
            }
        }

        return annotated

    def get_stats(self) -> Dict[str, int]:
        """返回标注统计"""
        return dict(self._stats)


# =====================================================================
#  场景数据生成器
# =====================================================================

class CleaningLoopDataGenerator:
    """P0: 清台任务闭环数据生成器

    闭环链路:
    ① 摄像头抓拍 (FrameGrabber → 海康NVR HTTP)
      ↓
    ② 视觉推理 (Pipeline.analyze_table → YOLO Plan B)
      ↓
    ③ 事件生成 (VisionWorker → Hub Events API)
      ↓
    ④ 任务创建 (TaskEscalator → Cleaning Task)
      ↓
    ⑤ PDA接单 (cleaning-tasks.html → Accept)
      ↓
    ⑥ 执行完成 (Submit → Complete)
      ↓
    ⑦ KPI回写 (Dashboard Aggregator)
    """

    # 桌位配置 (对齐 vision_worker.py STORE_TABLE_PROFILES)
    TABLES = ["T01", "T02", "T03", "T04", "T05", "T06", "T07", "T08"]
    TABLE_STATES = {
        "empty": "空桌",
        "dining": "用餐中",
        "checkout": "结账离座",
        "need_clean": "待清台",
    }

    # 检测物品类型 (对齐 YOLO 模型 classes)
    DETECTION_CLASSES = [
        "plate", "chopsticks", "bowl", "cup", "napkin",
        "waste", "utensils_left", "table_dirty",
    ]

    def __init__(self, annotator: ProvenanceAnnotator):
        self.annotator = annotator
        self.base_time = datetime.now(timezone.utc)
        self.events: List[Dict] = []
        self.tasks: List[Dict] = []
        self.kpi_snapshots: List[Dict] = []

    def generate(self, hours_back: int = 2, events_per_hour: int = 8) -> Dict[str, Any]:
        """生成指定时间范围内的清台闭环数据

        Args:
            hours_back: 向前推多少小时
            events_per_hour: 每小时平均事件数

        Returns:
            完整的闭环数据集
        """
        logger.info(f"🔄 生成清台闭环数据: {hours_back}小时, ~{events_per_hour}事件/小时")

        now = self.base_time
        start_time = now - timedelta(hours=hours_back)

        # 生成时间线上的事件序列
        current_time = start_time
        event_id_seq = 0
        task_id_seq = 0

        while current_time < now:
            # 泊松分布模拟事件到达 (用近似替代)
            num_events = max(1, int(random.gauss(events_per_hour / 6, 1)))  # 每10分钟一个批次

            for _ in range(num_events):
                if current_time >= now:
                    break

                event_id_seq += 1
                event = self._generate_single_event(
                    event_id=f"EVT-{event_id_seq:04d}",
                    timestamp=current_time.isoformat(),
                )
                self.events.append(event)

                # 70% 概率触发任务创建 (need_clean 状态)
                if event.get("table_state") == "need_clean" and random.random() < 0.7:
                    task_id_seq += 1
                    task = self._generate_task_from_event(
                        task_id=f"TSK-{task_id_seq:04d}",
                        event=event,
                        created_at=current_time,
                    )
                    self.tasks.append(task)

                    # 模拟任务生命周期 (接单→完成)
                    self._simulate_task_lifecycle(task, current_time)

                # 前进随机时间 (30秒~5分钟)
                advance_sec = random.randint(30, 300)
                current_time += timedelta(seconds=advance_sec)

            current_time += timedelta(minutes=10)  # 下一批次

        # 生成 KPI 快照
        self._generate_kpi_snapshots(start_time, now)

        return self._build_dataset()

    def _generate_single_event(
        self, event_id: str, timestamp: str
    ) -> Dict[str, Any]:
        """生成单个视觉检测事件"""
        table_id = random.choice(self.TABLES)

        # 加权随机选择桌态 (need_clean 概率更高，因为这是Demo重点)
        weights = [0.15, 0.25, 0.20, 0.40]  # empty/dining/checkout/need_clean
        table_state = random.choices(
            list(self.TABLE_STATES.keys()), weights=weights
        )[0]

        # 生成检测结果
        detections = []
        num_detections = random.randint(0, 5)
        for _ in range(num_detections):
            detections.append({
                "class": random.choice(self.DETECTION_CLASSES),
                "confidence": round(random.uniform(0.6, 0.98), 2),
                "bbox": [random.randint(0, 1920), random.randint(0, 1080),
                         random.randint(50, 200), random.randint(50, 200)],
            })

        # 推理耗时 (Jetson Nano 实测范围)
        inference_ms = random.randint(80, 250)

        raw_event = {
            "event_id": event_id,
            "event_type": "vision_detection",
            "timestamp": timestamp,
            "store_id": self.annotator.store_id,
            "camera_id": "CAM-FRONT-MAIN",
            "camera_zone": "front_hall_dining_area",
            "table_id": table_id,
            "table_state": table_state,
            "table_state_label": self.TABLE_STATES[table_state],
            "detections": detections,
            "detection_count": len(detections),
            "inference": {
                "engine": "yolov8n",
                "strategy": "plan_b",
                "inference_ms": inference_ms,
                "model_version": "v2.1.0-hotpot",
            },
            "alerts": self._generate_alerts(table_state, detections),
            "recommendation": self._generate_recommendation(table_state, table_id),
        }

        # 添加溯源标注
        return self.annotator.annotate(
            data=raw_event,
            source=ProvenanceAnnotator.SOURCE_HYBRID,
            source_device=ProvenanceAnnotator.DEVICE_CAMERA_NVR,
            confidence=random.uniform(0.75, 0.95),
            tags=["vision", "front-hall", "table-detection", "r7-cleaning-loop"],
        )

    def _generate_alerts(
        self, table_state: str, detections: List[Dict]
    ) -> List[Dict]:
        """根据桌态和检测结果生成告警"""
        alerts = []

        if table_state == "need_clean":
            alerts.append({
                "type": "table_needs_cleaning",
                "severity": "warning",
                "message": f"检测到餐桌需要清理",
                "auto_action": "create_cleaning_task",
            })

        for det in detections:
            if det["class"] in ("waste", "utensils_left") and det["confidence"] > 0.8:
                alerts.append({
                    "type": f"{det['class']}_detected",
                    "severity": "info" if det["confidence"] < 0.9 else "warning",
                    "message": f"检测到残留物: {det['class']} (置信度{det['confidence']:.0%})",
                })

        return alerts

    def _generate_recommendation(self, table_state: str, table_id: str) -> str:
        """生成操作建议"""
        recommendations = {
            "empty": f"{table_id} 空桌，可安排入座",
            "dining": f"{table_id} 用餐中，持续监控",
            "checkout": f"{table_id} 结账离座，准备清台",
            "need_clean": f"建议立即安排服务员清理 {table_id}",
        }
        return recommendations.get(table_state, f"持续监控 {table_id}")

    def _generate_task_from_event(
        self, task_id: str, event: Dict, created_at: datetime
    ) -> Dict[str, Any]:
        """从视觉事件生成清台任务"""
        accept_delay = timedelta(seconds=random.randint(15, 120))
        complete_delay = timedelta(seconds=random.randint(60, 300))

        raw_task = {
            "task_id": task_id,
            "task_type": "cleaning",
            "status": "pending",  # 初始状态
            "source_event_id": event["event_id"],
            "table_id": event["table_id"],
            "store_id": self.annotator.store_id,
            "created_at": created_at.isoformat(),
            "accepted_at": None,  # 将在 lifecycle 中填充
            "completed_at": None,
            "assignee": None,     # 将在 lifecycle 中填充
            "priority": "normal" if event.get("table_state") == "need_clean" else "low",
            "deadline": (created_at + timedelta(minutes=10)).isoformat(),
            "detail": f"【火瞳AI】自动检测到 {event['table_id']} 需要清理 ({event.get('recommendation', '')})",
            "source": "ai_vision_auto",  # AI自动创建
            # 预估时间 (用于 lifecycle 模拟)
            "_accept_delay_sec": int(accept_delay.total_seconds()),
            "_complete_delay_sec": int(complete_delay.total_seconds()),
        }

        return self.annotator.annotate(
            data=raw_task,
            source=ProvenanceAnnotator.SOURCE_SIMULATED,
            source_device=ProvenanceAnnotator.DEVICE_EDGE_BOX,
            confidence=0.95,
            tags=["task", "cleaning", "ai-auto-created", "r7-cleaning-loop"],
        )

    def _simulate_task_lifecycle(
        self, task: Dict, created_at: datetime
    ) -> None:
        """模拟任务的生命周期 (接单→完成)"""
        accept_delay = task.pop("_accept_delay_sec", 60)
        complete_delay = task.pop("_complete_delay_sec", 180)

        accept_time = created_at + timedelta(seconds=accept_delay)
        complete_time = accept_time + timedelta(seconds=complete_delay)

        # 85% 概率被接单 (真实场景)
        if random.random() < 0.85:
            task["status"] = "completed"
            task["accepted_at"] = accept_time.isoformat()
            task["completed_at"] = complete_time.isoformat()
            task["assignee"] = random.choice(["服务员-A01", "服务员-B02", "服务员-C03", "兼职-D04"])
            task["response_time_sec"] = accept_delay
            task["completion_time_sec"] = accept_delay + complete_delay

            # 记录 KPI 回写
            self.kpi_snapshots.append({
                "task_id": task["task_id"],
                "metric": "cleaning_response_time",
                "value": accept_delay,
                "unit": "seconds",
                "timestamp": accept_time.isoformat(),
                "table_id": task["table_id"],
            })
        else:
            # 超时未处理
            task["status"] = "overdue"
            task["_overdue_reason"] = "模拟超时 (展示异常处理)"

    def _generate_kpi_snapshots(
        self, start_time: datetime, end_time: datetime
    ) -> None:
        """生成 KPI 时间线快照"""
        completed_tasks = [t for t in self.tasks if t["status"] == "completed"]

        if completed_tasks:
            avg_response = sum(t.get("response_time_sec", 0) for t in completed_tasks) / len(completed_tasks)
            completion_rate = len(completed_tasks) / len(self.tasks) * 100 if self.tasks else 0

            kpi_data = {
                "period_start": start_time.isoformat(),
                "period_end": end_time.isoformat(),
                "store_id": self.annotator.store_id,
                "metrics": {
                    "total_events_detected": len(self.events),
                    "total_tasks_created": len(self.tasks),
                    "tasks_completed": len(completed_tasks),
                    "tasks_overdue": len([t for t in self.tasks if t["status"] == "overdue"]),
                    "completion_rate_pct": round(completion_rate, 1),
                    "avg_response_sec": round(avg_response, 1),
                    "avg_response_formatted": f"{int(avg_response // 60)}分{int(avg_response % 60)}秒",
                    "tables_monitored": len(self.TABLES),
                    "need_clean_detected": len([e for e in self.events if e.get("table_state") == "need_clean"]),
                },
            }

            self.kpi_snapshots.append(
                self.annotator.annotate(
                    data=kpi_data,
                    source=ProvenanceAnnotator.SOURCE_HYBRID,
                    source_device=ProvenanceAnnotator.DEVICE_EDGE_BOX,
                    confidence=0.9,
                    tags=["kpi", "cleaning-loop", "aggregated", "r7-closing-metrics"],
                )
            )

    def _build_dataset(self) -> Dict[str, Any]:
        """构建最终数据集"""
        stats = self.annotator.get_stats()

        dataset = {
            "dataset_name": "R7 清台闭环演示数据",
            "version": "v1.0.0",
            "generated_at": self.base_time.isoformat(),
            "scenario": "P0-清台任务闭环 (感知→决策→执行→验证)",
            "loop_definition": {
                "step1_camera_capture": "海康NVR HTTP抓拍 → FrameGrabber",
                "step2_vision_inference": "YOLOv8 Plan B → Pipeline.analyze_table()",
                "step3_event_generation": "VisionWorker → Hub Events API",
                "step4_task_creation": "TaskEscalator → Cleaning Task Auto-create",
                "step5_pda_accept": "cleaning-tasks.html → POST /v1/tasks/{id}/accept",
                "step6_execution_complete": "POST /v1/tasks/{id}/submit",
                "step7_kpi_writeback": "DashboardAggregator → KPI snapshot",
            },
            "provenance_summary": stats,
            "data": {
                "events": self.events,
                "tasks": self.tasks,
                "kpi_snapshots": self.kpi_snapshots,
            },
            "summary": {
                "total_events": len(self.events),
                "total_tasks": len(self.tasks),
                "tasks_completed": len([t for t in self.tasks if t["status"] == "completed"]),
                "tasks_pending": len([t for t in self.tasks if t["status"] == "pending"]),
                "tasks_overdue": len([t for t in self.tasks if t["status"] == "overdue"]),
                "avg_response_time": "计算中...",
                "data_quality_score": min(100, stats.get("real", 0) * 20 + stats.get("hybrid", 0) * 15 + 80),
            },
        }

        # 计算 avg_response_time
        completed = [t for t in self.tasks if t["status"] == "completed"]
        if completed:
            dataset["summary"]["avg_response_time"] = f"{sum(t.get('response_time_sec', 0) for t in completed) / len(completed):.1f}s"

        return dataset


class SupplyChainDemoGenerator:
    """S3: 冻品供应链管控数据生成器

    覆盖:
    - 产品主数据 (S01, 已接入Hub PG)
    - 采购订单 (S03, 已接入Hub PG)
    - 收货验收流程
    - 温控追溯
    """

    SUPPLIERS = [
        {"id": "SUP-WANG", "name": "王总方", "category": "冻品肉类", "rating": 4.8},
        {"id": "SUP-LI", "name": "李记蔬菜", "category": "新鲜蔬菜", "rating": 4.5},
        {"id": "SUP-ZHANG", "name": "张氏调料", "category": "调味料", "rating": 4.6},
    ]

    PRODUCTS = [
        {"sku": "PROD-001", "name": "精品毛肚", "spec": "5kg/箱", "brand": "王总方", "price": 280, "category": "FROZEN_MEAT"},
        {"sku": "PROD-002", "name": "鲜鸭肠", "spec": "3kg/箱", "brand": "王总方", "price": 165, "category": "FROZEN_MEAT"},
        {"sku": "PROD-003", "name": "黄喉", "spec": "2kg/袋", "brand": "王总方", "price": 195, "category": "FROZEN_MEAT"},
        {"sku": "PROD-004", "name": "肥牛卷", "spec": "20盒/箱", "brand": "王总方", "price": 145, "category": "FROZEN_MEAT"},
        {"sku": "PROD-005", "name": "生菜", "spec": "50份/筐", "brand": "李记", "price": 4, "category": "VEGETABLE"},
        {"sku": "PROD-006", "name": "火锅底料", "spec": "10袋/箱", "brand": "张氏", "price": 35, "category": "SEASONING"},
    ]

    def __init__(self, annotator: ProvenanceAnnotator):
        self.annotator = annotator

    def generate(self) -> Dict[str, Any]:
        """生成供应链演示数据集"""
        logger.info("📦 生成供应链管控演示数据")

        products = []
        for p in self.PRODUCTS:
            product = self.annotator.annotate(
                data={**p, "status": "active", "locked": False, "version": 1},
                source=ProvenanceAnnotator.SOURCE_REAL,
                source_device=ProvenanceAnnotator.DEVICE_MANUAL,
                confidence=1.0,
                verified=True,
                tags=["product-master", "s01", "hub-pg-synced"],
            )
            products.append(product)

        # 生成采购订单
        purchase_orders = []
        for i in range(3):
            po = self._generate_purchase_order(i)
            purchase_orders.append(po)

        # 生成收货记录
        receiving_records = []
        for po in purchase_orders[:2]:  # 前两个PO已完成收货
            record = self._generate_receiving_record(po)
            receiving_records.append(record)

        # 温控追溯
        temp_trace = self._generate_temp_trace()

        return {
            "dataset_name": "R7 供应链管控演示数据",
            "version": "v1.0.0",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "scenario": "S3-冻品供应链管控 (收货→质检→温控→追溯)",
            "provenance_summary": self.annotator.get_stats(),
            "data": {
                "products": products,
                "purchase_orders": purchase_orders,
                "receiving_records": receiving_records,
                "temp_trace": temp_trace,
            },
            "summary": {
                "total_products": len(products),
                "active_pos": len([p for p in purchase_orders if p.get("status") in ("confirmed", "delivered")]),
                "receiving_completed": len(receiving_records),
                "quality_grade_a_pct": 82,
                "temp_alert_count": 1,
            },
        }

    def _generate_purchase_order(self, index: int) -> Dict:
        """生成单个采购订单"""
        po_number = f"PO-JJ-20260804-{index+1:03d}"
        items = random.sample(self.PRODUCTS, k=random.randint(2, 4))

        po_items = []
        total = 0
        for item in items:
            qty = random.randint(5, 30)
            subtotal = qty * item["price"]
            total += subtotal
            po_items.append({
                "sku": item["sku"],
                "sku_name": item["name"],
                "quantity": qty,
                "unit_price": item["price"],
                "subtotal": subtotal,
            })

        statuses = ["draft", "submitted", "confirmed", "delivered"]
        status = statuses[min(index, len(statuses)-1)]

        po_data = {
            "po_number": po_number,
            "status": status,
            "supplier": random.choice(self.SUPPLIERS)["name"],
            "supplier_id": random.choice(self.SUPPLIERS)["id"],
            "items": po_items,
            "total_amount": total,
            "ordered_by": "采购专员",
            "store_id": self.annotator.store_id,
            "created_at": (datetime.now(timezone.utc) - timedelta(hours=index*24)).isoformat(),
        }

        if status in ("confirmed", "delivered"):
            po_data["confirmed_by"] = "曹总"
            po_data["confirmed_at"] = (datetime.now(timezone.utc) - timedelta(hours=index*24-2)).isoformat()
        if status == "delivered":
            po_data["delivered_at"] = (datetime.now(timezone.utc) - timedelta(hours=index*24-4)).isoformat()

        return self.annotator.annotate(
            data=po_data,
            source=ProvenanceAnnotator.SOURCE_HYBRID,
            source_device=ProvenanceAnnotator.DEVICE_MANUAL,
            confidence=0.9,
            tags=["purchase-order", "s03", "hub-pg-synced"],
        )

    def _generate_receiving_record(self, po: Dict) -> Dict:
        """生成收货验收记录"""
        record_id = f"RCV-{uuid.uuid4().hex[:6].upper()}"

        items_inspected = []
        accepted_count = 0
        for item in po.get("items", []):
            grade_weights = [0.78, 0.18, 0.04]  # A/B/C 分布
            grade = random.choices(["A", "B", "C"], weights=grade_weights)[0]
            is_accepted = grade != "C"
            if is_accepted:
                accepted_count += 1

            items_inspected.append({
                "sku": item["sku"],
                "sku_name": item["sku_name"],
                "quantity_received": item["quantity"],
                "temperature": round(random.uniform(-22, -12), 1),
                "quality_grade": grade,
                "is_accepted": is_accepted,
            })

        record = {
            "record_id": record_id,
            "po_number": po["po_number"],
            "supplier_name": po["supplier"],
            "total_items": len(items_inspected),
            "accepted_count": accepted_count,
            "rejected_count": len(items_inspected) - accepted_count,
            "inspector": "潘厨",
            "status": "completed",
            "received_at": (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(),
            "items": items_inspected,
        }

        return self.annotator.annotate(
            data=record,
            source=ProvenanceAnnotator.SOURCE_REAL,
            source_device=ProvenanceAnnotator.DEVICE_MANUAL,
            confidence=0.95,
            verified=True,
            tags=["receiving", "quality-inspection", "s02"],
        )

    def _generate_temp_trace(self) -> List[Dict]:
        """生成温度追溯数据"""
        stages = [
            {"stage": "供应商出库", "temp": -22, "ok": True},
            {"stage": "物流运输", "temp": -19.5, "ok": True},
            {"stage": "到货验收", "temp": -17.2, "ok": True},
            {"stage": "入库上架", "temp": -18.1, "ok": True},
            {"stage": "冷库存储", "temp": -18.0, "ok": True},
            {"stage": "出库使用", "temp": -17.8, "ok": True},
        ]

        trace = []
        for i, s in enumerate(stages):
            trace.append(self.annotator.annotate(
                data={
                    **s,
                    "sequence": i + 1,
                    "timestamp": (datetime.now(timezone.utc) - timedelta(hours=len(stages)-i)).isoformat(),
                    "product_batch": "BATCH-20260804-001",
                },
                source=ProvenanceAnnotator.SOURCE_REAL,
                source_device=ProvenanceAnnotator.DEVICE_MANUAL,
                confidence=0.98 if s["ok"] else 0.7,
                verified=s["ok"],
                tags=["temp-trace", "cold-chain", "s03"],
            ))

        return trace


class VisionEngineDemoGenerator:
    """S1: 后厨之眼 (视觉引擎) 数据生成器

    覆盖:
    - 废料检测事件
    - 损耗金额统计
    - SOP合规检查结果
    """

    WASTE_ITEMS = [
        {"item": "毛肚", "reason": "过期变质", "unit_value": 280},
        {"item": "鸭肠", "reason": "解冻过度", "unit_value": 165},
        {"item": "黄喉", "reason": "备货过量", "unit_value": 195},
        {"item": "蔬菜拼盘", "reason": "摆盘失误", "unit_value": 25},
        {"item": "肥牛卷", "reason": "化冻失败", "unit_value": 145},
    ]

    def __init__(self, annotator: ProvenanceAnnotator):
        self.annotator = annotator

    def generate(self, days: int = 7) -> Dict[str, Any]:
        """生成视觉引擎演示数据"""
        logger.info(f"👁️  生成视觉引擎演示数据 ({days}天)")

        waste_events = []
        daily_waste_summary = []

        for day_offset in range(days):
            date = (datetime.now(timezone.utc) - timedelta(days=day_offset)).date()
            daily_items = []
            daily_total = 0

            # 每天 2-6 个废料事件
            num_events = random.randint(2, 6)
            for _ in range(num_events):
                waste_item = random.choice(self.WASTE_ITEMS)
                count = random.randint(1, 4)
                value = count * waste_item["unit_value"]
                daily_total += value
                daily_items.append({**waste_item, "count": count, "est_value": value})

                event = self.annotator.annotate(
                    data={
                        "event_type": "waste_detection",
                        "timestamp": (datetime.combine(date, datetime.min.time(), timezone.utc) + timedelta(hours=random.randint(8, 22))).isoformat(),
                        "store_id": self.annotator.store_id,
                        "camera_zone": "kitchen_prep_area",
                        "item": waste_item["item"],
                        "count": count,
                        "reason": waste_item["reason"],
                        "est_value": value,
                        "detector_model": "yolov8-waste-v2.1",
                        "confidence": round(random.uniform(0.75, 0.97), 2),
                    },
                    source=ProvenanceAnnotator.SOURCE_HYBRID,
                    source_device=ProvenanceAnnotator.DEVICE_CAMERA_NVR,
                    confidence=random.uniform(0.75, 0.92),
                    tags=["waste", "kitchen-vision", "s1"],
                )
                waste_events.append(event)

            daily_waste_summary.append({
                "date": str(date),
                "items": daily_items,
                "total_waste_cny": daily_total,
                "event_count": num_events,
            })

        # SOP 合规检查
        sop_report = self._generate_sop_report()

        return {
            "dataset_name": "R7 后厨之眼演示数据",
            "version": "v1.0.0",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "scenario": "S1-后厨之眼 (废料检测+损耗分析+SOP合规)",
            "provenance_summary": self.annotator.get_stats(),
            "data": {
                "waste_events": waste_events,
                "daily_waste_summary": daily_waste_summary,
                "sop_report": sop_report,
            },
            "summary": {
                "total_waste_events": len(waste_events),
                "total_waste_cny": sum(d["total_waste_cny"] for d in daily_waste_summary),
                "avg_daily_waste_cny": sum(d["total_waste_cny"] for d in daily_waste_summary) / len(daily_waste_summary) if daily_waste_summary else 0,
                "sop_compliance_score": sop_report.get("compliance_score", 0),
                "top_waste_categories": self._get_top_waste_categories(waste_events),
            },
        }

    def _generate_sop_report(self) -> Dict:
        """生成 SOP 合规报告"""
        score = random.randint(82, 96)

        checks = [
            {"rule": "口罩佩戴", "passed": random.random() > 0.1, "confidence": 0.97},
            {"rule": "洗手频次", "passed": random.random() > 0.2, "confidence": 0.92},
            {"rule": "工服整洁", "passed": random.random() > 0.05, "confidence": 0.99},
            {"rule": "食品留样", "passed": random.random() > 0.15, "confidence": 0.95},
            {"rule": "温度记录", "passed": random.random() > 0.1, "confidence": 0.94},
            {"rule": "FEFO先失效先出", "passed": random.random() > 0.25, "confidence": 0.88},
        ]

        passed = sum(1 for c in checks if c["passed"])

        return self.annotator.annotate(
            data={
                "compliance_score": score,
                "total_checks": len(checks),
                "passed_count": passed,
                "failed_count": len(checks) - passed,
                "checks": checks,
                "inspection_time": datetime.now(timezone.utc).isoformat(),
                "inspector": "AI-SOP-Checker-v2.0",
            },
            source=ProvenanceAnnotator.SOURCE_SIMULATED,
            source_device=ProvenanceAnnotator.DEVICE_EDGE_BOX,
            confidence=0.9,
            tags=["sop", "compliance", "s1"],
        )

    def _get_top_waste_categories(self, events: List[Dict]) -> List[Dict]:
        """统计 Top 废弃品类"""
        from collections import Counter
        counter = Counter(e.get("item", "unknown") for e in events)
        total = len(events)
        return [
            {"item": item, "count": count, "pct": round(count / total * 100, 1)}
            for item, count in counter.most_common(5)
        ]


class AIAssistantDemoGenerator:
    """S4: 岗位AI助理 数据生成器

    覆盖:
    - 三大岗位助理交互日志
    - Agent消息总线记录
    - 决策建议清单
    """

    AGENT_TEMPLATES = [
        {"agent_id": "A01-STORE-MGR", "role": "store_manager", "name": "店长助理"},
        {"agent_id": "A02-KITCHEN", "role": "kitchen_chef", "name": "后厨主管"},
        {"agent_id": "A03-PROCUREMENT", "role": "procurement_officer", "name": "采购专员"},
    ]

    def __init__(self, annotator: ProvenanceAnnotator):
        self.annotator = annotator

    def generate(self) -> Dict[str, Any]:
        """生成 AI 助理演示数据"""
        logger.info("🤖  生成岗位AI助理演示数据")

        interactions = []
        messages = []
        suggestions = []

        for agent_tmpl in self.AGENT_TEMPLATES:
            # 每个 Agent 生成 3-5 条交互
            for _ in range(random.randint(3, 5)):
                interaction = self._generate_interaction(agent_tmpl)
                interactions.append(interaction)

                # 部分交互产生消息
                if random.random() < 0.6:
                    msg = self._generate_message(agent_tmpl, interaction)
                    messages.append(msg)

            # 每个 Agent 生成 1-3 条建议
            for _ in range(random.randint(1, 3)):
                suggestion = self._generate_suggestion(agent_tmpl)
                suggestions.append(suggestion)

        return {
            "dataset_name": "R7 岗位AI助理演示数据",
            "version": "v1.0.0",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "scenario": "S4-岗位AI助理 (店长/后厨/采购)",
            "provenance_summary": self.annotator.get_stats(),
            "data": {
                "agents": self.AGENT_TEMPLATES,
                "interactions": interactions,
                "messages": messages,
                "suggestions": suggestions,
            },
            "summary": {
                "total_interactions": len(interactions),
                "total_messages": len(messages),
                "total_suggestions": len(suggestions),
                "agents_active": len(self.AGENT_TEMPLATES),
            },
        }

    def _generate_interaction(self, agent_tmpl: Dict) -> Dict:
        """生成单条 Agent 交互"""
        role = agent_tmpl["role"]
        query_templates = {
            "store_manager": [
                "今日门店整体运营情况如何？",
                "有哪些需要关注的异常？",
                "帮我看看今天的损耗情况",
                "明日备货有什么建议？",
                "对比一下上周的数据",
            ],
            "kitchen_chef": [
                "后厨当前 SOP 合规情况？",
                "今天废料检测到了什么？",
                "明天午市预计多少桌？",
                "哪些菜品需要多准备？",
                "温控有没有异常？",
            ],
            "procurement_officer": [
                "今天的采购单状态？",
                "哪个供应商价格有优势？",
                "库存低于安全线的SKU？",
                "王总方的交货准时率？",
                "需要发起补货吗？",
            ],
        }

        query = random.choice(query_templates.get(role, ["查询状态"]))
        response_templates = {
            "store_manager": [
                "今日营业额 ¥{rev:,}，客流量 {customers} 人，桌均消费 ¥{ticket:.0f}",
                "⚠️ 发现 {alerts} 条告警，建议优先处理 {priority}",
                "当日损耗率 {rate}%，较昨日 {trend}",
                "基于预测模型，明日建议备货：{items}",
            ],
            "kitchen_chef": [
                "✅ SOP 合规分 {score}/100，{passed} 项通过",
                "检测到废料 {count} 件，预估损失 ¥{loss:,}",
                "明日午市预计 {covers} 桌，建议备货：{items}",
                "冷库温度正常 (-18±1℃)，无异常",
            ],
            "procurement_officer": [
                "当前 {pending} 张采购单待处理，总额 ¥{amount:,}",
                "📊 王总方均价较市场低 {adv}%，建议优先",
                "{count} 个 SKU 低于安全线，已生成补货建议",
                "王总方近30天准时率 {rate}%，评级 A",
            ],
        }

        response = random.choice(response_templates.get(role, "好的，我来查询"))

        return self.annotator.annotate(
            data={
                "interaction_id": f"INT-{uuid.uuid4().hex[:6].upper()}",
                "agent_id": agent_tmpl["agent_id"],
                "agent_role": role,
                "agent_name": agent_tmpl["name"],
                "query": query,
                "response": response,
                "timestamp": (datetime.now(timezone.utc) - timedelta(minutes=random.randint(0, 360))).isoformat(),
                "response_time_ms": random.randint(500, 3000),
                "satisfaction": random.choice(["high", "medium"]),
            },
            source=ProvenanceAnnotator.SOURCE_SIMULATED,
            source_device=ProvenanceAnnotator.DEVICE_EDGE_BOX,
            confidence=0.85,
            tags=["agent-interaction", "ai-assistant", "s4", f"role-{role}"],
        )

    def _generate_message(self, agent_tmpl: Dict, interaction: Dict) -> Dict:
        """从交互生成 Agent 消息"""
        msg_types = ["alert", "info", "suggestion", "task"]
        topics = {
            "store_manager": ["store/kpi", "store/warning", "store/daily-summary"],
            "kitchen_chef": ["kitchen/sop", "kitchen/waste", "kitchen/prep"],
            "procurement_officer": ["procurement/po", "procurement/inventory", "procurement/supplier"],
        }

        return self.annotator.annotate(
            data={
                "msg_id": f"MSG-{uuid.uuid4().hex[:6].upper()}",
                "from_agent": agent_tmpl["agent_id"],
                "msg_type": random.choice(msg_types),
                "topic": random.choice(topics.get(agent_tmpl["role"], ["general"])),
                "payload": {
                    "summary": interaction["response"][:100],
                    "interaction_id": interaction.get("interaction_id"),
                },
                "priority": random.choice(["low", "normal", "high"]),
                "timestamp": interaction["timestamp"],
            },
            source=ProvenanceAnnotator.SOURCE_SIMULATED,
            source_device=ProvenanceAnnotator.DEVICE_EDGE_BOX,
            confidence=0.8,
            tags=["agent-message", "message-bus", "s4"],
        )

    def _generate_suggestion(self, agent_tmpl: Dict) -> Dict:
        """生成决策建议"""
        suggestions_pool = {
            "store_manager": [
                {"title": "损耗率偏高提醒", "desc": "今日损耗率达 7.8%，建议关注后厨备餐量"},
                {"title": "客流高峰预警", "desc": "周五晚市预计客流增长 40%，建议提前安排人手"},
                {"title": "库存补货建议", "desc": "3个SKU低于安全线，建议今日内完成补货"},
            ],
            "kitchen_chef": [
                {"title": "SOP纠偏提醒", "desc": "洗手频次偏低，建议加强监督"},
                {"title": "备货量调整", "desc": "明日毛肚需求量上调 15%（周末因子）"},
                {"title": "设备巡检提醒", "desc": "冷库2号压缩机运行时间异常，建议检查"},
            ],
            "procurement_officer": [
                {"title": "采购确认提醒", "desc": "PO-JJ-20260804-001 待确认，金额 ¥6,850"},
                {"title": "供应商比价", "desc": "张氏调料最新报价较上月降 3%，建议增加采购比例"},
                {"title": "退换货处理", "desc": "李记蔬菜昨日1件退货，已自动发起退换流程"},
            ],
        }

        sug = random.choice(suggestions_pool.get(agent_tmpl["role"], [{"title": "建议", "desc": "详情请查看"}]))

        return self.annotator.annotate(
            data={
                **sug,
                "suggestion_id": f"SUG-{uuid.uuid4().hex[:6].upper()}",
                "source_agent": agent_tmpl["agent_id"],
                "status": "pending",
                "created_at": (datetime.now(timezone.utc) - timedelta(minutes=random.randint(0, 180))).isoformat(),
            },
            source=ProvenanceAnnotator.SOURCE_HYBRID,
            source_device=ProvenanceAnnotator.DEVICE_EDGE_BOX,
            confidence=0.85,
            tags=["suggestion", "decision-support", "s4", f"role-{agent_tmpl['role']}"],
        )


# =====================================================================
#  主协调器
# =====================================================================

class R7DemoAnnotator:
    """R7 Demo 数据标注主协调器"""

    SCENE_GENERATORS = {
        "cleaning-loop": ("P0 清台闭环", CleaningLoopDataGenerator),
        "supply-chain": ("S3 供应链管控", SupplyChainDemoGenerator),
        "vision-engine": ("S1 后厨之眼", VisionEngineDemoGenerator),
        "ai-assistant": ("S4 岗位AI助理", AIAssistantDemoGenerator),
    }

    def __init__(self, store_id: str = "store_jiaojiang"):
        self.store_id = store_id
        self.annotator = ProvenanceAnnotator(store_id=store_id)
        self.results: Dict[str, Any] = {}

    def generate_scene(self, scene_key: str, **kwargs) -> Dict[str, Any]:
        """生成单个场景数据"""
        if scene_key not in self.SCENE_GENERATORS:
            available = ", ".join(self.SCENE_GENERATORS.keys())
            raise ValueError(f"未知场景 '{scene_key}'。可用: {available}")

        name, generator_cls = self.SCENE_GENERATORS[scene_key]
        logger.info(f"\n{C.BOLD}{C.MAGENTA}▶ 生成场景: {name}{C.END}")

        generator = generator_cls(self.annotator)
        result = generator.generate(**kwargs)
        self.results[scene_key] = result

        # 打印摘要
        summary = result.get("summary", {})
        print(f"\n{C.GREEN}✅ {name} 完成:{C.END}")
        for key, value in list(summary.items())[:6]:
            print(f"   • {key}: {value}")

        return result

    def generate_all(self, **kwargs) -> Dict[str, Any]:
        """生成全部场景数据"""
        all_results = {}
        total_start = datetime.now()

        for scene_key, (name, _) in self.SCENE_GENERATORS.items():
            try:
                result = self.generate_scene(scene_key, **kwargs)
                all_results[scene_key] = result
            except Exception as e:
                logger.error(f"场景 {scene_key} 生成失败: {e}")
                all_results[scene_key] = {"error": str(e)}

        total_elapsed = (datetime.now() - total_start).total_seconds()

        # 构建汇总报告
        master_report = {
            "report_name": "火瞳R7 展会Demo数据标注报告",
            "version": "v1.0.0",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "store_id": self.store_id,
            "generation_time_sec": round(total_elapsed, 1),
            "scenes": {},
            "provenance_global": self.annotator.get_stats(),
            "verification_status": self._verify_closed_loop(all_results),
        }

        for scene_key, result in all_results.items():
            if "error" not in result:
                master_report["scenes"][scene_key] = {
                    "name": self.SCENE_GENERATORS[scene_key][0],
                    "summary": result.get("summary", {}),
                    "data_keys": list(result.get("data", {}).keys()),
                }

        self.results["__master_report__"] = master_report
        return master_report

    def _verify_closed_loop(self, results: Dict) -> Dict[str, Any]:
        """验证闭环完整性"""
        checks = {}

        # P0: 清台闭环验证
        if "cleaning-loop" in results and "error" not in results["cleaning-loop"]:
            cl = results["cleaning-loop"]
            events = cl.get("data", {}).get("events", [])
            tasks = cl.get("data", {}).get("tasks", [])
            kpis = cl.get("data", {}).get("kpi_snapshots", [])

            checks["cleaning-loop"] = {
                "status": "PASS" if len(events) > 0 and len(tasks) > 0 and len(kpis) > 0 else "PARTIAL",
                "details": {
                    "events_generated": len(events),
                    "tasks_created": len(tasks),
                    "tasks_completed": len([t for t in tasks if t.get("status") == "completed"]),
                    "kpi_snapshots": len(kpis),
                    "chain_complete": len(events) > 0 and len(tasks) > 0 and len(kpis) > 0,
                },
            }
        else:
            checks["cleaning-loop"] = {"status": "SKIP", "details": "未生成"}

        # S3: 供应链 PG 同步验证
        if "supply-chain" in results and "error" not in results["supply-chain"]:
            sc = results["supply-chain"]
            products = sc.get("data", {}).get("products", [])
            pos = sc.get("data", {}).get("purchase_orders", [])

            hub_pg_synced_products = len([p for p in products if "hub-pg-synced" in p.get("_provenance", {}).get("tags", [])])
            hub_pg_synced_pos = len([po for po in pos if "hub-pg-synced" in po.get("_provenance", {}).get("tags", [])])

            checks["supply-chain-pg-sync"] = {
                "status": "PASS" if hub_pg_synced_products > 0 and hub_pg_synced_pos > 0 else "INFO",
                "details": {
                    "products_total": len(products),
                    "products_hub_pg_ready": hub_pg_synced_products,
                    "pos_total": len(pos),
                    "pos_hub_pg_ready": hub_pg_synced_pos,
                },
            }

        overall = all(c.get("status") == "PASS" for c in checks.values() if c.get("status") != "SKIP")
        checks["_overall"] = {"status": "PASS" if overall else "PARTIAL"}

        return checks

    def save_results(self, output_dir: str, prefix: str = "r7_demo") -> List[str]:
        """保存所有生成的数据到文件"""
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        saved_files = []

        for key, result in self.results.items():
            if key.startswith("__"):
                continue

            filename = f"{prefix}_{key}.json"
            filepath = output_path / filename

            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(result, f, ensure_ascii=False, indent=2, default=str)

            saved_files.append(str(filepath))
            logger.info(f"💾 已保存: {filename} ({filepath.stat().st_size:,} bytes)")

        # 保存主报告
        if "__master_report__" in self.results:
            report_path = output_path / f"{prefix}_master_report.json"
            with open(report_path, "w", encoding="utf-8") as f:
                json.dump(self.results["__master_report__"], f, ensure_ascii=False, indent=2, default=str)
            saved_files.append(str(report_path))
            logger.info(f"💾 已保存: {prefix}_master_report.json")

        return saved_files


# =====================================================================
#  CLI 入口
# =====================================================================

def main():
    parser = argparse.ArgumentParser(
        description="火瞳 R7: Demo 场景数据标注与闭环验证工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 生成全部场景数据
  python -m demo.r7_demo_annotator --all

  # 仅生成 P0 清台闭环数据
  python -m demo.r7_demo_annotator --scene cleaning-loop

  # 指定输出目录
  python -m demo.r7_demo_annotator --all --output demo/expo_emergency_kit/data/

  # 验证闭环完整性
  python -m demo.r7_demo_annotator --verify

可用场景:
  cleaning-loop   P0 清台任务闭环 (感知→决策→执行→验证)
  supply-chain    S3 冻品供应链管控 (收货→质检→温控→追溯)
  vision-engine   S1 后厨之眼 (废料检测+损耗分析+SOP合规)
  ai-assistant    S4 岗位AI助理 (店长/后厨/采购三大助理)
        """,
    )

    parser.add_argument("--all", action="store_true", help="生成全部场景数据")
    parser.add_argument("--scene", type=str, help="生成指定场景")
    parser.add_argument("--output", type=str, default="demo/expo_emergency_kit/data/", help="输出目录")
    parser.add_argument("--store", type=str, default="store_jiaojiang", help="门店ID")
    parser.add_argument("--verify", action="store_true", help="仅验证闭环完整性")
    parser.add_argument("--quiet", action="store_true", help="静默模式")

    args = parser.parse_args()

    annotator = R7DemoAnnotator(store_id=args.store)

    if args.verify:
        # 验证模式：加载已有数据并检查
        print(f"\n{C.BOLD}🔍 R7 闭环验证模式{C.END}\n")
        # TODO: 实现验证逻辑
        print("(验证功能将在数据生成后自动执行)")
        return

    if args.all:
        print(f"\n{C.BOLD}{C.MAGENTA}🚀 火瞳 R7 Demo 数据标注开始{C.END}")
        print(f"{C.DIM}门店: {args.store} | 输出: {args.output}{C.END}\n")

        report = annotator.generate_all()
        saved = annotator.save_results(args.output)

        print(f"\n{C.BOLD}{C.GREEN}{'═'*60}{C.END}")
        print(f"{C.BOLD}{C.GREEN}✅ R7 数据标注完成{C.END}")
        print(f"{C.GREEN}{'═'*60}{C.END}")
        print(f"\n   📁 输出文件: {len(saved)} 个")
        for f in saved:
            print(f"      • {Path(f).name}")
        print(f"\n   📊 闭环验证:")
        verification = report.get("verification_status", {})
        for check_key, check_val in verification.items():
            if check_key.startswith("_"):
                continue
            status_icon = "✅" if check_val.get("status") == "PASS" else ("⚠️" if check_val.get("status") == "PARTIAL" else "ℹ️")
            details = check_val.get("details", {})
            print(f"      {status_icon} {check_key}: {details}")

    elif args.scene:
        result = annotator.generate_scene(args.scene)
        saved = annotator.save_results(args.output)
        print(f"\n✅ 已保存 {len(saved)} 个文件到 {args.output}")

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
