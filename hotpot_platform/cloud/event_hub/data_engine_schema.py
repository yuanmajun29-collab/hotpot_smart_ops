"""
数据引擎 · 6 张新增数据库表 (SQLite DDL)

导入方式:
    from hotpot_platform.cloud.event_hub.data_engine_schema import SQLITE_DATA_ENGINE_SCHEMA

在 hub_core.db._init_schema() 中追加即可。
"""

SQLITE_DATA_ENGINE_SCHEMA = """

-- 表1: sales_daily — per-SKU 日销量时序
CREATE TABLE IF NOT EXISTS sales_daily (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    store_id    TEXT    NOT NULL,
    business_date TEXT NOT NULL,
    sku         TEXT    NOT NULL,
    sku_name    TEXT,
    category    TEXT,
    qty_sold    REAL    NOT NULL DEFAULT 0,
    unit        TEXT    DEFAULT '份',
    unit_price  REAL,
    revenue     REAL,
    hour_dist   TEXT,
    source      TEXT    DEFAULT 'pos',
    synced_at   TEXT    NOT NULL,
    UNIQUE(store_id, business_date, sku)
);
CREATE INDEX IF NOT EXISTS idx_sales_store_date ON sales_daily(store_id, business_date);
CREATE INDEX IF NOT EXISTS idx_sales_sku ON sales_daily(sku);

-- 表2: inventory_ledger — 库存台账 (流水)
CREATE TABLE IF NOT EXISTS inventory_ledger (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    store_id        TEXT    NOT NULL,
    sku             TEXT    NOT NULL,
    batch_id        TEXT,
    movement_type   TEXT    NOT NULL,
    qty_change      REAL    NOT NULL,
    qty_after       REAL,
    unit            TEXT    DEFAULT 'kg',
    unit_cost       REAL,
    reason          TEXT,
    ref_type        TEXT,
    ref_id          TEXT,
    operator        TEXT,
    recorded_at     TEXT    NOT NULL,
    UNIQUE(store_id, sku, batch_id, movement_type, recorded_at)
);
CREATE INDEX IF NOT EXISTS idx_inv_store_sku ON inventory_ledger(store_id, sku);

-- 表3: inventory_snapshot — 库存快照
CREATE TABLE IF NOT EXISTS inventory_snapshot (
    store_id    TEXT    NOT NULL,
    sku         TEXT    NOT NULL,
    on_hand_qty REAL    NOT NULL DEFAULT 0,
    in_transit_qty REAL DEFAULT 0,
    unit        TEXT    DEFAULT 'kg',
    avg_daily_consumption REAL,
    shelf_life_days  INTEGER,
    earliest_expiry  TEXT,
    last_received_at TEXT,
    last_consumed_at TEXT,
    updated_at  TEXT    NOT NULL,
    PRIMARY KEY (store_id, sku)
);

-- 表4: sales_forecast — 预测结果
CREATE TABLE IF NOT EXISTS sales_forecast (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    store_id    TEXT    NOT NULL,
    sku         TEXT    NOT NULL,
    forecast_date TEXT NOT NULL,
    predicted_qty  REAL   NOT NULL,
    confidence     REAL,
    lower_bound    REAL,
    upper_bound    REAL,
    model_version  TEXT,
    features_used  TEXT,
    generated_at   TEXT    NOT NULL,
    UNIQUE(store_id, sku, forecast_date, model_version)
);
CREATE INDEX IF NOT EXISTS idx_forecast_store_date ON sales_forecast(store_id, forecast_date);

-- 表5: order_suggestion — 订货建议
CREATE TABLE IF NOT EXISTS order_suggestion (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    store_id        TEXT    NOT NULL,
    sku             TEXT    NOT NULL,
    suggested_qty   REAL    NOT NULL,
    unit            TEXT    DEFAULT 'kg',
    current_stock   REAL,
    safety_stock    REAL,
    forecast_demand REAL,
    lead_time_days  INTEGER,
    supplier        TEXT,
    urgency         TEXT    DEFAULT 'normal',
    reason          TEXT,
    status          TEXT    DEFAULT 'pending',
    approved_by     TEXT,
    approved_at     TEXT,
    generated_at    TEXT    NOT NULL,
    UNIQUE(store_id, sku, generated_at)
);

-- 表6: supplier_scorecard — 供应商评分卡
CREATE TABLE IF NOT EXISTS supplier_scorecard (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    store_id        TEXT,
    supplier_name   TEXT    NOT NULL,
    sku             TEXT,
    total_batches   INTEGER DEFAULT 0,
    avg_variance_pct REAL,
    avg_yield_rate   REAL,
    quality_grade_dist TEXT,
    avg_price         REAL,
    price_stability   REAL,
    on_time_rate      REAL,
    reject_rate       REAL,
    total_score       REAL,
    score_level       TEXT,
    last_evaluated_at TEXT    NOT NULL,
    UNIQUE(store_id, supplier_name, sku)
);
"""
