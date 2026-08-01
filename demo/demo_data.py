"""
火瞳展会 Demo 数据生成器
=========================
为重庆展会演示生成椒江店+玉环店的完整模拟数据集。

数据覆盖:
  - 冻品供应链: 供应商/收货记录/采购订单/质检结果
  - SOP合规: 检查信号/合规报告/违规记录
  - 知识库: 菜品知识/经营Know-how
  - 数字座舱: KPI历史/告警记录/待办事项
  - Agent消息: 岗位助理交互日志

使用方式:
    from demo.demo_data import DemoDataGenerator
    gen = DemoDataGenerator(db_session)
    gen.generate_all()  # 生成全部数据
"""

import logging
import random
import sqlite3
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class DemoDataGenerator:
    """展会演示数据生成器 — 生成真实感的双店运营数据"""

    # ==================== 店铺配置 ====================

    STORES = {
        "store_jiaojiang": {
            "store_id": "store_jiaojiang",
            "name": "椒江店",
            "city": "台州",
            "address": "椒江区中心大道188号",
            "open_date": "2025-03-15",
            # 椒江店运营较好（作为标杆）
            "daily_revenue_base": 28000,      # 日营业额基数
            "waste_rate_base": 0.068,         # 损耗率 6.8%（已改善）
            "table_turnover_base": 3.2,        # 翻台率
            "customer_count_base": 180,        # 日客流量
            "sop_compliance_base": 92,         # SOP合规率%
            "inventory_accuracy_base": 96,     # 库存准确率%
            "labor_efficiency_base": 185,      # 人效(元/人/天)
        },
        "store_yuhuan": {
            "store_id": "store_yuhuan",
            "name": "玉环店",
            "city": "台州",
            "address": "玉环市港南大道66号",
            "open_date": "2025-06-20",
            # 玉环店有改进空间（展示系统能力）
            "daily_revenue_base": 22000,
            "waste_rate_base": 0.112,          # 损耗率 11.2%（待改善）
            "table_turnover_base": 2.6,
            "customer_count_base": 140,
            "sop_compliance_base": 78,          # SOP合规率偏低
            "inventory_accuracy_base": 88,
            "labor_efficiency_base": 158,
        },
    }

    # ==================== 供应商数据 ====================

    SUPPLIERS = [
        {
            "supplier_id": "SUPP-WANG-001",
            "name": "王总方冻品批发",
            "contact_person": "王总",
            "phone": "138****5678",
            "category": "frozen_food",
            "status": "active",
            "rating": 4.6,
            "products": ["毛肚", "鸭肠", "黄喉", "牛百叶", "肥牛卷", "羊肉卷"],
        },
        {
            "supplier_id": "SUPP-LI-002",
            "name": "李记蔬菜配送",
            "contact_person": "李经理",
            "phone": "139****1234",
            "category": "vegetable",
            "status": "active",
            "rating": 4.2,
            "products": ["生菜", "菠菜", "金针菇", "莲藕", "土豆", "娃娃菜"],
        },
        {
            "supplier_id": "SUPP-ZHANG-003",
            "name": "张氏调料行",
            "contact_person": "张老板",
            "phone": "137****9876",
            "category": "seasoning",
            "status": "active",
            "rating": 4.8,
            "products": ["火锅底料", "香油", "蒜泥", "香菜", "葱花", "花椒油"],
        },
    ]

    # ==================== 货品主数据 ====================

    PRODUCTS = [
        {"sku": "PROD-001", "name": "精品毛肚", "spec": "5kg/箱", "unit": "箱", "brand": "蜀道", "category": "frozen_meat", "price": 280.0, "safety_stock": 3},
        {"sku": "PROD-002", "name": "鲜鸭肠", "spec": "3kg/箱", "unit": "箱", "brand": "渝达", "category": "frozen_meat", "price": 165.0, "safety_stock": 5},
        {"sku": "PROD-003", "name": "水发黄喉", "spec": "2kg/袋", "unit": "袋", "brand": "川味", "category": "frozen_meat", "price": 95.0, "safety_stock": 8},
        {"sku": "PROD-004", "name": "牛百叶", "spec": "5kg/箱", "unit": "箱", "brand": "蜀道", "category": "frozen_meat", "price": 260.0, "safety_stock": 3},
        {"sku": "PROD-005", "name": "肥牛卷", "spec": "2.5kg/盒", "unit": "盒", "brand": "恒都", "category": "frozen_meat", "price": 145.0, "safety_stock": 10},
        {"sku": "PROD-006", "name": "羔羊肉卷", "spec": "2.5kg/盒", "unit": "盒", "brand": "小肥羊", "category": "frozen_meat", "price": 168.0, "safety_stock": 10},
        {"sku": "PROD-007", "name": "生菜", "spec": "500g/份", "unit": "份", "brand": "本地", "category": "vegetable", "price": 4.0, "safety_stock": 30},
        {"sku": "PROD-008", "name": "金针菇", "spec": "300g/盒", "unit": "盒", "brand": "本地", "category": "vegetable", "price": 6.0, "safety_stock": 25},
        {"sku": "PROD-009", "name": "火锅底料(麻辣)", "spec": "500g/袋", "unit": "袋", "brand": "名扬", "category": "seasoning", "price": 35.0, "safety_stock": 15},
        {"sku": "PROD-010", "name": "香油碟料包", "spec": "100套/箱", "unit": "箱", "brand": "自制", "category": "seasoning", "price": 120.0, "safety_stock": 5},
    ]

    # ==================== 知识库条目 ====================

    KNOWLEDGE_ITEMS = [
        {
            "title": "毛肚处理标准SOP",
            "content": "【菜品名称】精品毛肚\n【处理步骤】\n1. 解冻：提前4小时从冷冻室移至冷藏室（0~4℃）自然解冻\n2. 清洗：流动水下轻柔冲洗，去除杂质和多余脂肪\n3. 切片：逆纹路切薄片，厚度2-3mm，过大影响口感\n4. 涮烫：七上八下约8-10秒，起卷即熟，过久变老\n【品质标准】\n- 颜色：灰黑色有光泽\n- 质地：脆嫩有弹性\n- 气味：无异味\n【常见问题】\n- 发白：过度清洗或浸泡过久\n- 变韧：涮烫时间过长\n【损耗控制】\n- 解冻损耗控制在3%以内\n- 切片边角料可用于熬汤底",
            "category": "dish",
            "source_doc": "厨房SOP手册-v2.1",
        },
        {
            "title": "鸭肠清洗与摆盘规范",
            "content": "【预处理】\n1. 鸭肠用盐+醋揉搓去腥，清水冲净\n2. 入开水中焯烫10秒捞出过凉\n3. 沥干切段，每段长约8cm\n【摆盘标准】\n- 每盘200g±5g\n- 摆放整齐呈扇形\n- 配干碟调料包1份\n【出餐时间】\n- 点单后3分钟内上桌\n【注意事项】\n- 当日未售完的需当日处理，不可隔夜",
            "category": "dish",
            "source_doc": "前厅服务规范",
        },
        {
            "title": "高峰期备货量计算方法",
            "content": "【公式】预计销量 = 历史同期均值 × (1 + 天气系数) × (1 + 节假日系数) × 周末系数\n\n【参考系数】\n- 周末系数：工作日1.0 / 周六1.4 / 周日1.3\n- 节假日系数：普通日1.0 / 小长假1.6 / 春节2.2\n- 天气系数：晴1.0 / 多云0.95 / 雨0.8 / 雪天0.6 / 极热(>35℃)1.15\n\n【各品类占比参考】\n- 冻品肉类：45%（毛肚25%/鸭肠15%/其他5%）\n- 蔬菜：25%\n- 豆制品：12%\n- 饮料/其他：18%\n\n【安全库存】\n- 冻品：3天用量\n- 蔬菜：1天用量\n- 调料：7天用量",
            "category": "operation",
            "source_doc": "采购管理手册",
        },
        {
            "title": "冻品收货验收标准（潘厨版）",
            "content": "【温度要求】\n- 到货温度 ≤ -12℃（冷冻品）\n- 到货温度 0~8℃（冷藏品）\n- 超温拒收！\n\n【外观检查】\n- 包装完整无破损、无胀袋\n- 生产日期在保质期内（剩余≥2/3）\n- 无明显解冻痕迹（无血水、冰霜不过厚）\n\n【抽样比例】\n- ≤10箱：抽检2箱\n- 10~50箱：抽检20%\n- >50箱：抽检10%且不少于10箱\n\n【评级标准】\n- A级：温度/外观/日期全合格\n- B级：外观轻微瑕疵但可使用\n- C级：不合格，退换货",
            "category": "supplier",
            "source_doc": "收货验收SOP-v1.0",
        },
        {
            "title": "食品安全红线清单",
            "content": "【绝对禁止行为】\n1. 使用过期食材 → 即刻开除\n2. 生熟混放 → 严重警告+再培训\n3. 温度超标食材上架 → 记过+食材销毁\n4. 未戴手套接触直接入口食品 → 警告\n5. 患病上岗（腹泻/发热/皮肤感染）→ 停职检查\n\n【每日必查项】\n- 冷链温度记录（每2小时一次）\n- 食材留样（每样≥125g，留48小时）\n- 消毒记录（餐具/台面/地面）\n- 从业人员健康状态\n\n【应急处理】\n发现食品安全隐患 → 立即上报店长 → 隔离问题食材 → 记录并追踪",
            "category": "safety",
            "source_doc": "食品安全管理制度",
        },
        {
            "title": "门店成本结构分析模板",
            "content": "【火锅店典型成本结构】\n- 食材成本：38%~42%\n- 人工成本：18%~22%\n- 租金水电：10%~14%\n- 营销费用：3%~5%\n- 其他杂费：3%~5%\n- 净利润：8%~15%\n\n【关键降本抓手】\n1. 损耗控制：每降低1%损耗 ≈ 月省¥3000~8000（视规模）\n2. 采购优化：集中采购比零采便宜8%~15%\n3. 人效提升：合理排班可提升人效10%~20%\n4. 能耗管理：空调/冰柜定时开关，月省¥500~1500\n\n【火瞳系统贡献点】\n- 视觉检测降损耗 → 目标年省¥5万+\n- AI预测准订货 → 减少积压浪费¥3万+\n- SOP合规提效率 → 减少培训成本¥2万+\n- 供应链管控 → 采购议价能力提升¥5万+",
            "category": "finance",
            "source_doc": "经营分析报告-Q2",
        },
    ]

    def __init__(self, db_session: sqlite3.Connection):
        self.db = db_session
        self.rng = random.Random(42)  # 固定种子确保可复现

    # ==================== 核心生成方法 ====================

    def generate_all(self, days: int = 30) -> Dict[str, Any]:
        """一键生成全部演示数据
        
        Args:
            days: 生成多少天的历史数据（默认30天）
        
        Returns:
            生成统计信息
        """
        stats = {}
        logger.info("🎬 开始生成展会演示数据...")

        # 1. 基础数据（供应商+货品）
        stats["suppliers"] = self._generate_suppliers()
        stats["products"] = self._generate_products()

        # 2. 为每个店铺生成数据
        for store_key, store_cfg in self.STORES.items():
            sid = store_cfg["store_id"]
            sname = store_cfg["name"]

            # 收货记录
            stats[f"{sid}_receiving"] = self._generate_receiving_records(sid, days)

            # 采购订单
            stats[f"{sid}_orders"] = self._generate_purchase_orders(sid, days)

            # SOP检查信号和历史
            stats[f"{sid}_sop"] = self._generate_sop_history(sid, days)

            # 违规记录
            stats[f"{sid}_violations"] = self._generate_violations(sid, days)

            # KPI历史
            stats[f"{sid}_kpi"] = self._generate_kpi_history(sid, days)

            logger.info(f"  ✅ {sname} 数据生成完成")

        # 3. 全局知识库
        stats["knowledge"] = self._generate_knowledge()

        logger.info(f"🎉 演示数据全部生成完成！")
        return stats

    # ==================== 供应商与货品 ====================

    def _generate_suppliers(self) -> int:
        """生成供应商数据"""
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS suppliers (
                supplier_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                contact_person TEXT,
                phone TEXT,
                category TEXT,
                status TEXT DEFAULT 'active',
                rating REAL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        count = 0
        for s in self.SUPPLIERS:
            self.db.execute("""
                INSERT OR REPLACE INTO suppliers 
                (supplier_id, name, contact_person, phone, category, status, rating)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (s["supplier_id"], s["name"], s["contact_person"], s["phone"],
                  s["category"], s["status"], s["rating"]))
            count += 1
        self.db.commit()
        return count

    def _generate_products(self) -> int:
        """生成货品主数据"""
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS products (
                sku TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                spec TEXT,
                unit TEXT,
                brand TEXT,
                category TEXT,
                price REAL,
                safety_stock INTEGER,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        count = 0
        for p in self.PRODUCTS:
            self.db.execute("""
                INSERT OR REPLACE INTO products
                (sku, name, spec, unit, brand, category, price, safety_stock)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (p["sku"], p["name"], p["spec"], p["unit"], p["brand"],
                  p["category"], p["price"], p["safety_stock"]))
            count += 1
        self.db.commit()
        return count

    # ==================== 收货记录 ====================

    def _generate_receiving_records(self, store_id: str, days: int) -> int:
        """生成收货验收记录"""
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS receiving_records (
                record_id TEXT PRIMARY KEY,
                store_id TEXT NOT NULL,
                supplier_id TEXT,
                received_at TEXT,
                status TEXT DEFAULT 'completed',
                total_items INTEGER,
                inspector TEXT,
                notes TEXT
            )
        """)
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS receiving_items (
                item_id TEXT PRIMARY KEY,
                record_id TEXT NOT NULL,
                sku TEXT,
                product_name TEXT,
                quantity REAL,
                unit TEXT,
                batch_no TEXT,
                temperature REAL,
                quality_grade TEXT,
                is_accepted INTEGER DEFAULT 1
            )
        """)

        count = 0
        base_date = date.today() - timedelta(days=days)

        # 每家店每3天收一次货（共约10次）
        for day_offset in range(0, days, 3):
            rec_date = base_date + timedelta(days=day_offset)
            # 跳过未来日期
            if rec_date > date.today():
                continue

            # 随机选一个供应商（主要从王总方进货）
            supplier = self.SUPPLIERS[0] if self.rng.random() > 0.2 else self.rng.choice(self.SUPPLIERS)
            record_id = f"REC-{store_id}-{rec_date.strftime('%Y%m%d')}"
            inspector = "潘厨" if store_id == "store_jiaojiang" else "厨师长"

            # 生成收货明细（3-6个SKU）
            items_data = []
            total_temp_ok = True
            num_items = self.rng.randint(3, 6)
            selected_products = self.rng.sample(self.PRODUCTS, min(num_items, len(self.PRODUCTS)))

            for idx, prod in enumerate(selected_products):
                item_id = f"{record_id}-ITEM-{idx+1:02d}"

                # 温度模拟：大部分正常，偶尔异常（展示温控功能）
                if self.rng.random() < 0.08:  # 8%概率温度异常
                    temp = self.rng.uniform(-8, -2)  # 异常：偏高
                    grade = "C"
                    accepted = 0
                    total_temp_ok = False
                elif self.rng.random() < 0.15:  # 15%概率B级
                    temp = self.rng.uniform(-18, -13)
                    grade = "B"
                    accepted = 1
                else:  # 正常A级
                    temp = self.rng.uniform(-20, -15)
                    grade = "A"
                    accepted = 1

                items_data.append((item_id, record_id, prod["sku"], prod["name"],
                                   self.rng.uniform(1, 5), prod["unit"],
                                   f"B{rec_date.strftime('%Y%m%d')}{self.rng.randint(100,999)}",
                                   round(temp, 1), grade, accepted))

            status = "completed" if total_temp_ok else "exception"
            notes = None if total_temp_ok else f"部分商品温度异常，已隔离{sum(1 for i in items_data if i[9]==0)}件"

            self.db.execute("""
                INSERT OR REPLACE INTO receiving_records
                (record_id, store_id, supplier_id, received_at, status, total_items, inspector, notes)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (record_id, store_id, supplier["supplier_id"],
                  rec_date.isoformat(), status, len(items_data), inspector, notes))

            for item in items_data:
                self.db.execute("""
                    INSERT OR REPLACE INTO receiving_items
                    (item_id, record_id, sku, product_name, quantity, unit, batch_no, temperature, quality_grade, is_accepted)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, item)

            count += 1

        self.db.commit()
        return count

    # ==================== 采购订单 ====================

    def _generate_purchase_orders(self, store_id: str, days: int) -> int:
        """生成采购订单"""
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS purchase_orders (
                po_number TEXT PRIMARY KEY,
                store_id TEXT NOT NULL,
                supplier_id TEXT,
                status TEXT DEFAULT 'draft',
                created_at TEXT,
                submitted_at TEXT,
                confirmed_at TEXT,
                total_amount REAL,
                notes TEXT
            )
        """)
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS purchase_order_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                po_number TEXT NOT NULL,
                sku TEXT,
                product_name TEXT,
                quantity REAL,
                unit TEXT,
                unit_price REAL,
                subtotal REAL
            )
        """)

        count = 0
        base_date = date.today() - timedelta(days=days)

        for day_offset in range(2, days, 3):  # 收货前2天下订单
            order_date = base_date + timedelta(days=day_offset)
            if order_date > date.today():
                continue

            po_num = f"PO-{store_id.upper()[-2:]}-{order_date.strftime('%Y%m%d')}-{self.rng.randint(100,999)}"
            supplier = self.SUPPLIERS[0]  # 主要从王总方采购

            # 生成订单明细
            items_data = []
            total = 0.0
            num_items = self.rng.randint(4, 7)
            selected_products = self.rng.sample([p for p in self.PRODUCTS if p["category"] == "frozen_meat"],
                                                min(num_items, 6))

            for prod in selected_products:
                qty = self.rng.uniform(2, 8)
                subtotal = qty * prod["price"]
                items_data.append((po_num, prod["sku"], prod["name"], qty, prod["unit"], prod["price"], round(subtotal, 2)))
                total += subtotal

            submitted_at = (order_date + timedelta(hours=self.rng.randint(1, 3))).isoformat()
            confirmed_at = (order_date + timedelta(hours=self.rng.randint(4, 8))).isoformat()

            self.db.execute("""
                INSERT OR REPLACE INTO purchase_orders
                (po_number, store_id, supplier_id, status, created_at, submitted_at, confirmed_at, total_amount)
                VALUES (?, ?, ?, 'confirmed', ?, ?, ?, ?)
            """, (po_num, store_id, supplier["supplier_id"], order_date.isoformat(),
                  submitted_at, confirmed_at, round(total, 2)))

            for item in items_data:
                self.db.execute("""
                    INSERT INTO purchase_order_items (po_number, sku, product_name, quantity, unit, unit_price, subtotal)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """ , item)

            count += 1

        self.db.commit()
        return count

    # ==================== SOP检查历史 ====================

    def _generate_sop_history(self, store_id: str, days: int) -> int:
        """生成SOP检查信号数据（用于回测合规趋势）"""
        # 确保sop相关表存在
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS sop_check_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                store_id TEXT NOT NULL,
                zone TEXT,
                check_time TEXT,
                score REAL,
                passed INTEGER,
                failed INTEGER,
                pending INTEGER,
                details TEXT
            )
        """)

        store_cfg = self.STORES[store_id]
        base_compliance = store_cfg["sop_compliance_base"]
        count = 0
        base_date = date.today() - timedelta(days=days)
        zones = ["kitchen", "warehouse", "dining_hall"]

        for day_offset in range(days):
            check_date = base_date + timedelta(days=day_offset)
            if check_date > date.today():
                continue

            for zone in zones:
                # 模拟合规趋势：椒江店稳步上升，玉环店波动较大
                if store_id == "store_jiaojiang":
                    # 椒江店：从85%逐步上升到95%
                    trend_factor = min(1.0, 0.85 + (day_offset / days) * 0.12)
                    noise = self.rng.gauss(0, 0.03)
                else:
                    # 玉环店：波动大，平均78%
                    trend_factor = 0.75 + self.rng.gauss(0, 0.07)
                    noise = 0

                compliance_rate = max(0.5, min(1.0, trend_factor + noise))
                total_checks = self.rng.randint(8, 12)
                passed = int(total_checks * compliance_rate)
                failed = int(total_checks * (1 - compliance_rate) * 0.7)
                pending = total_checks - passed - failed
                score = compliance_rate * 100

                self.db.execute("""
                    INSERT INTO sop_check_history
                    (store_id, zone, check_time, score, passed, failed, pending, details)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (store_id, zone,
                      (check_date + timedelta(hours=self.rng.randint(8, 22))).isoformat(),
                      round(score, 1), passed, failed, pending, None))
                count += 1

        self.db.commit()
        return count

    # ==================== 违规记录 ====================

    def _generate_violations(self, store_id: str, days: int) -> int:
        """生成违规记录"""
        # 确保表存在
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS sop_violations (
                violation_id TEXT PRIMARY KEY,
                store_id TEXT NOT NULL,
                rule_id TEXT,
                rule_name TEXT,
                severity TEXT,
                zone TEXT,
                status TEXT DEFAULT 'open',
                detected_at TEXT,
                acknowledged_at TEXT,
                resolved_at TEXT,
                acknowledged_by TEXT,
                resolved_by TEXT,
                evidence TEXT,
                corrective_action TEXT
            )
        """)

        store_cfg = self.STORES[store_id]
        base_compliance = store_cfg["sop_compliance_base"]

        # 违规场景定义
        VIOLATION_SCENARIOS = [
            ("SOP-KITCHEN-001", "口罩佩戴不规范", "major", "kitchen",
             "后厨区域检测到工作人员未正确佩戴口罩"),
            ("SOP-KITCHEN-002", "洗手频次不足", "minor", "kitchen",
             "洗手间隔超过30分钟"),
            ("SOP-KITCHEN-003", "着装不整", "info", "kitchen",
             "工作服扣子未扣好"),
            ("SOP-WAREHOUSE-001", "冷库温度偏高", "critical", "warehouse",
             "冷库A区温度-9℃，超出安全范围"),
            ("SOP-WAREHOUSE-002", "FEFO违规", "major", "warehouse",
             "先入库的毛肚未被优先使用"),
            ("SOP-DINING-001", "桌面清洁不及时", "minor", "dining_hall",
             "顾客离桌后5分钟内未完成清洁"),
        ]

        count = 0
        base_date = date.today() - timedelta(days=days)

        # 每天生成0-3条违规（根据店铺合规水平调整概率）
        for day_offset in range(days):
            viol_date = base_date + timedelta(days=day_offset)
            if viol_date > date.today():
                continue

            # 违规概率：合规率高则违规少
            viol_prob = (100 - base_compliance) / 100 * 0.6
            num_violations = sum(1 for _ in range(3) if self.rng.random() < viol_prob)

            for i in range(num_violations):
                scenario = self.rng.choice(VIOLATION_SCENARIOS)
                viol_id = f"VIOL-{store_id[-2:].upper()}-{viol_date.strftime('%Y%m%d')}-{count+1:03d}"

                # 大部分违规最终被解决
                status_roll = self.rng.random()
                if status_roll < 0.6:
                    status = "resolved"
                    ack_at = (viol_date + timedelta(hours=self.rng.randint(1, 4))).isoformat()
                    res_at = (viol_date + timedelta(hours=self.rng.randint(5, 24))).isoformat()
                elif status_roll < 0.85:
                    status = "acknowledged"
                    ack_at = (viol_date + timedelta(hours=self.rng.randint(1, 4))).isoformat()
                    res_at = None
                else:
                    status = "open"
                    ack_at = None
                    res_at = None

                self.db.execute("""
                    INSERT INTO sop_violations
                    (violation_id, store_id, rule_id, rule_name, severity, zone, status,
                     detected_at, acknowledged_at, resolved_at, acknowledged_by, resolved_by,
                     evidence, corrective_action)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (viol_id, store_id, scenario[0], scenario[1], scenario[2], scenario[3],
                      status, viol_date.isoformat(), ack_at, res_at,
                      "值班经理" if ack_at else None,
                      "店长" if status == "resolved" else None,
                      "视觉AI自动检测截图" if scenario[2] in ("critical", "major") else "巡检发现",
                      scenario[4]))
                count += 1

        self.db.commit()
        return count

    # ==================== KPI历史数据 ====================

    def _generate_kpi_history(self, store_id: str, days: int) -> int:
        """生成KPI历史数据"""
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS kpi_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                store_id TEXT NOT NULL,
                metric_id TEXT NOT NULL,
                value REAL,
                status TEXT,
                trend TEXT,
                recorded_date TEXT
            )
        """)

        store_cfg = self.STORES[store_id]
        count = 0
        base_date = date.today() - timedelta(days=days)

        kpi_configs = [
            ("daily_revenue", store_cfg["daily_revenue_base"], 2000, "higher_better"),
            ("waste_rate", store_cfg["waste_rate_base"] * 100, 1.5, "lower_better"),   # 转为百分比
            ("table_turnover", store_cfg["table_turnover_base"], 0.3, "higher_better"),
            ("customer_count", store_cfg["customer_count_base"], 25, "higher_better"),
            ("avg_ticket", store_cfg["daily_revenue_base"] / store_cfg["customer_count_base"], 8, "stable"),
            ("sop_compliance", store_cfg["sop_compliance_base"], 5, "higher_better"),
            ("inventory_accuracy", store_cfg["inventory_accuracy_base"], 4, "higher_better"),
            ("labor_efficiency", store_cfg["labor_efficiency_base"], 15, "higher_better"),
        ]

        for day_offset in range(days):
            kpi_date = base_date + timedelta(days=day_offset)
            if kpi_date > date.today():
                continue

            # 周末效应
            weekday = kpi_date.weekday()
            weekend_factor = 1.35 if weekday >= 5 else 1.0

            for metric_id, base_val, stddev, direction in kpi_configs:
                # 加入趋势和噪声
                if store_id == "store_jiaojiang":
                    trend = 1.0 + (day_offset / days) * 0.03  # 缓慢改善
                else:
                    trend = 1.0 + self.rng.gauss(0, 0.02)

                noise = self.rng.gauss(0, 1)
                value = base_val * trend * weekend_factor + noise * stddev

                # 方向修正
                if direction == "lower_better":
                    value = base_val / trend + noise * stddev * 0.5

                value = max(0, round(value, 2))

                # 状态判定
                if direction == "lower_better":
                    if value <= base_val * 0.9:
                        status = "good"
                    elif value >= base_val * 1.2:
                        status = "danger"
                    else:
                        status = "warning" if value > base_val * 1.1 else "normal"
                else:
                    if value >= base_val * 1.05:
                        status = "good"
                    elif value <= base_val * 0.85:
                        status = "danger"
                    else:
                        status = "warning" if value < base_val * 0.95 else "normal"

                # 趋势判断（与前一天对比）
                trend_label = "stable"
                if day_offset > 0 and self.rng.random() > 0.5:
                    trend_label = self.rng.choice(["up", "down", "stable"])

                self.db.execute("""
                    INSERT INTO kpi_history
                    (store_id, metric_id, value, status, trend, recorded_date)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (store_id, metric_id, value, status, trend_label, kpi_date.isoformat()))
                count += 1

        self.db.commit()
        return count

    # ==================== 知识库 ====================

    def _generate_knowledge(self) -> int:
        """生成知识库条目"""
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS knowledge_base (
                item_id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                content TEXT,
                category TEXT,
                source_doc TEXT,
                author TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT,
                is_deleted INTEGER DEFAULT 0
            )
        """)

        count = 0
        for item in self.KNOWLEDGE_ITEMS:
            item_id = f"KB-{count+1:04d}"
            now = datetime.now().isoformat()
            self.db.execute("""
                INSERT OR REPLACE INTO knowledge_base
                (item_id, title, content, category, source_doc, author, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, '系统管理员', ?, ?)
            """, (item_id, item["title"], item["content"], item["category"],
                  item.get("source_doc", ""), now, now))
            count += 1

        self.db.commit()
        return count


# ==================== 便捷函数 ====================

def generate_demo_data(db_session: sqlite3.Connection, days: int = 30) -> Dict[str, Any]:
    """便捷函数：生成全部演示数据
    
    Args:
        db_session: SQLite数据库连接
        days: 生成多少天的历史数据
    
    Returns:
        生成统计信息字典
    """
    generator = DemoDataGenerator(db_session)
    return generator.generate_all(days)
