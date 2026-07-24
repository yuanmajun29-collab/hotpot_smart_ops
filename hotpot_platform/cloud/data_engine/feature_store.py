"""
火瞳 · 数据引擎 — N03 特征工程 (Feature Store)

FeatureStore 从 sales_daily 表构建时间序列特征, 供预测模型消费。
设计原则: 零外部依赖, callback 模式注入数据源, 所有特征可解释。
"""

from typing import Dict, List, Optional, Callable
from datetime import date, timedelta
import calendar


# ---------------------------------------------------------------------------
# 类型别名
# ---------------------------------------------------------------------------

# 数据源回调签名: (store_id, sku, start_date, end_date) → Dict[date, float]
SalesCallback = Callable[[str, str, date, date], Dict[date, float]]


# ---------------------------------------------------------------------------
# 中国法定节假日 (简化版, 足够火锅场景使用)
# ---------------------------------------------------------------------------

_HOLIDAY_DATE_SET: Dict[int, set] = {
    2025: {
        (1, 1),   # 元旦
        *( (1, d) for d in range(28, 31) ),   # 春节除夕-初七 (简化)
        *( (2, d) for d in range(1, 5) ),
        (4, 4), (4, 5), (4, 6),                # 清明
        (5, 1), (5, 2), (5, 3), (5, 4), (5, 5), # 劳动节
        *( (5, d) for d in range(31, 32) ),    # 端午
        (6, 1), (6, 2),
        (10, 1), (10, 2), (10, 3), (10, 4), (10, 5), (10, 6), (10, 7), (10, 8), # 国庆+中秋合并
    },
    2026: {
        (1, 1), (1, 2), (1, 3),
        *( (2, d) for d in range(16, 23) ),    # 春节
        (4, 4), (4, 5), (4, 6),
        (5, 1), (5, 2), (5, 3), (5, 4), (5, 5),
        (6, 19), (6, 20), (6, 21),             # 端午 (农历五月初五 ≈ 2026-06-19)
        (9, 25), (9, 26), (9, 27),             # 中秋 (农历八月十五 ≈ 2026-09-25)
        (10, 1), (10, 2), (10, 3), (10, 4), (10, 5), (10, 6), (10, 7),
    },
    2027: {
        (1, 1), (1, 2), (1, 3),
        *( (2, d) for d in range(5, 12) ),     # 春节
        (4, 4), (4, 5), (4, 6),
        (5, 1), (5, 2), (5, 3), (5, 4), (5, 5),
    },
}

# 特殊节日 (非公假但显著影响火锅消费): 元宵、七夕、平安夜、跨年夜
_SPECIAL_EVENT_DATE_SET: Dict[int, Dict[tuple, str]] = {
    2025: {
        (2, 12): "元宵节",
        (8, 29): "七夕",
        (12, 24): "平安夜",
        (12, 31): "跨年夜",
    },
    2026: {
        (3, 3): "元宵节",
        (8, 19): "七夕",
        (12, 24): "平安夜",
        (12, 31): "跨年夜",
    },
    2027: {
        (2, 20): "元宵节",
        (8, 8): "七夕",
        (12, 24): "平安夜",
        (12, 31): "跨年夜",
    },
}


# ---------------------------------------------------------------------------
# FeatureStore
# ---------------------------------------------------------------------------

class FeatureStore:
    """
    时间序列特征构建器。

    从 sales_daily 表拉取历史销量, 构建结构化特征字典, 供 L1/L2/L3 各级预测模型消费。

    用法:
        store = FeatureStore(fetch_sales=my_db.query_sales_daily)
        features = store.build_features("S001", "肥牛", date(2026, 7, 26))
    """

    DEFAULT_LOOKBACK_DAYS = 90

    def __init__(self, fetch_sales: Optional[SalesCallback] = None):
        """
        Args:
            fetch_sales: 数据源回调 (store_id, sku, start, end) → Dict[date, qty]。
                         未注入时特征构建会返回空历史, 但基础维度 (星期/节假日) 仍然有效。
        """
        self.fetch_sales = fetch_sales

    # ------------------------------------------------------------------
    # 主入口
    # ------------------------------------------------------------------

    def build_features(
        self,
        store_id: str,
        sku: str,
        target_date: date,
    ) -> Dict:
        """
        构建完整特征字典。

        Args:
            store_id: 门店 ID
            sku:      单品编码
            target_date: 目标日期 (预测日)

        Returns:
            {
                "date": str,
                "lag_1": float, "lag_7": float, "lag_14": float,
                "ma_7": float, "ma_14": float, "ma_28": float,
                "weekday": int (0=Mon),
                "is_weekend": bool,
                "is_holiday": bool,
                "holiday_name": Optional[str],
                "day_of_month": int,
                "month": int,
                "quarter": int,
                "weather_factor": Optional[float],  # 预留
            }
        """
        history = self._load_history(store_id, sku, target_date)

        features: Dict = {
            "date": target_date.isoformat(),
        }

        # --- 滞后特征 ---
        features["lag_1"] = history.get(target_date - timedelta(days=1), 0.0)
        features["lag_7"] = history.get(target_date - timedelta(days=7), 0.0)
        features["lag_14"] = history.get(target_date - timedelta(days=14), 0.0)

        # --- 移动平均 ---
        features["ma_7"] = self._ma(history, target_date, 7)
        features["ma_14"] = self._ma(history, target_date, 14)
        features["ma_28"] = self._ma(history, target_date, 28)

        # --- 时间维度 ---
        features["weekday"] = target_date.weekday()
        features["is_weekend"] = target_date.weekday() >= 5
        features["day_of_month"] = target_date.day
        features["month"] = target_date.month
        features["quarter"] = (target_date.month - 1) // 3 + 1

        # --- 节假日 ---
        holiday_info = self._check_holiday(target_date)
        features["is_holiday"] = holiday_info["is_holiday"]
        features["holiday_name"] = holiday_info["name"]

        # --- 天气因子 (预留) ---
        features["weather_factor"] = None  # 未来接入气象 API

        return features

    # ------------------------------------------------------------------
    # 内部 helper
    # ------------------------------------------------------------------

    def _load_history(self, store_id: str, sku: str, target_date: date) -> Dict[date, float]:
        """通过回调加载历史数据, 未注入回调时返回空字典。"""
        if self.fetch_sales is None:
            return {}
        start = target_date - timedelta(days=self.DEFAULT_LOOKBACK_DAYS)
        return self.fetch_sales(store_id, sku, start, target_date)

    @staticmethod
    def _ma(history: Dict[date, float], target_date: date, window: int) -> float:
        """计算目标日之前 window 天的移动平均。"""
        vals: List[float] = []
        for d in range(1, window + 1):
            v = history.get(target_date - timedelta(days=d))
            if v is not None:
                vals.append(v)
        if not vals:
            return 0.0
        return round(sum(vals) / len(vals), 4)

    @staticmethod
    def _check_holiday(target_date: date) -> Dict:
        """检查是否为法定节假日或特殊消费日。"""
        key = (target_date.month, target_date.day)

        # 法定节假日
        holiday_dates = _HOLIDAY_DATE_SET.get(target_date.year, set())
        if key in holiday_dates:
            return {"is_holiday": True, "name": "法定节假日"}

        # 特殊事件
        special = _SPECIAL_EVENT_DATE_SET.get(target_date.year, {})
        if key in special:
            return {"is_holiday": False, "name": special[key]}

        return {"is_holiday": False, "name": None}
