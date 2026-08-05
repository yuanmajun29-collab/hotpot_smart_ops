"""火瞳 · 模拟数据服务

集中管理所有演示/展会模式下的模拟数据生成，解决:
- 随机种子竞态条件（全局 random.seed() 并发不安全）
- 模拟数据散落在各 Agent 方法中难以维护
- 无法统一切换真实/模拟数据源

使用方式:
    from .mock_data_service import MockDataService

    mock_svc = MockDataService(seed=42)
    iot_data = mock_svc.generate_iot_temperature(store_id)
    dirty_tables = mock_svc.detect_dirty_tables()

作者: 火瞳AI团队
日期: 2026-08-05
"""

from __future__ import annotations

import logging
import random
from datetime import datetime
from typing import Any, Dict, List, Optional


logger = logging.getLogger(__name__)


class MockDataService:
    """模拟数据服务 - 线程安全的模拟数据生成器

    将散落在各 Agent 中的硬编码模拟数据和随机数生成为集中管理，
    支持可重现的测试和并发安全的运行时。

    Attributes:
        _seed: 随机种子（用于可重现的测试结果）
        _rng: 实例级随机数生成器（避免全局状态污染）
        _store_profiles: 门店配置档案（从配置文件加载）
        _dish_menu: 菜品菜单数据（从配置文件加载）
    """

    def __init__(self, seed: Optional[int] = None):
        """初始化模拟数据服务

        Args:
            seed: 随机种子（None 表示不固定种子，每次结果不同）
        """
        self._seed = seed
        self._rng = random.Random(seed) if seed is not None else random.Random()

        # 从配置文件加载（延迟导入避免循环依赖）
        try:
            from .config_loader import get_config
            self._store_profiles = get_config('stores', {})
            self._dish_menu = get_config('dish_menu', [])
            logger.debug("从配置文件加载了 %d 个门店, %d 道菜品",
                        len(self._store_profiles), len(self._dish_menu))
        except Exception as e:
            logger.warning("配置文件加载失败，使用默认值: %s", e)
            self._store_profiles = {}
            self._dish_menu = []

        logger.info("MockDataService 初始化完成 (seed=%s)", seed)

    def regenerate_rng(self, new_seed: Optional[int] = None):
        """重新生成随机数生成器（用于每个请求周期重置）

        Args:
            new_seed: 新的种子值
        """
        self._seed = new_seed if new_seed is not None else self._seed
        self._rng = random.Random(self._seed)
        logger.debug("RNG 已重置 (seed=%s)", self._seed)

    # ── IoT 传感器数据 ─────────────────────────────────────

    def generate_iot_temperature(self, store_id: str) -> Dict[str, Any]:
        """生成 IoT 温度传感器模拟数据

        模拟厨房冷柜温度监控，包含正常和异常阈值检测。

        Args:
            store_id: 门店ID

        Returns:
            温度传感器数据字典，含读数、告警信息
        """
        sensors = self._store_profiles.get(store_id, {}).get(
            "iot_sensors",
            ["sensor_kitchen_temp_01", "sensor_fridge_01"]
        )

        readings = []
        alerts = []

        for sensor_id in sensors:
            if "fridge" in sensor_id:
                # 冷柜温度: 正常范围 2-8°C
                temp = round(self._rng.uniform(-2, 12), 1)
                status = "normal" if 2 <= temp <= 8 else ("too_cold" if temp < 2 else "too_warm")
                if status != "normal":
                    alerts.append({
                        "sensor_id": sensor_id,
                        "type": "temperature_out_of_range",
                        "current_value": temp,
                        "threshold_min": 2,
                        "threshold_max": 8,
                        "severity": "warning" if abs(temp - 5) < 5 else "critical",
                    })
            else:
                # 厨房环境温度: 正常范围 20-30°C
                temp = round(self._rng.uniform(18, 35), 1)
                status = "normal" if 20 <= temp <= 30 else ("too_cold" if temp < 20 else "too_hot")
                if status != "normal":
                    alerts.append({
                        "sensor_id": sensor_id,
                        "type": "temperature_out_of_range",
                        "current_value": temp,
                        "threshold_min": 20,
                        "threshold_max": 30,
                        "severity": "warning",
                    })

            readings.append({
                "sensor_id": sensor_id,
                "temperature_celsius": temp,
                "status": status,
                "timestamp": datetime.now().isoformat(),
            })

        return {
            "task_type": "iot_temperature",
            "store_id": store_id,
            "temperatures": readings,
            "alerts": alerts,
            "alert_count": len(alerts),
            "data_source": "iot_sensor_simulation",
            "generated_at": datetime.now().isoformat(),
        }

    # ── 视觉检测数据 ───────────────────────────────────────

    def detect_dirty_tables(self, store_id: str, camera_ids: Optional[List[str]] = None) -> Dict[str, Any]:
        """检测脏桌（模拟视觉引擎结果）

        Args:
            store_id: 门店ID
            camera_ids: 摄像头ID列表（可选）

        Returns:
            脏桌检测结果，含脏桌列表、置信度等
        """
        if camera_ids is None:
            camera_ids = self._store_profiles.get(store_id, {}).get(
                "camera_ids",
                ["camera_jiaojiang_hikvision_nvr"]
            )

        # 随机生成 1-3 张脏桌
        dirty_count = self._rng.randint(1, 3)
        table_ids = [f"T{str(i).zfill(2)}" for i in range(1, 9)]  # T01-T08
        dirty_tables = self._rng.sample(table_ids, dirty_count)

        tables = []
        for table_id in dirty_tables:
            tables.append({
                "table_id": table_id,
                "status": "need_clean",
                "dirty_since_min": self._rng.randint(2, 15),
                "confidence": round(self._rng.uniform(0.80, 0.98), 2),
            })

        return {
            "task_type": "dirty_table_detection",
            "detected_at": datetime.now().isoformat(),
            "source": camera_ids[0] if camera_ids else "unknown_camera",
            "tables": tables,
            "total_dirty": len(tables),
            "action": "auto_create_tasks",
        }

    # ── POS 销售数据 ────────────────────────────────────────

    def calculate_turnover_rate(self, store_id: str, date: Optional[str] = None) -> Dict[str, Any]:
        """计算翻台率（模拟POS数据）

        Args:
            store_id: 门店ID
            date: 日期字符串（可选，默认今天）

        Returns:
            翻台率数据，含午市/晚市/日均翻台率
        """
        profile = self._store_profiles.get(store_id, {})

        # 基于目标值添加小幅随机波动
        lunch_turns = round(
            profile.get("target_turnover_lunch", 2.0) * self._rng.uniform(0.90, 1.10), 1
        )
        dinner_turns = round(
            profile.get("target_turnover_dinner", 2.5) * self._rng.uniform(0.85, 1.15), 1
        )

        lunch_revenue = int(profile.get("target_revenue_lunch", 5000) * self._rng.uniform(0.85, 1.10))
        dinner_revenue = int(profile.get("target_revenue_dinner", 8000) * self._rng.uniform(0.85, 1.15))

        daily_avg = round((lunch_turns + dinner_turns) / 2, 2)
        target = profile.get("target_turnover_dinner", 2.5)

        # 判断状态
        ratio = daily_avg / target if target > 0 else 0
        if ratio >= 0.95:
            status = "at_target"
        elif ratio >= 0.85:
            status = "near_target"
        else:
            status = "below_target"

        return {
            "task_type": "turnover_rate",
            "date": date or datetime.now().strftime("%Y-%m-%d"),
            "lunch": {"tables": profile.get("tables_count", 8), "turns": lunch_turns, "revenue": lunch_revenue},
            "dinner": {"tables": profile.get("tables_count", 8), "turns": dinner_turns, "revenue": dinner_revenue},
            "daily_avg": daily_avg,
            "target": target,
            "status": status,
        }

    # ── 采购预测数据 ────────────────────────────────────────

    def generate_purchase_history(self, item_id: str, days: int = 30) -> List[int]:
        """生成采购历史销量数据

        使用实例级 RNG 生成可重现的历史数据。

        Args:
            item_id: 商品ID（用于影响随机分布）
            days: 历史天数

        Returns:
            历史销量列表
        """
        # 基于 item_id 生成稳定的偏移量
        base_qty = 50 + (hash(item_id) % 70)  # 50-120 范围

        history = []
        for _ in range(days):
            # 添加 ±20% 的随机波动
            qty = int(base_qty * self._rng.uniform(0.80, 1.20))
            history.append(qty)

        return history

    def predict_purchase_quantity(
        self,
        item_id: str,
        days: int = 7,
        has_promo: bool = False,
        seasonal_factor: float = 0.85,
    ) -> Dict[str, Any]:
        """智能采购量预测（WMA算法 + 因子调整）

        Args:
            item_id: 商品ID
            days: 用于计算的最近天数
            has_promo: 是否有促销计划
            seasonal_factor: 季节因子（夏季淡季 0.85）

        Returns:
            预测结果，含预测量、置信度、应用因子
        """
        # 生成历史数据
        history_30d = self.generate_purchase_history(item_id, 30)
        history_7d = history_30d[-days:]

        # WMA 计算（权重: 最近一天权重最高）
        weights = list(range(1, len(history_7d) + 1))
        wma_numerator = sum(w * d for w, d in zip(weights, history_7d))
        wma_denominator = sum(weights)
        wma_base = round(wma_numerator / wma_denominator, 1)

        # 促销调整
        promo_factor = 1.2 if has_promo else 1.0

        # 最终预测量
        predicted_qty = int(wma_base * seasonal_factor * promo_factor)

        # 置信度评估（基于变异系数）
        avg_7d = sum(history_7d) / len(history_7d) if history_7d else 1
        variance = sum((x - avg_7d) ** 2 for x in history_7d) / len(history_7d)
        std_dev = variance ** 0.5
        cv = (std_dev / avg_7d * 100) if avg_7d > 0 else 0
        confidence = "high" if cv < 15 else ("medium" if cv < 25 else "low")

        return {
            "task_type": "purchase_quantity_prediction",
            "item_id": item_id,
            "prediction": {
                "predicted_qty": predicted_qty,
                "unit": "kg",
                "confidence": confidence,
                "confidence_pct": round(max(60, min(95, 100 - cv)), 1),
                "wma_base": wma_base,
                "history_days_used": days,
            },
            "factors_applied": {
                "seasonal_factor": seasonal_factor,
                "seasonal_note": "夏季火锅淡季调整",
                "promo_factor": promo_factor,
                "promo_note": "促销计划调整" if has_promo else "无促销",
                "final_adjustment": round(seasonal_factor * promo_factor, 2),
            },
            "historical_summary": {
                "avg_7d": round(avg_7d, 1),
                "avg_30d": round(sum(history_30d) / len(history_30d), 1),
                "trend": "increasing" if history_7d[-1] > history_7d[0] else "decreasing",
            },
            "recommendation": f"建议采购 {predicted_qty}kg，置信度{confidence}",
        }

    # ── 菜品知识库查询 ──────────────────────────────────────

    def get_dish_info(self, sku: Optional[str] = None) -> Dict[str, Any]:
        """查询菜品信息

        Args:
            sku: 菜品SKU（可选，不传则返回全部）

        Returns:
            菜品信息字典或列表
        """
        if sku:
            for dish in self._dish_menu:
                if dish["sku"] == sku:
                    return dict(dish)
            return {"error": f"菜品 {sku} 未找到"}

        return {
            "total": len(self._dish_menu),
            "dishes": list(self._dish_menu),
        }

    # ── 服务术语库 ──────────────────────────────────────────

    @staticmethod
    def get_service_terminology() -> Dict[str, str]:
        """获取标准服务术语库

        Returns:
            场景→话术 映射字典
        """
        return {
            "greeting": "欢迎光临火瞳火锅！请问几位用餐？",
            "seating": "这边请，您的位置在靠窗的位置，视野很好。",
            "ordering": "推荐您试试我们的招牌毛肚和精品鸭肠，都是今日新鲜到货的。",
            "upsell": "餐后来份冰粉吧？解辣又清爽，今天还有活动价。",
            "handling_complaint": "非常抱歉给您带来不好的体验，我马上叫经理来处理，请您稍等。",
            "farewell": "谢谢光临，慢走！下次再来记得提前预约留位哦。",
        }


# 全局单例（默认使用 seed=42 保证可重现性）
_default_mock_service: Optional[MockDataService] = None


def get_mock_service(seed: Optional[int] = 42) -> MockDataService:
    """获取全局 MockDataService 单例

    Args:
        seed: 随机种子（仅在首次调用时生效）

    Returns:
        MockDataService 实例
    """
    global _default_mock_service
    if _default_mock_service is None:
        _default_mock_service = MockDataService(seed=seed)
    return _default_mock_service
