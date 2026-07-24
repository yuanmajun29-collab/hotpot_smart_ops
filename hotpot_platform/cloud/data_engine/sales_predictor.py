"""
火瞳 · 数据引擎 — 销量预测器 (N01)

四级预测降级链:
  L1 (RuleBaseline)  — 移动平均/同周环比, 零依赖, 永远可用
  L2 (StatisticalModel) — SARIMA 季节性时序, 需 statsmodels
  L3 (MLModel)           — LightGBM 多因子回归, 需 60+ 天数据
  L4 (LLMEnhancer)       — 复用 forecast_agent 的 LLM 推理增强

逐层尝试, 任一层失败/不可用时优雅降级到下一层。L4 不替代预测,
而是对前一层的结果做自然语言增强。

数据访问采用 callback/hook 模式: 通过注入 data_loader 和 sku_lister
解耦数据库实现, 不直接依赖具体 DB 驱动。

使用示例:
    >>> from data_engine import SalesPredictor
    >>> 
    >>> def my_loader(store_id, sku, start, end):
    ...     rows = db.query("SELECT * FROM sales_daily WHERE ...")
    ...     return [SalesRecord(**r) for r in rows]
    >>> 
    >>> predictor = SalesPredictor(data_loader=my_loader, sku_lister=my_sku_list)
    >>> forecast = predictor.predict("S001", "毛肚", date.today())
    >>> print(forecast.predicted_qty, forecast.confidence, forecast.model_version)
"""

from typing import Callable, Dict, List, Optional
from datetime import date, timedelta
import math

from .models import SalesForecast, SalesRecord
from .algorithms.baseline import (
    RuleBaseline,
    StatisticalModel,
    MLModel,
    LLMEnhancer,
)

# ── 回调类型别名 ──────────────────────────────────────────────

DataLoader = Callable[[str, str, date, date], List[SalesRecord]]
"""数据加载回调签名: (store_id, sku, start_date, end_date) -> List[SalesRecord]
start_date/end_date 为闭区间。"""

SkuLister = Callable[[str], List[str]]
"""SKU 列表回调签名: (store_id) -> List[sku]"""


# ── SalesPredictor ────────────────────────────────────────────

