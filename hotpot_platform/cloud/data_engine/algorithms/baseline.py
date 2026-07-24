"""
数据引擎 — 四级预测算法

L1 规则基线 (移动平均/同周环比) → L2 SARIMA → L3 LightGBM → L4 LLM增强
逐层尝试, 任一层失败优雅降级到下一层。L1 永远可用 (零依赖)。
"""

from typing import Dict, Optional, List
from datetime import date, timedelta
from collections import defaultdict


# ============================================================
# L1: 规则基线 — 零依赖, 永远可用
# ============================================================

class RuleBaseline:
    """移动平均 + 同周环比 + 简单规则"""

    def predict(
        self,
        store_id: str,
        sku: str,
        target_date: date,
        history: Dict[date, float],  # {date: qty_sold}
        horizon_days: int = 1,
    ) -> Dict:
        """
        规则基线预测。
        逻辑: 优先用 7日移动平均 → 数据不足时用最近N天平均 → 无数据返回 0。
        """
        if not history:
            return {
                "predicted_qty": 0.0,
                "confidence": 0.0,
                "model_version": "L1-rule",
                "method": "no_data",
            }

        # 取最近 7/14/28 天的移动平均
        ma_7 = self._moving_avg(history, target_date, 7)
        ma_14 = self._moving_avg(history, target_date, 14)
        ma_28 = self._moving_avg(history, target_date, 28)

        # 同周环比
        same_day_last_week = history.get(target_date - timedelta(days=7))
        same_day_last_year = history.get(target_date.replace(year=target_date.year - 1)) if target_date.year > 2026 else None

        # 周末/节假日加权
        is_weekend = target_date.weekday() >= 5
        weekend_factor = 1.3 if is_weekend else 1.0

        # 选择最佳基准
        if ma_7 and ma_7 > 0:
            predicted = ma_7 * weekend_factor
            method = "ma_7"
        elif ma_14 and ma_14 > 0:
            predicted = ma_14 * weekend_factor
            method = "ma_14"
        elif ma_28 and ma_28 > 0:
            predicted = ma_28 * weekend_factor
            method = "ma_28"
        else:
            # 无足够历史, 用最近可用数据的均值
            recent = sorted(history.items(), key=lambda x: x[0], reverse=True)[:7]
            if recent:
                predicted = sum(v for _, v in recent) / len(recent) * weekend_factor
                method = "recent_avg"
            else:
                predicted = 0.0
                method = "zero"

        # 置信度: 数据越充分越有信心
        n_days = len(history)
        if n_days >= 60:
            confidence = 0.7
        elif n_days >= 30:
            confidence = 0.5
        elif n_days >= 14:
            confidence = 0.35
        else:
            confidence = 0.2

        return {
            "predicted_qty": round(predicted, 2),
            "confidence": confidence,
            "model_version": "L1-rule",
            "method": method,
            "ma_7": ma_7,
            "ma_14": ma_14,
            "same_day_last_week": same_day_last_week,
        }

    def _moving_avg(self, history: Dict[date, float], target_date: date, days: int) -> Optional[float]:
        """计算最近 N 天的移动平均"""
        values = []
        for d in range(1, days + 1):
            day = target_date - timedelta(days=d)
            v = history.get(day)
            if v is not None:
                values.append(v)
        return sum(values) / len(values) if values else None


# ============================================================
# L2: 统计模型 (SARIMA)
# ============================================================

class StatisticalModel:
    """SARIMA + Holt-Winters 指数平滑"""

    def __init__(self):
        self._sarima_available = False
        try:
            import statsmodels.api as sm
            self._sm = sm
            self._sarima_available = True
        except ImportError:
            pass

    def predict(
        self,
        store_id: str,
        sku: str,
        target_date: date,
        history: Dict[date, float],
        horizon_days: int = 1,
    ) -> Dict:
        """SARIMA 预测。statsmodels 不可用时返回降级信号。"""
        if not self._sarima_available or len(history) < 14:
            return {"degraded": True, "reason": "statsmodels 不可用或数据不足 14 天"}

        try:
            dates = sorted(history.keys())
            values = [history[d] for d in dates]

            # SARIMA(1,1,1)(1,1,1,7) — 火锅有明显周季节性
            model = self._sm.tsa.statespace.SARIMAX(
                values,
                order=(1, 1, 1),
                seasonal_order=(1, 1, 1, 7),
                enforce_stationarity=False,
                enforce_invertibility=False,
            )
            result = model.fit(disp=False)
            forecast = result.forecast(steps=horizon_days)

            predicted = float(forecast[0]) if horizon_days == 1 else float(forecast[-1])
            predicted = max(0, predicted)  # 不能为负

            return {
                "predicted_qty": round(predicted, 2),
                "confidence": 0.8,
                "model_version": "L2-stat",
                "method": "SARIMA(1,1,1)(1,1,1,7)",
                "aic": float(result.aic) if hasattr(result, 'aic') else None,
            }
        except Exception:
            return {"degraded": True, "reason": "SARIMA 拟合失败"}


