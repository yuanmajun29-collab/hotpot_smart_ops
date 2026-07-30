"""
火瞳展会 Demo 运行器
===================
重庆市政府"AI+火锅"展会演示程序。

5大场景（约20分钟）:
  场景1: 后厨之眼 — 视觉引擎（废料检测+损耗分析+SOP合规）
  场景2: 算得清的订货 — 数据引擎（销量预测+采购建议+库存监控）
  场景3: 冻品供应链管控 — 供应链全链路（收货→质检→温控追溯）
  场景4: 岗位AI助理 — 三大岗位助理（店长/后厨/采购）
  场景5: 连锁管控 — 两店对比看板

使用方式:
    # 运行全部场景
    python -m demo.demo_runner --all

    # 运行单个场景
    python -m demo.demo_runner --scene supply-chain

    # 仅生成数据
    python -m demo.demo_runner --init-data

    # 输出JSON格式
    python -m demo.demo_runner --all --format json
"""

import argparse
import json
import logging
import sqlite3
import sys
import time
from datetime import date, datetime
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
#  Demo 运行器主类
# =====================================================================

class ExpoDemoRunner:
    """火瞳重庆展会 Demo 运行器"""

    # 场景定义
    SCENARIOS = {
        "kitchen-eye": {
            "id": "S1",
            "name": "后厨之眼（视觉引擎）",
            "duration_min": 5,
            "description": "实时废料检测、损耗金额日报、SOP合规检测",
        },
        "smart-ordering": {
            "id": "S2",
            "name": "算得清的订货（数据引擎）",
            "duration_min": 5,
            "description": "AI销量预测、采购清单生成、库存监控、损耗闭环",
        },
        "supply-chain": {
            "id": "S3",
            "name": "冻品供应链管控",
            "duration_min": 4,
            "description": "收货验收、品质评级、温控追溯、退换货流程",
        },
        "ai-assistant": {
            "id": "S4",
            "name": "岗位AI助理",
            "duration_min": 4,
            "description": "店长助理/后厨助理/采购助理三大入口",
        },
        "chain-dashboard": {
            "id": "S5",
            "name": "连锁管控看板",
            "duration_min": 2,
            "description": "椒江vs玉环两店横向对比、区域健康分",
        },
    }

    def __init__(self, db_path: str = ":memory:", store_id: str = "store_jiaojiang"):
        self.db_path = db_path
        self.store_id = store_id
        self.db: Optional[sqlite3.Connection] = None
        self.results: Dict[str, Any] = {}
        self._engines: Dict[str, Any] = {}

    def _get_db(self) -> sqlite3.Connection:
        """延迟初始化数据库连接"""
        if self.db is None:
            self.db = sqlite3.connect(self.db_path)
            self.db.row_factory = sqlite3.Row
        return self.db

    def _init_engines(self):
        """初始化所有业务引擎"""
        db = self._get_db()

        # D1: 供应链管理器
        from hotpot_platform.cloud.supply_chain import SupplyChainManager
        self._engines["supply_chain"] = SupplyChainManager(db_session=db)

        # D2: SOP合规引擎
        from hotpot_platform.cloud.sop_engine import (
            SOPChecker, SOPTemplateManager, ViolationTracker,
        )
        self._engines["sop_checker"] = SOPChecker(db_session=db)
        self._engines["template_mgr"] = SOPTemplateManager(db_session=db)
        self._engines["violation_tracker"] = ViolationTracker(db_session=db)

        # D2: 知识检索
        from hotpot_platform.cloud.knowledge import KnowledgeRetriever
        self._engines["knowledge"] = KnowledgeRetriever(db_session=db)

        # D2: Agent框架
        from hotpot_platform.cloud.agent_framework import (
            AgentOrchestrator, MessageBus,
        )
        bus = MessageBus(db_session=db)
        self._engines["message_bus"] = bus
        self._engines["orchestrator"] = AgentOrchestrator(message_bus=bus)

        # D2: 数字座舱
        from hotpot_platform.cloud.cockpit import (
            DashboardAggregator, KPIEngine, AlertSummary,
            DecisionSupport, StoreComparison,
        )
        kpi_engine = KPIEngine()
        alert_summary = AlertSummary()
        decision_support = DecisionSupport()
        store_comparison = StoreComparison()

        # 注册KPI数据源
        self._register_kpi_sources(kpi_engine)

        self._engines["kpi_engine"] = kpi_engine
        self._engines["alert_summary"] = alert_summary
        self._engines["decision_support"] = decision_support
        self._engines["store_comparison"] = store_comparison
        self._engines["dashboard"] = DashboardAggregator(
            kpi_engine=kpi_engine,
            alert_summary=alert_summary,
            decision_support=decision_support,
            store_comparison=store_comparison,
        )

        logger.info("✅ 全部引擎初始化完成")

    def _register_kpi_sources(self, kpi_engine):
        """注册KPI数据源函数"""
        db = self._get_db()

        def make_kpi_source(metric_id):
            def source_fn(store_id):
                try:
                    row = db.execute("""
                        SELECT value, status, trend FROM kpi_history
                        WHERE store_id = ? AND metric_id = ?
                        ORDER BY recorded_date DESC LIMIT 1
                    """, (store_id, metric_id)).fetchone()
                    if row:
                        return float(row["value"])
                except Exception:
                    pass
                return 0.0
            return source_fn

        for mid in ["daily_revenue", "waste_rate", "table_turnover", "customer_count",
                     "avg_ticket", "sop_compliance", "inventory_accuracy", "labor_efficiency"]:
            kpi_engine.register_source(mid, make_kpi_source(mid))

    # =====================================================================
    #  场景实现
    # =====================================================================

    def scene_kitchen_eye(self) -> Dict[str, Any]:
        """
        场景1: 后厨之眼（视觉引擎）
        ─────────────────────────
        演示内容：
          1. 废料检测模拟（毛肚/鸭肠废弃统计）
          2. 损耗金额计算与趋势
          3. SOP合规自动检查
          4. 违规告警推送
        """
        print(f"\n{'='*60}")
        print(f"{C.BOLD}{C.MAGENTA}📹 场景1: 后厨之眼（视觉引擎）{C.END}")
        print(f"{C.DIM}演示时长: ~5分钟 | 展示废料检测 + 损耗分析 + SOP合规{C.END}")
        print(f"{'='*60}")

        result = {"steps": [], "key_metrics": {}}
        checker = self._engines["sop_checker"]
        store_id = self.store_id

        # Step 1: 模拟视觉检测结果
        print(f"\n{C.CYAN}▶ Step 1/4: 视觉AI废料检测{C.END}")
        print(f"{C.DIM}   （模拟椒江店后厨摄像头实时画面）{C.END}")

        waste_detection = {
            "timestamp": datetime.now().isoformat(),
            "store_id": store_id,
            "camera_zone": "kitchen_prep_area",
            "detections": [
            {"item": "毛肚", "count": 3, "reason": "过期变质", "est_value": 280 * 3},
                {"item": "鸭肠", "count": 2, "reason": "解冻过度", "est_value": 165 * 2},
                {"item": "蔬菜拼盘", "count": 1, "reason": "摆盘失误", "est_value": 25},
            ],
            "total_waste_items": 6,
            "total_est_loss": 280 * 3 + 165 * 2 + 25,
        }
        for d in waste_detection["detections"]:
            print(f"   {C.RED}⚠ {d['item']} x{d['count']} — {d['reason']} (≈¥{d['est_value']}){C.END}")

        result["steps"].append({"step": 1, "action": "视觉废料检测", "data": waste_detection})
        result["key_metrics"]["当日废料件数"] = waste_detection["total_waste_items"]
        result["key_metrics"]["当日损耗估算"] = f"¥{waste_detection['total_est_loss']}"

        time.sleep(0.3)

        # Step 2: 损耗率分析
        print(f"\n{C.CYAN}▶ Step 2/4: 损耗金额日报 & 趋势分析{C.END}")
        kpi_engine = self._engines["kpi_engine"]
        waste_kpi = kpi_engine.calculate_one(store_id, "waste_rate")
        if waste_kpi:
            status_emoji = "✅" if waste_kpi.status == "good" else ("⚠️" if waste_kpi.status == "warning" else "❌")
            print(f"   {status_emoji} 当前损耗率: {C.BOLD}{waste_kpi.value:.1f}%{C.END} (状态: {waste_kpi.status})")
            print(f"   📊 趋势: {waste_kpi.trend} | 阈值: >8%预警, >12%告警")

            # 对比行业平均
            industry_avg = 15.0  # 火锅行业平均损耗率
            saving = (industry_avg - waste_kpi.value) * 365 * (30000 / 100)  # 日营业额3万估算
            print(f"   💰 vs 行业平均({industry_avg}%): 年省 ≈ ¥{saving:,.0f}")

            result["key_metrics"]["损耗率"] = f"{waste_kpi.value:.1f}%"
            result["key_metrics"]["年节省估算"] = f"¥{saving:,.0f}"

        result["steps"].append({"step": 2, "action": "损耗分析", "data": {"waste_rate": waste_kpi.model_dump() if waste_kpi else None}})
        time.sleep(0.3)

        # Step 3: SOP合规检查
        print(f"\n{C.CYAN}▶ Step 3/4: SOP合规自动检查{C.END}")
        report = checker.check(
            store_id=store_id,
            zone="kitchen",
            signals={
                "mask_kitchen": True,
                "mask_kitchen_confidence": 0.97,
                "handwash_kitchen": 4,  # 分钟数，<30为正常
                "uniform_kitchen": True,
                "food_sample_done": True,
                "food_temp_ok": True,
                "expired_items_count": 0,
            },
        )

        score_emoji = "🏆" if report.compliance_score >= 90 else ("✅" if report.compliance_score >= 80 else ("⚠️" if report.compliance_score >= 70 else "❌"))
        print(f"   {score_emoji} 厨房区域合规分: {C.BOLD}{report.compliance_score:.1f}{C.END}/100")
        print(f"   ✓ 通过项: {report.passed_count} | ✗ 失败项: {report.failed_count} | ⏳ 待检: {report.pending_count}")

        if report.violations:
            print(f"\n   {C.RED}违规详情:{C.END}")
            for v in report.violations[:3]:
                sev_emoji = {"critical": "🔴", "major": "🟠", "minor": "🟡", "info": "🔵"}.get(v.severity.value if hasattr(v.severity, 'value') else v.severity, "⚪")
                print(f"     {sev_emoji} [{v.severity}] {v.rule_name}: {v.evidence or 'N/A'}")

        result["key_metrics"]["SOP合规分"] = f"{report.compliance_score:.1f}"
        result["steps"].append({"step": 3, "action": "SOP检查", "data": {"score": report.compliance_score, "violations": len(report.violations)}})
        time.sleep(0.3)

        # Step 4: 合规趋势
        print(f"\n{C.CYAN}▶ Step 4/4: 30天合规趋势{C.END}")
        trend = checker.get_compliance_trend(store_id, days=30)
        if trend and trend.daily_scores:
            scores = trend.daily_scores
            avg = trend.avg_score
            improvement = trend.improvement_pct
            print(f"   📈 30天均分: {C.BOLD}{avg:.1f}{C.END}")
            if improvement:
                direction = "📈 改善" if improvement > 0 else "📉 下降"
                print(f"   {direction}: {abs(improvement):+.1f}% (首日{scores[0]:.1f} → 近日{scores[-1]:.1f})")

            # 可视化趋势条
            bar_width = 50
            print(f"\n   {'':>4} │", end="")
            for s in scores[::max(1, len(scores)//20)]:  # 最多显示20个点
                filled = int(s / 100 * bar_width)
                bar = "█" * filled + "░" * (bar_width - filled)
                color = C.GREEN if s >= 90 else (C.YELLOW if s >= 70 else C.RED)
                print(f"{color}█{C.END}", end="")
            print(f"\n       0{'':<{bar_width//2-1}}100%")

            result["key_metrics"]["30天均分"] = f"{avg:.1f}"
            result["key_metrics"]["改善幅度"] = f"{improvement:+.1f}%"

        result["steps"].append({"step": 4, "action": "合规趋势", "data": {"avg_score": trend.avg_score if trend else 0}})

        print(f"\n{C.GREEN}✅ 场景1完成{C.END}")
        return result

    def scene_smart_ordering(self) -> Dict[str, Any]:
        """
        场景2: 算得清的订货（数据引擎）
        ─────────────────────────
        演示内容：
          1. AI销量预测展示
          2. 预测准确率回测
          3. 采购清单自动生成
          4. 库存安全线监控
          5. 损耗-预测闭环
        """
        print(f"\n{'='*60}")
        print(f"{C.BOLD}{C.MAGENTA}🧠 场景2: 算得清的订货（数据引擎）{C.END}")
        print(f"{C.DIM}演示时长: ~5分钟 | AI预测 + 采购建议 + 库存监控{C.END}")
        print(f"{'='*60}")

        result = {"steps": [], "key_metrics": {}}
        sc = self._engines["supply_chain"]
        store_id = self.store_id

        # Step 1: 销量预测
        print(f"\n{C.CYAN}▶ Step 1/5: AI销量预测{C.END}")
        print(f"{C.DIM}   明天{self._store_name()}各品类预测销量:{C.END}")

        predictions = [
            {"category": "冻品肉类", "item": "精品毛肚", "pred_qty": "15kg", "confidence": "92%", "factor": "周末×1.4"},
            {"category": "冻品肉类", "item": "鲜鸭肠", "pred_qty": "10kg", "confidence": "89%", "factor": "周末×1.4"},
            {"category": "冻品肉类", "item": "肥牛卷", "pred_qty": "20盒", "confidence": "94%", "factor": "周末×1.4"},
            {"category": "蔬菜", "item": "生菜", "pred_qty": "40份", "confidence": "85%", "factor": "周末×1.3"},
            {"category": "调料", "item": "火锅底料", "pred_qty": "8袋", "confidence": "91%", "factor": "稳定"},
        ]

        for p in predictions:
            conf_color = C.GREEN if int(p["confidence"].replace('%','')) >= 90 else C.YELLOW
            print(f"   📦 {p['item']:8s} → {C.BOLD}{p['pred_qty']}{C.END} ({conf_color}{p['confidence']}{C.END}) {p['factor']}")

        result["key_metrics"]["预测品类数"] = len(predictions)
        result["key_metrics"]["平均置信度"] = "90%"
        result["steps"].append({"step": 1, "action": "AI销量预测", "data": predictions})
        time.sleep(0.3)

        # Step 2: 预测准确率回测
        print(f"\n{C.CYAN}▶ Step 2/5: 预测准确率回测{C.END}")
        mape_value = 10.6
        print(f"   🎯 90天回测 MAPE: {C.BOLD}{mape_value}%{C.END}")
        print(f"   📊 远超行业门槛(45%)，准确率提升 {45 - mape_value:.1f} 个百分点")

        accuracy_trend = [
            {"month": "第1月", "mape": 18.2},
            {"month": "第2月", "mape": 14.5},
            {"month": "第3月", "mape": 10.6},
        ]
        print(f"\n   准确率提升轨迹:")
        for t in accuracy_trend:
            bar_len = int(t["mape"] / 25 * 30)
            color = C.GREEN if t["mape"] <= 12 else (C.YELLOW if t["mape"] <= 18 else C.RED)
            print(f"     {t['month']:6s} {color}{'█'*bar_len}{'░'*(30-bar_len)}{C.END} {t['mape']:.1f}%")

        result["key_metrics"]["MAPE"] = f"{mape_value}%"
        result["steps"].append({"step": 2, "action": "准确率回测", "data": {"mape": mape_value}})
        time.sleep(0.3)

        # Step 3: 采购清单生成
        print(f"\n{C.CYAN}▶ Step 3/5: 采购建议清单{C.END}")

        suppliers = sc.list_suppliers(store_id=store_id, status="active")
        po_items = [
            {"sku": "PROD-001", "name": "精品毛肚", "qty": 15, "unit": "kg", "price": 280, "supplier": "王总方"},
            {"sku": "PROD-002", "name": "鲜鸭肠", "qty": 10, "unit": "kg", "price": 165, "supplier": "王总方"},
            {"sku": "PROD-005", "name": "肥牛卷", "qty": 20, "unit": "盒", "price": 145, "supplier": "王总方"},
            {"sku": "PROD-007", "name": "生菜", "qty": 50, "unit": "份", "price": 4, "supplier": "李记"},
            {"sku": "PROD-009", "name": "火锅底料", "qty": 10, "unit": "袋", "price": 35, "supplier": "张氏"},
        ]

        total_amount = sum(p["qty"] * p["price"] for p in po_items)
        print(f"   📋 自动生成采购单 (供应商加权推荐):")
        for item in po_items:
            subtotal = item["qty"] * item["price"]
            print(f"     {item['name']:8s} {item['qty']:>5}{item['unit']} × ¥{item['price']:>6} = ¥{subtotal:>7,.0f}  [{item['supplier']}]")

        print(f"\n   {C.BOLD}合计: ¥{total_amount:,.0f}{C.END}")
        result["key_metrics"]["采购单总额"] = f"¥{total_amount:,.0f}"
        result["steps"].append({"step": 3, "action": "采购清单", "data": {"items": po_items, "total": total_amount}})
        time.sleep(0.3)

        # Step 4: 库存监控
        print(f"\n{C.CYAN}▶ Step 4/5: 库存安全线监控{C.END}")

        inventory_status = [
            {"name": "精品毛肚", "current": 4, "safety": 3, "status": "normal"},
            {"name": "鲜鸭肠", "current": 2, "safety": 5, "status": "low"},      # 低于安全线！
            {"name": "肥牛卷", "current": 12, "safety": 10, "status": "normal"},
            {"name": "香油碟料包", "current": 2, "safety": 5, "status": "low"},   # 低于安全线！
            {"name": "火锅底料", "current": 18, "safety": 15, "status": "normal"},
        ]

        low_stock_count = 0
        for inv in inventory_status:
            if inv["status"] == "low":
                print(f"   {C.RED}⚠ {inv['name']:10s} 库存 {inv['current']} < 安全线({inv['safety']}) → 需补货{C.END}")
                low_stock_count += 1
            else:
                print(f"   ✅ {inv['name']:10s} 库存 {inv['current']} (安全线{inv['safety']})")

        if low_stock_count > 0:
            print(f"\n   🔔 已自动触发 {low_stock_count} 项补货提醒 → 同步到采购单")

        result["key_metrics"]["低库存SKU"] = low_stock_count
        result["steps"].append({"step": 4, "action": "库存监控", "data": inventory_status})
        time.sleep(0.3)

        # Step 5: 损耗闭环
        print(f"\n{C.CYAN}▶ Step 5/5: 损耗成本闭环{C.END}")
        print(f"{C.DIM}   视觉检测废料 → 自动扣减库存 → 损耗金额 → 预测校准{C.END}")

        closed_loop = {
            "vision_detect": "检测到毛肚废弃3盘 (¥840)",
            "auto_deduct": "自动扣减库存: 毛肚 -3kg",
            "waste_record": "记录损耗: 当日累计¥1,175",
            "forecast_adjust": "明日毛肚预测量 +5% (补偿今日损耗)",
        }

        for key, val in closed_loop.items():
            emoji = {"vision_detect": "👁", "auto_deduct": "📦", "waste_record": "💸", "forecast_adjust": "🔄"}.get(key, "•")
            print(f"   {emoji} {val}")

        print(f"\n   {C.GREEN}♻️ 闭环完成: 废料数据已反馈至预测模型{C.END}")
        result["steps"].append({"step": 5, "action": "损耗闭环", "data": closed_loop})

        print(f"\n{C.GREEN}✅ 场景2完成{C.END}")
        return result

    def scene_supply_chain(self) -> Dict[str, Any]:
        """
        场景3: 冻品供应链管控
        ─────────────────────────
        演示内容：
          1. 货品主数据展示
          2. 收货验收流程
          3. 温控异常处理
          4. 退换货流程
          5. 全链路温度追溯
        """
        print(f"\n{'='*60}")
        print(f"{C.BOLD}{C.MAGENTA}🧊 场景3: 冻品供应链管控{C.END}")
        print(f"{C.DIM}演示时长: ~4分钟 | 收货→质检→温控→退换货全链路{C.END}")
        print(f"{'='*60}")

        result = {"steps": [], "key_metrics": {}}
        sc = self._engines["supply_chain"]
        store_id = self.store_id
        db = self._get_db()

        # Step 1: 货品主数据
        print(f"\n{C.CYAN}▶ Step 1/5: 货品主数据（品牌规格锁定）{C.END}")

        # 确保row_factory已设置
        if not isinstance(db.row_factory, type):
            db.row_factory = sqlite3.Row

        products = db.execute("SELECT sku, name, spec, brand, price FROM products LIMIT 8").fetchall()
        print(f"   📦 统一货品清单 ({len(products)}个SKU已录入):")
        for p in products:
            print(f"     [{p['sku']}] {p['name']:8s} {p['spec']:12s} {p['brand']:4s} ¥{p['price']:.0f}")

        result["key_metrics"]["SKU总数"] = len(products)
        result["steps"].append({"step": 1, "action": "货品主数据", "data": {"count": len(products)}})
        time.sleep(0.3)

        # Step 2: 收货验收流程
        print(f"\n{C.CYAN}▶ Step 2/5: 收货验收流程{C.END}")

        receiving_records = db.execute("""
            SELECT r.record_id, r.received_at, s.name as supplier_name,
                   r.total_items, r.inspector, r.status, r.notes
            FROM receiving_records r
            LEFT JOIN suppliers s ON r.supplier_id = s.supplier_id
            WHERE r.store_id = ?
            ORDER BY r.received_at DESC LIMIT 3
        """, (store_id,)).fetchall()

        if receiving_records:
            for rec in receiving_records:
                status_icon = "✅" if rec["status"] == "completed" else ("⚠️" if rec["status"] == "exception" else "📋")
                items = db.execute("SELECT COUNT(*) as cnt, SUM(CASE WHEN is_accepted=1 THEN 1 ELSE 0 END) as accepted FROM receiving_items WHERE record_id=?", (rec["record_id"],)).fetchone()
                print(f"   {status_icon} {rec['received_at'][:10]} | {rec['supplier_name']} | "
                      f"{rec['total_items']}件 | 验收员:{rec['inspector']} | 通过:{items['accepted']}/{items['cnt']}")
                if rec["notes"]:
                    print(f"      {C.YELLOW}└─ {rec['notes']}{C.END}")

        result["steps"].append({"step": 2, "action": "收货验收", "data": {"recent_records": len(receiving_records)}})
        time.sleep(0.3)

        # Step 3: 温控异常处理
        print(f"\n{C.CYAN}▶ Step 3/5: 温控异常检测与处理{C.END}")

        temp_exceptions = db.execute("""
            SELECT i.product_name, i.temperature, i.quality_grade, r.received_at
            FROM receiving_items i
            JOIN receiving_records r ON i.record_id = r.record_id
            WHERE r.store_id = ? AND i.quality_grade IN ('B', 'C')
            ORDER BY r.received_at DESC LIMIT 5
        """, (store_id,)).fetchall()

        if temp_exceptions:
            for exc in temp_exceptions:
                grade_color = C.RED if exc["quality_grade"] == "C" else C.YELLOW
                grade_label = {"A": "合格", "B": "轻微瑕疵", "C": "不合格"}.get(exc["quality_grade"], "未知")
                print(f"   {grade_color}[{exc['quality_grade']}] {exc['product_name']:8s} 到货温度: {exc['temperature']:.1f}℃ → {grade_label}{C.END}")
        else:
            print(f"   ✅ 近期无温度异常记录")

        result["key_metrics"]["温度异常次数"] = len([e for e in temp_exceptions if e["quality_grade"] == "C"])
        result["steps"].append({"step": 3, "action": "温控异常", "data": {"exceptions": len(temp_exceptions)}})
        time.sleep(0.3)

        # Step 4: 退换货流程
        print(f"\n{C.CYAN}▶ Step 4/5: 退换货流程{C.END}")
        rejected_items = db.execute("""
            SELECT COUNT(*) as cnt FROM receiving_items ri
            JOIN receiving_records r ON ri.record_id = r.record_id
            WHERE r.store_id = ? AND ri.is_accepted = 0
        """, (store_id,)).fetchone()

        reject_count = rejected_items["cnt"] if rejected_items else 0
        if reject_count > 0:
            print(f"   📤 本月退换货: {reject_count}件")
            print(f"   ├─ 自动发起退换货单")
            print(f"   ├─ 群内通知供应商（王总方）")
            print(f"   └─ 记录供应商评分扣减")
        else:
            print(f"   ✅ 本月无退换货（质量稳定）")

        result["key_metrics"]["本月退换货"] = reject_count
        result["steps"].append({"step": 4, "action": "退换货", "data": {"rejected": reject_count}})
        time.sleep(0.3)

        # Step 5: 温度追溯
        print(f"\n{C.CYAN}▶ Step 5/5: 全链路温度追溯{C.END}")
        print(f"{C.DIM}   冻品从收货→入库→出库全程温度记录:{C.END}")

        temp_trace = [
            {"stage": "供应商出库", "time": "08:00", "temp": "-22℃", "ok": True},
            {"stage": "物流运输", "time": "09:30", "temp": "-19℃", "ok": True},
            {"stage": "到货验收", "time": "10:15", "temp": "-17℃", "ok": True},
            {"stage": "入库上架", "time": "10:45", "temp": "-18℃", "ok": True},
            {"stage": "冷库存储", "time": "每日巡检", "temp": "-18±1℃", "ok": True},
            {"stage": "出库使用", "time": "次日备餐", "temp": "-18℃", "ok": True},
        ]

        for trace in temp_trace:
            icon = "✅" if trace["ok"] else "❌"
            print(f"   {icon} {trace['stage']:8s} {trace['time']:10s} 温度:{trace['temp']:>8}")

        print(f"\n   📡 全程冷链完整，{C.GREEN}无断链记录{C.END}")
        result["steps"].append({"step": 5, "action": "温度追溯", "data": temp_trace})

        print(f"\n{C.GREEN}✅ 场景3完成{C.END}")
        return result

    def scene_ai_assistant(self) -> Dict[str, Any]:
        """
        场景4: 岗位AI助理
        ─────────────────────────
        演示内容：
          1. 店长助理（今日待办+异常汇总+决策建议）
          2. 后厨助理（备货提醒+SOP纠偏）
          3. 采购助理（采购确认+供应商比价）
          4. Agent消息总线协作
        """
        print(f"\n{'='*60}")
        print(f"{C.BOLD}{C.MAGENTA}🤖 场景4: 岗位AI助理{C.END}")
        print(f"{C.DIM}演示时长: ~4分钟 | 店长/后厨/采购三大AI助理{C.END}")
        print(f"{'='*60}")

        result = {"steps": [], "key_metrics": {}}
        orch = self._engines["orchestrator"]
        bus = self._engines["message_bus"]
        store_id = self.store_id

        # Step 1: 店长助理
        print(f"\n{C.CYAN}▶ Step 1/4: 🏪 店长助理{C.END}")
        print(f"{C.DIM}   打开手机 → 今日工作台:{C.END}")

        dashboard = self._engines["dashboard"].build_dashboard(
            store_id=store_id,
            include_comparison=True,
            comparison_store_ids=["store_yuhuan"],
        )

        # KPI概览
        print(f"\n   📊 今日KPI总览:")
        for kpi in dashboard.kpis[:5]:  # 显示前5项
            status_icon = {"good": "🟢", "normal": "⚪", "warning": "🟡", "danger": "🔴"}.get(kpi.status, "⚪")
            trend_arrow = {"up": "↑", "down": "↓", "stable": "→"}.get(kpi.trend, "→")
            print(f"     {status_icon} {kpi.name:10s}: {kpi.value} {trend_arrow} ({kpi.status})")

        # 待办事项
        if dashboard.todos:
            print(f"\n   📋 今日待办 ({len(dashboard.todos)}项):")
            for todo in dashboard.todos[:4]:
                prio_icon = {"high": "🔴", "medium": "🟡", "low": "🔵"}.get(todo.priority, "⚪")
                print(f"     {prio_icon} [{todo.priority}] {todo.title}")

        # 决策建议
        if dashboard.suggestions:
            print(f"\n   💡 AI决策建议:")
            for sug in dashboard.suggestions[:3]:
                print(f"     • {sug.title}: {sug.description[:50]}...")

        result["key_metrics"]["KPI数量"] = len(dashboard.kpis)
        result["key_metrics"]["待办数量"] = len(dashboard.todos)
        result["key_metrics"]["建议数量"] = len(dashboard.suggestions)
        result["steps"].append({"step": 1, "action": "店长助理", "data": {"kpis": len(dashboard.kpis), "todos": len(dashboard.todos)}})
        time.sleep(0.3)

        # Step 2: 后厨助理
        print(f"\n{C.CYAN}▶ Step 2/4: 👨‍🍳 后厨助理{C.END}")

        kitchen_data = {
            "prep_reminders": [
                {"dish": "毛肚", "forecast_covers": 80, "prep_qty": "16kg", "note": "周末高峰，多备20%"},
                {"dish": "鸭肠", "forecast_covers": 80, "prep_qty": "10kg", "note": "按标准量准备"},
                {"dish": "蔬菜拼盘", "forecast_covers": 80, "prep_qty": "50份", "note": "现切现摆"},
            ],
            "sop_deviations": [
                {"zone": "厨房", "rule": "洗手频次", "severity": "minor", "tip": "提醒员工每30分钟洗手"},
                {"zone": "仓库", "rule": "FEFO先失效先出", "severity": "major", "tip": "优先使用入库较早的毛肚"},
            ],
        }

        print(f"   📅 明日午市预计 {C.BOLD}80桌{C.END}，备货建议:")
        for prep in kitchen_data["prep_reminders"]:
            print(f"     🥘 {prep['dish']:8s} → {prep['prep_qty']} ({prep['note']})")

        if kitchen_data["sop_deviations"]:
            print(f"\n   ⚠️ SOP纠偏提醒:")
            for dev in kitchen_data["sop_deviations"]:
                sev_color = C.RED if dev["severity"] == "major" else C.YELLOW
                print(f"     {sev_color}[{dev['severity']}] {dev['zone']}-{dev['rule']}: {dev['tip']}{C.END}")

        result["steps"].append({"step": 2, "action": "后厨助理", "data": kitchen_data})
        time.sleep(0.3)

        # Step 3: 采购助理
        print(f"\n{C.CYAN}▶ Step 3/4: 🛒 采购助理{C.END}")

        procurement_data = {
            "pending_orders": [
                {"po_number": "PO-JJ-20260728-042", "supplier": "王总方", "total": 6850, "status": "待确认"},
                {"po_number": "PO-JJ-20260727-038", "supplier": "李记蔬菜", "total": 420, "status": "配送中"},
            ],
            "supplier_comparison": [
                {"product": "毛肚(5kg)", "wang_price": 280, "market_avg": 310, "saving": "9.7%"},
                {"product": "鸭肠(3kg)", "wang_price": 165, "market_avg": 185, "saving": "10.8%"},
            ],
        }

        print(f"   📦 待处理采购单:")
        for po in procurement_data["pending_orders"]:
            status_color = C.YELLOW if po["status"] == "待确认" else C.BLUE
            print(f"     {po['po_number']} | {po['supplier']} | ¥{po['total']:,} | {status_color}{po['status']}{C.END}")

        print(f"\n   💰 供应商价格优势:")
        for comp in procurement_data["supplier_comparison"]:
            print(f"     {comp['product']:14s} 王总方¥{comp['wang_price']} vs 市场¥{comp['market_avg']} → {C.GREEN}省{comp['saving']}{C.END}")

        result["steps"].append({"step": 3, "action": "采购助理", "data": procurement_data})
        time.sleep(0.3)

        # Step 4: Agent消息协作
        print(f"\n{C.CYAN}▶ Step 4/4: Agent消息总线协作{C.END}")

        # 创建Agent实例
        a01 = orch.create_agent_from_template("TPL-A01-STORE-MGR", "A01-DEMO")
        a02 = orch.create_agent_from_template("TPL-A02-KITCHEN", "A02-DEMO")
        a03 = orch.create_agent_from_template("TPL-A03-PROCUREMENT", "A03-DEMO")

        agents_created = [a for a in [a01, a02, a03] if a is not None]
        print(f"   🤖 已创建 {len(agents_created)} 个岗位Agent:")

        for agent in agents_created:
            role_name = getattr(agent.config.role, 'value', str(agent.config.role)) if hasattr(agent.config.role, 'value') else str(agent.config.role)
            role_labels = {"store_manager": "店长助理", "kitchen_chef": "后厨主管", "procurement_officer": "采购专员"}
            label = role_labels.get(role_name, role_name)
            cap_names = [str(c).split('.')[-1] for c in agent.config.capabilities] if agent.config.capabilities else []
            print(f"     • {agent.config.name} ({label}) 能力: {', '.join(cap_names[:3])}")

        # 模拟消息发送
        if agents_created:
            sender = agents_created[0]
            msg = sender.send(
                msg_type="alert",
                receiver_id="broadcast",
                topic="store/warning",
                payload={
                    "type": "waste_rate_warning",
                    "store_id": store_id,
                    "current_rate": 7.2,
                    "threshold": 8.0,
                    "action": "请后厨助理关注备货量",
                },
                priority="high",
            )
            print(f"\n   📨 店长助理 → 消息总线:")
            print(f"     消息类型: {msg.msg_type if hasattr(msg, 'msg_type') else 'alert'}")
            print(f"     主题: store/warning")
            print(f"     优先级: high")
            print(f"     内容: 损耗率预警通知已广播给所有订阅者")

        result["key_metrics"]["Agent数量"] = len(agents_created)
        result["steps"].append({"step": 4, "action": "Agent协作", "data": {"agents": len(agents_created)}})

        print(f"\n{C.GREEN}✅ 场景4完成{C.END}")
        return result

    def scene_chain_dashboard(self) -> Dict[str, Any]:
        """
        场景5: 连锁管控看板
        ─────────────────────────
        演示内容：
          1. 两店关键指标对比
          2. 异常门店标红
          3. 区域健康分
          4. 改善趋势可视化
        """
        print(f"\n{'='*60}")
        print(f"{C.BOLD}{C.MAGENTA}🏢 场景5: 连锁管控看板{C.END}")
        print(f"{C.DIM}演示时长: ~2分钟 | 椒江vs玉环两店横向对比{C.END}")
        print(f"{'='*60}")

        result = {"steps": [], "key_metrics": {}}

        # Step 1: 两店KPI对比
        print(f"\n{C.CYAN}▶ Step 1/3: 两店关键指标对比{C.END}")

        comparison = self._engines["store_comparison"].compare_stores(
            primary_store_id=self.store_id,
            store_ids=["store_jiaojiang", "store_yuhuan"],
        )

        if comparison and comparison.stores:
            # 获取所有指标名
            all_metrics = set()
            for s in comparison.stores:
                all_metrics.update(s.metrics.keys())

            print(f"\n   {'指标':12s}", end="")
            for s in comparison.stores:
                print(f" {s.store_name or s.store_id:>10s}", end="")
            print(f" {'状态'}")
            print(f"   {'─'*12}", end="")
            for _ in comparison.stores:
                print(f" {'─'*10}", end="")
            print(f" {'─'*6}")

            for metric_id in sorted(all_metrics):
                print(f"   {metric_id:12s}", end="")
                values = []
                for s in comparison.stores:
                    val = s.metrics.get(metric_id)
                    val_str = f"{val:.1f}" if isinstance(val, (int, float)) else "N/A"
                    print(f" {val_str:>10s}", end="")
                    values.append(val if isinstance(val, (int, float)) else 0)

                # 状态判断（基于两店差异）
                if len(values) >= 2:
                    try:
                        diff = abs(values[0] - values[1])
                        avg_val = (values[0] + values[1]) / 2
                        if avg_val > 0 and diff / avg_val > 0.15:
                            status = "🔴异常"
                        elif avg_val > 0 and diff / avg_val > 0.08:
                            status = "🟡注意"
                        else:
                            status = "✅正常"
                    except (ValueError, TypeError, ZeroDivisionError):
                        status = "—"
                else:
                    status = "✅正常"
                print(f" {status}")

        result["steps"].append({"step": 1, "action": "两店对比", "data": "comparison_executed"})
        time.sleep(0.3)

        # Step 2: 区域健康分
        print(f"\n{C.CYAN}▶ Step 2/3: 区域健康分{C.END}")

        health_scores = [
            {"store": "椒江店", "overall": 88, "ops": 90, "safety": 92, "finance": 85, "trend": "📈+3"},
            {"store": "玉环店", "overall": 72, "ops": 75, "safety": 70, "finance": 73, "trend": "📈+5"},
        ]

        for h in health_scores:
            bar_filled = int(h["overall"] / 100 * 25)
            bar_color = C.GREEN if h["overall"] >= 85 else (C.YELLOW if h["overall"] >= 70 else C.RED)
            print(f"   {h['store']:6s} {C.BOLD}{bar_color}{'█'*bar_filled}{'░'*(25-bar_filled)}{C.END} {h['overall']}分 {h['trend']}")
            print(f"         运营{h['ops']} | 安全{h['safety']} | 财务{h['finance']}")

        result["key_metrics"][
            "椒江店健康分"] = f"{health_scores[0]['overall']}分"
        result["key_metrics"][
            "玉环店健康分"] = f"{health_scores[1]['overall']}分"
        result["steps"].append({"step": 2, "action": "区域健康分", "data": health_scores})
        time.sleep(0.3)

        # Step 3: ROI总结
        print(f"\n{C.CYAN}▶ Step 3/3: 投资回报总结{C.END}")

        roi_summary = [
            ("预测准确率", "MAPE 10.6%", "行业平均45%，提升34.4个百分点"),
            ("损耗率改善", "12% → 6.8%", "年省约¥5万+"),
            ("采购优化", "集中采购降本", "较市场价低8%~11%"),
            ("人效提升", "SOP自动化", "减少培训和管理成本"),
            ("单店年节省", "≥¥150,000", "损耗+采购+人效综合"),
        ]

        print(f"\n   {C.BOLD}🎯 火瞳系统价值量化:{C.END}\n")
        for name, value, desc in roi_summary:
            print(f"   ✅ {name:10s} {C.BOLD}{value}{C.END}")
            print(f"      {C.DIM}{desc}{C.END}")

        result["key_metrics"]["单店年节省"] = "≥¥150,000"
        result["steps"].append({"step": 3, "action": "ROI总结", "data": roi_summary})

        print(f"\n{C.GREEN}✅ 场景5完成 — 全部演示结束{C.END}")
        return result

    # =====================================================================
    #  工具方法
    # =====================================================================

    def _store_name(self) -> str:
        """获取当前店铺名称"""
        names = {"store_jiaojiang": "椒江店", "store_yuhuan": "玉环店"}
        return names.get(self.store_id, self.store_id)

    def init_data(self, days: int = 30) -> Dict[str, Any]:
        """初始化演示数据"""
        from demo.demo_data import DemoDataGenerator
        db = self._get_db()
        gen = DemoDataGenerator(db)
        stats = gen.generate_all(days=days)
        logger.info(f"📊 演示数据生成完成: {stats}")
        return stats

    def run_scene(self, scene_key: str) -> Dict[str, Any]:
        """运行单个场景"""
        scene_map = {
            "kitchen-eye": self.scene_kitchen_eye,
            "smart-ordering": self.scene_smart_ordering,
            "supply-chain": self.scene_supply_chain,
            "ai-assistant": self.scene_ai_assistant,
            "chain-dashboard": self.scene_chain_dashboard,
        }

        if scene_key not in scene_map:
            available = ", ".join(scene_map.keys())
            raise ValueError(f"未知场景 '{scene_key}'。可用场景: {available}")

        if not self._engines:
            self._init_engines()

        return scene_map[scene_key]()

    def run_all(self) -> Dict[str, Any]:
        """运行全部5个场景"""
        if not self._engines:
            self._init_engines()

        all_results = {}
        total_start = time.time()

        for scene_key, info in self.SCENARIOS.items():
            print(f"\n\n{C.DIM}{'━'*60}{C.END}")
            print(f"{C.DIM}  开始 {info['id']}: {info['name']} (~{info['duration_min']}分钟){C.END}")
            print(f"{C.DIM}{'━'*60}{C.END}")

            start = time.time()
            try:
                result = self.run_scene(scene_key)
                elapsed = time.time() - start
                result["_elapsed_seconds"] = round(elapsed, 1)
                all_results[scene_key] = result
                print(f"\n{C.DIM}  ⏱️ {info['name']} 耗时 {elapsed:.1f}s{C.END}")
            except Exception as e:
                logger.error(f"场景 {scene_key} 执行失败: {e}", exc_info=True)
                all_results[scene_key] = {"error": str(e), "_elapsed_seconds": 0}

        total_elapsed = time.time() - total_start
        all_results["_total_elapsed"] = round(total_elapsed, 1)
        all_results["_run_time"] = datetime.now().isoformat()

        # 打印总结
        self._print_summary(all_results)

        return all_results

    def _print_summary(self, results: Dict[str, Any]):
        """打印执行总结"""
        print(f"\n\n{'='*60}")
        print(f"{C.BOLD}{C.MAGENTA}🎬 火瞳展会 Demo 执行总结{C.END}")
        print(f"{'='*60}")

        total_scenes = len(self.SCENARIOS)
        success_count = sum(1 for k in results if k.startswith("S") or k in self.SCENARIOS and "error" not in results.get(k, {}))

        print(f"\n   场景执行: {C.GREEN}{success_count}/{total_scenes} 通过{C.END}")
        print(f"   总耗时: {results.get('_total_elapsed', '?')}s")
        print(f"   执行时间: {results.get('_run_time', '?')}")

        print(f"\n   关键指标汇总:")
        for scene_key, result in results.items():
            if scene_key.startswith("_") or "error" in result:
                continue
            info = self.SCENARIOS.get(scene_key, {})
            metrics = result.get("key_metrics", {})
            if metrics:
                metrics_str = ", ".join(f"{k}={v}" for k, v in list(metrics.items())[:3])
                print(f"     {info.get('id', '?')}: {metrics_str}")

        print(f"\n{C.GREEN}{'═'*60}{C.END}")
        print(f"{C.BOLD}  重庆火锅，AI赋能 — 火瞳系统演示完毕{C.END}")
        print(f"{C.GREEN}{'═'*60}{C.END}")


# =====================================================================
#  CLI 入口
# =====================================================================

def main():
    parser = argparse.ArgumentParser(description="火瞳重庆展会 Demo 运行器")
    parser.add_argument("--all", action="store_true", help="运行全部5个场景")
    parser.add_argument("--scene", type=str, help="运行指定场景 (kitchen-eye/smart-ordering/supply-chain/ai-assistant/chain-dashboard)")
    parser.add_argument("--init-data", action="store_true", help="仅生成演示数据")
    parser.add_argument("--days", type=int, default=30, help="生成多少天的历史数据 (默认30)")
    parser.add_argument("--store", type=str, default="store_jiaojiang", help="店铺ID (默认store_jiaojiang)")
    parser.add_argument("--db", type=str, default=":memory:", help="数据库路径 (默认:memory)")
    parser.add_argument("--format", type=str, default="text", choices=["text", "json"], help="输出格式")
    parser.add_argument("--quiet", action="store_true", help="静默模式（仅输出结果）")

    args = parser.parse_args()

    runner = ExpoDemoRunner(db_path=args.db, store_id=args.store)

    # 初始化数据
    if args.init_data or args.all or args.scene:
        print(f"\n{C.BOLD}🚀 初始化演示数据 ({args.days}天){C.END}")
        stats = runner.init_data(days=args.days)
        if args.format == "json":
            print(json.dumps(stats, ensure_ascii=False, indent=2))

    # 运行场景
    if args.all:
        results = runner.run_all()
        if args.format == "json":
            print(json.dumps(results, ensure_ascii=False, indent=2, default=str))
    elif args.scene:
        result = runner.run_scene(args.scene)
        if args.format == "json":
            print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    elif not args.init_data:
        parser.print_help()


if __name__ == "__main__":
    main()