class SalesPredictor:
    """
    销量预测器。

    四级降级链在每次 predict() 调用中自动执行:
      1. L1 RuleBaseline   — 永远成功, 作为保底
      2. L2 StatisticalModel — 尝试 SARIMA, 失败则保持 L1 结果
      3. L3 MLModel         — 尝试 LightGBM, 失败则保持当前结果
      4. L4 LLMEnhancer     — 对最终结果做 LLM 增强 (可选)

    Parameters
    ----------
    data_loader : DataLoader, optional
        历史销量数据加载回调。若为 None, predict() 会 raise ValueError。
    sku_lister : SkuLister, optional
        SKU 列表回调, batch_predict() 需要。若为 None, batch_predict() 会 raise。
    """

    # 历史回溯天数 (供各层级算法使用)
    HISTORY_LOOKBACK_DAYS = 90

    def __init__(
        self,
        data_loader: Optional[DataLoader] = None,
        sku_lister: Optional[SkuLister] = None,
    ):
        self.data_loader = data_loader
        self.sku_lister = sku_lister

        # 四级预测器实例
        self.l1 = RuleBaseline()
        self.l2 = StatisticalModel()
        self.l3 = MLModel()
        self.l4 = LLMEnhancer()

    # ── 核心 API ───────────────────────────────────────────

    def predict(
        self,
        store_id: str,
        sku: str,
        target_date: date,
    ) -> SalesForecast:
        """
        单 SKU 单日预测。

        Returns
        -------
        SalesForecast
            包含 predicted_qty / confidence / model_version / bounds。
        """
        history = self._load_history_dict(store_id, sku, target_date)

        # ── L1: 规则基线 (永远可用) ──
        result = self.l1.predict(store_id, sku, target_date, history)

        # ── L2: 统计模型 ──
        result_l2 = self.l2.predict(store_id, sku, target_date, history)
        if not result_l2.get("degraded"):
            result = result_l2

        # ── L3: 机器学习 ──
        result_l3 = self.l3.predict(store_id, sku, target_date, {}, history)
        if not result_l3.get("degraded"):
            result = result_l3

        # ── L4: LLM 增强 ──
        result = self.l4.enhance(
            result,
            context=f"store={store_id}, sku={sku}, target={target_date.isoformat()}",
        )

        # 计算预测区间
        lower, upper = self._compute_bounds(
            result["predicted_qty"], result["confidence"]
        )

        return SalesForecast(
            store_id=store_id,
            sku=sku,
            forecast_date=target_date,
            predicted_qty=result["predicted_qty"],
            confidence=result["confidence"],
            lower_bound=lower,
            upper_bound=upper,
            model_version=result.get("model_version", "L1-rule"),
            features_used=result,
        )

    def batch_predict(
        self,
        store_id: str,
        target_date: date,
        horizon_days: int = 7,
    ) -> List[SalesForecast]:
        """
        门店全 SKU 多日滚动预测。

        对门店下所有 SKU, 在 [target_date, target_date + horizon_days)
        范围内逐日预测。

        Parameters
        ----------
        store_id : str
            门店 ID。
        target_date : date
            预测起始日期。
        horizon_days : int
            预测天数 (默认 7)。

        Returns
        -------
        List[SalesForecast]
            按 (sku, date) 排序的预测结果列表。
        """
        if self.sku_lister is None:
            raise ValueError(
                "batch_predict 需要注入 sku_lister 回调; "
                "请在构造 SalesPredictor 时提供 sku_lister 参数。"
            )

        skus = self.sku_lister(store_id)
        if not skus:
            return []

        forecasts: List[SalesForecast] = []
        for offset in range(horizon_days):
            day = target_date + timedelta(days=offset)
            for sku in skus:
                forecast = self.predict(store_id, sku, day)
                forecasts.append(forecast)

        return forecasts

    def evaluate(
        self,
        store_id: str,
        sku: str,
        eval_days: int = 30,
    ) -> Dict:
        """
        回测评估: 对过去 N 天做逐日 walk-forward 预测, 对比实际销量。

        Parameters
        ----------
        store_id : str
        sku : str
        eval_days : int
            回测天数 (默认 30)。最大不超过 HIST_LOOKBACK_DAYS。

        Returns
        -------
        Dict
            {
                "MAPE": float,           # 平均绝对百分比误差 (%)
                "RMSE": float,           # 均方根误差
                "bias_rate": float,      # 偏差率 (预测-实际)/实际
                "n_days": int,           # 有效评估天数
                "model_version": str,    # 最终使用的模型版本
                "daily_details": [...]   # 每日明细 (可选)
            }
        """
        if eval_days > self.HISTORY_LOOKBACK_DAYS:
            eval_days = self.HISTORY_LOOKBACK_DAYS

        today = date.today()
        eval_start = today - timedelta(days=eval_days)

        # 拉取整个评估窗口的实际数据 (含评估开始前的历史)
        full_start = eval_start - timedelta(days=self.HISTORY_LOOKBACK_DAYS)
        all_records = self._load_history(store_id, sku, full_start, today)
        all_history = {r.business_date: r.qty_sold for r in all_records}

        actuals = []
        predictions = []
        daily_details = []

        for offset in range(eval_days):
            eval_date = eval_start + timedelta(days=offset)
            if eval_date >= today:
                break  # 不超过今天

            actual = all_history.get(eval_date)
            if actual is None or actual == 0:
                continue  # 跳过无销量日

            # 只用 eval_date 之前的数据做预测
            hist_before = {
                d: v for d, v in all_history.items() if d < eval_date
            }

            # 四级降级链 (不含 L4, 回测不需要 LLM 增强)
            result = self.l1.predict(store_id, sku, eval_date, hist_before)

            l2_out = self.l2.predict(store_id, sku, eval_date, hist_before)
            if not l2_out.get("degraded"):
                result = l2_out

            l3_out = self.l3.predict(store_id, sku, eval_date, {}, hist_before)
            if not l3_out.get("degraded"):
                result = l3_out

            predicted = result["predicted_qty"]

            actuals.append(actual)
            predictions.append(predicted)
            daily_details.append({
                "date": eval_date.isoformat(),
                "actual": actual,
                "predicted": round(predicted, 2),
                "model_version": result.get("model_version", "L1-rule"),
            })

        if not actuals:
            return {
                "MAPE": None,
                "RMSE": None,
                "bias_rate": None,
                "n_days": 0,
                "model_version": "N/A",
                "daily_details": [],
            }

        n = len(actuals)

        # MAPE
        ape_sum = sum(abs((a - p) / a) for a, p in zip(actuals, predictions))
        mape = round(ape_sum / n * 100, 2)

        # RMSE
        se_sum = sum((a - p) ** 2 for a, p in zip(actuals, predictions))
        rmse = round(math.sqrt(se_sum / n), 2)

        # 偏差率 (bias rate): 正值 = 高估, 负值 = 低估
        bias_sum = sum((p - a) / a for a, p in zip(actuals, predictions))
        bias_rate = round(bias_sum / n * 100, 2)

        return {
            "MAPE": mape,
            "RMSE": rmse,
            "bias_rate": bias_rate,
            "n_days": n,
            "model_version": (
                daily_details[-1]["model_version"] if daily_details else "N/A"
            ),
            "daily_details": daily_details,
        }

    # ── 内部方法 ───────────────────────────────────────────

    def _load_history(
        self,
        store_id: str,
        sku: str,
        start_date: date,
        end_date: date,
    ) -> List[SalesRecord]:
        """通过注入的 data_loader 回调加载历史数据。"""
        if self.data_loader is None:
            raise ValueError(
                "SalesPredictor 未注入 data_loader 回调; "
                "请在构造时提供 data_loader 参数, 或调用 set_data_loader()。"
            )
        return self.data_loader(store_id, sku, start_date, end_date)

    def _load_history_dict(
        self,
        store_id: str,
        sku: str,
        target_date: date,
    ) -> Dict[date, float]:
        """加载预测所需的回溯历史, 返回 {date: qty_sold}。"""
        start = target_date - timedelta(days=self.HISTORY_LOOKBACK_DAYS)
        records = self._load_history(store_id, sku, start, target_date)
        return {r.business_date: r.qty_sold for r in records}

    @staticmethod
    def _compute_bounds(
        predicted_qty: float,
        confidence: float,
    ) -> tuple:
        """
        根据置信度计算预测区间。

        置信度越高区间越窄; 置信度 0.9 时区间约为 ±20%,
        置信度 0.5 时区间约为 ±60%。
        """
        if predicted_qty <= 0:
            return (0.0, 0.0)
        margin = (1.0 - confidence) * 0.8  # 0.0 ~ 0.8
        lower = round(predicted_qty * (1.0 - margin), 2)
        upper = round(predicted_qty * (1.0 + margin), 2)
        return (max(0.0, lower), upper)

    def set_data_loader(self, loader: DataLoader) -> None:
        """运行时注入数据加载回调。"""
        self.data_loader = loader

    def set_sku_lister(self, lister: SkuLister) -> None:
        """运行时注入 SKU 列表回调。"""
        self.sku_lister = lister