# ============================================================
# L3: 机器学习 (LightGBM)
# ============================================================

class MLModel:
    """LightGBM 回归 — 多因子特征"""

    def __init__(self):
        self._lgb_available = False
        try:
            import lightgbm as lgb
            self._lgb = lgb
            self._lgb_available = True
        except ImportError:
            pass

    def predict(
        self,
        store_id: str,
        sku: str,
        target_date: date,
        features: Dict,  # 来自 FeatureStore.build_features()
        history: Dict[date, float],
    ) -> Dict:
        """LightGBM 预测。不可用或数据不足 60 天时降级。"""
        if not self._lgb_available or len(history) < 60:
            return {"degraded": True, "reason": "lightgbm 不可用或数据不足 60 天"}

        try:
            # 构建训练集: 从历史中生成 (X, y)
            dates = sorted(history.keys())
            X, y = [], []
            min_train_date = dates[14]  # 至少留 14 天做特征

            for i, d in enumerate(dates):
                if d < min_train_date:
                    continue
                # 用 d 之前的 14 天历史做特征
                past_history = {pd: history[pd] for pd in dates[:i] if pd < d}
                if len(past_history) < 7:
                    continue
                feat = self._build_features_vec(d, past_history)
                if feat:
                    X.append(feat)
                    y.append(history[d])

            if len(X) < 30:
                return {"degraded": True, "reason": f"训练样本不足: {len(X)}"}

            model = self._lgb.LGBMRegressor(
                n_estimators=100,
                max_depth=5,
                learning_rate=0.05,
                verbose=-1,
            )
            model.fit(X, y)

            # 预测
            pred_features = self._build_features_vec(target_date, history)
            if not pred_features:
                return {"degraded": True, "reason": "无法构建预测特征"}

            predicted = float(model.predict([pred_features])[0])
            predicted = max(0, predicted)

            return {
                "predicted_qty": round(predicted, 2),
                "confidence": 0.85,
                "model_version": "L3-ml",
                "method": "LightGBM",
                "n_train_samples": len(X),
            }
        except Exception:
            return {"degraded": True, "reason": "LightGBM 训练/预测失败"}

    def _build_features_vec(self, target_date: date, history: Dict[date, float]) -> Optional[List[float]]:
        """构建特征向量"""
        vec = [
            target_date.weekday(),
            1.0 if target_date.weekday() >= 5 else 0.0,
            target_date.day,
            target_date.month,
        ]
        for lag in [1, 2, 3, 7, 14]:
            day = target_date - timedelta(days=lag)
            vec.append(history.get(day, 0.0))
        for w in [1, 2, 4]:
            vals = [history.get(target_date - timedelta(days=d), 0) for d in range(1, 7 * w + 1)]
            vals = [v for v in vals if v > 0]
            vec.append(sum(vals) / len(vals) if vals else 0.0)
        return vec


# ============================================================
# L4: LLM 增强
# ============================================================

class LLMEnhancer:
    """复用现有 forecast_agent 的 LLM 推理"""

    def __init__(self):
        try:
            import sys, os
            sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..'))
            from hotpot_platform.cloud.llm_report.forecast_agent import LLMForecastAgent
            self._agent = LLMForecastAgent()
            self._available = True
        except (ImportError, Exception):
            self._agent = None
            self._available = False

    def enhance(self, base_prediction: Dict, context: str = "") -> Dict:
        """LLM 增强预测结果, 添加自然语言解释。不可用时回退。"""
        if not self._available:
            return {**base_prediction, "llm_enhanced": False}

        try:
            # 调用 LLM 增强
            result = self._agent.forecast(
                sku=base_prediction.get("sku", "unknown"),
                historical_data=str(base_prediction.get("historical_preview", "")),
                special_events=context,
            )
            return {
                **base_prediction,
                "llm_enhanced": True,
                "llm_explanation": result.get("explanation", ""),
                "model_version": "L4-llm",
                "confidence": min(0.95, base_prediction.get("confidence", 0.7) + 0.1),
            }
        except Exception:
            return {**base_prediction, "llm_enhanced": False}
