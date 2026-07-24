"""
火瞳 · 数据引擎 — 统一入口 (hotpot_platform.cloud.data_engine)

子模块:
  models            — Pydantic 数据模型 (N01-N06)
  algorithms.baseline — 四级预测算法 (L1-L4)
  loss_analyzer     — N04: 损耗分析 (LossAnalyzer)
  erp_connector     — N06: ERP 双向连接器 (ErpConnector + 6 适配器)
"""

# ---- 数据模型 (N01-N06) ----
from hotpot_platform.cloud.data_engine.models import (  # noqa: F401
    ErpSyncResult, InventoryMovement, InventorySnapshot,
    LossAnalysis, LossTrend, OrderSuggestion, SalesForecast,
    SalesRecord, SupplierScorecard,
)

# ---- 预测算法 ----
from hotpot_platform.cloud.data_engine.algorithms.baseline import (  # noqa: F401
    LLMEnhancer, MLModel, RuleBaseline, StatisticalModel,
)

# ---- N04 损耗分析 ----
from hotpot_platform.cloud.data_engine.loss_analyzer import LossAnalyzer  # noqa: F401

# ---- N06 ERP 连接器 (含全部 6 个适配器) ----
from hotpot_platform.cloud.data_engine.erp_connector import (  # noqa: F401
    ADAPTER_REGISTRY,
    ErpAdapter,
    ErpConnector,
    FileAdapter,
    HualalaAdapter,
    KingdeeAdapter,
    MockAdapter,
    RestApiAdapter,
    TflongAdapter,
)

# ---- 同级模块 (Try-import, 其他子代理可能并行开发) ----
try:
    from hotpot_platform.cloud.data_engine.sales_predictor import SalesPredictor  # noqa: F401
except ImportError:
    SalesPredictor = None  # type: ignore[assignment]

try:
    from hotpot_platform.cloud.data_engine.order_advisor import OrderAdvisor  # noqa: F401
except ImportError:
    OrderAdvisor = None  # type: ignore[assignment]

try:
    from hotpot_platform.cloud.data_engine.inventory_book import InventoryBook  # noqa: F401
except ImportError:
    InventoryBook = None  # type: ignore[assignment]

try:
    from hotpot_platform.cloud.data_engine.supplier_scorer import SupplierScorer  # noqa: F401
except ImportError:
    SupplierScorer = None  # type: ignore[assignment]

try:
    from hotpot_platform.cloud.data_engine.feature_store import FeatureStore  # noqa: F401
except ImportError:
    FeatureStore = None  # type: ignore[assignment]


__all__ = [
    # N01 销量预测
    "SalesRecord", "SalesForecast",
    # N02 订货建议
    "OrderSuggestion",
    # N03 库存
    "InventoryMovement", "InventorySnapshot",
    # N04 损耗分析
    "LossAnalysis", "LossTrend", "LossAnalyzer",
    # N05 供应商评分
    "SupplierScorecard",
    # N06 ERP 连接器
    "ErpSyncResult", "ErpConnector", "ErpAdapter",
    # 适配器 (全部 6 种)
    "FileAdapter", "MockAdapter", "RestApiAdapter",
    "HualalaAdapter", "TflongAdapter", "KingdeeAdapter",
    # 预测算法
    "RuleBaseline", "StatisticalModel", "MLModel", "LLMEnhancer",
    # 适配器注册表
    "ADAPTER_REGISTRY",
]
