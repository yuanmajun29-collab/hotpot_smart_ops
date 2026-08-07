"""
数据引擎 · 6 张新增数据库表 DDL（SQLite + PostgreSQL 双轨）

导入方式:
    from hotpot_platform.cloud.event_hub.data_engine_schema import (
        SQLITE_DATA_ENGINE_SCHEMA,
        POSTGRES_DATA_ENGINE_SCHEMA,
        get_data_engine_schema,
    )

在 hub_core.db._init_schema() 中根据 ENGINE 追加对应 schema 即可。
"""

import os as _os


SQLITE_DATA_ENGINE_SCHEMA = """

-- 表1: sales_daily — per-SKU 日销量时序
CREATE TABLE IF NOT EXISTS sales_daily (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id   TEXT    NOT NULL DEFAULT '',
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
    tenant_id       TEXT    NOT NULL DEFAULT '',
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
    tenant_id   TEXT    NOT NULL DEFAULT '',
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
    tenant_id   TEXT    NOT NULL DEFAULT '',
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
    tenant_id       TEXT    NOT NULL DEFAULT '',
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
    tenant_id       TEXT    NOT NULL DEFAULT '',
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

POSTGRES_DATA_ENGINE_SCHEMA = """

-- 表1: sales_daily — per-SKU 日销量时序
CREATE TABLE IF NOT EXISTS sales_daily (
    id          SERIAL PRIMARY KEY,
    tenant_id   VARCHAR(64)  NOT NULL DEFAULT '',
    store_id    TEXT    NOT NULL,
    business_date DATE NOT NULL,
    sku         TEXT    NOT NULL,
    sku_name    TEXT,
    category    TEXT,
    qty_sold    DOUBLE PRECISION NOT NULL DEFAULT 0,
    unit        TEXT    DEFAULT '份',
    unit_price  DOUBLE PRECISION,
    revenue     DOUBLE PRECISION,
    hour_dist   TEXT,
    source      TEXT    DEFAULT 'pos',
    synced_at   TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_sales_daily UNIQUE(store_id, business_date, sku)
);
CREATE INDEX IF NOT EXISTS idx_sales_store_date ON sales_daily(store_id, business_date);
CREATE INDEX IF NOT EXISTS idx_sales_sku ON sales_daily(sku);

-- 表2: inventory_ledger — 库存台账 (流水)
CREATE TABLE IF NOT EXISTS inventory_ledger (
    id              SERIAL PRIMARY KEY,
    tenant_id       VARCHAR(64)  NOT NULL DEFAULT '',
    store_id        TEXT    NOT NULL,
    sku             TEXT    NOT NULL,
    batch_id        TEXT,
    movement_type   TEXT    NOT NULL,
    qty_change      DOUBLE PRECISION NOT NULL,
    qty_after       DOUBLE PRECISION,
    unit            TEXT    DEFAULT 'kg',
    unit_cost       DOUBLE PRECISION,
    reason          TEXT,
    ref_type        TEXT,
    ref_id          TEXT,
    operator        TEXT,
    recorded_at     TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_inventory_ledger UNIQUE(store_id, sku, batch_id, movement_type, recorded_at)
);
CREATE INDEX IF NOT EXISTS idx_inv_store_sku ON inventory_ledger(store_id, sku);

-- 表3: inventory_snapshot — 库存快照
CREATE TABLE IF NOT EXISTS inventory_snapshot (
    tenant_id   VARCHAR(64)  NOT NULL DEFAULT '',
    store_id    TEXT    NOT NULL,
    sku         TEXT    NOT NULL,
    on_hand_qty DOUBLE PRECISION NOT NULL DEFAULT 0,
    in_transit_qty DOUBLE PRECISION DEFAULT 0,
    unit        TEXT    DEFAULT 'kg',
    avg_daily_consumption DOUBLE PRECISION,
    shelf_life_days  INTEGER,
    earliest_expiry  TIMESTAMP WITH TIME ZONE,
    last_received_at TIMESTAMP WITH TIME ZONE,
    last_consumed_at TIMESTAMP WITH TIME ZONE,
    updated_at  TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    PRIMARY KEY (store_id, sku)
);

-- 表4: sales_forecast — 预测结果
CREATE TABLE IF NOT EXISTS sales_forecast (
    id          SERIAL PRIMARY KEY,
    tenant_id   VARCHAR(64)  NOT NULL DEFAULT '',
    store_id    TEXT    NOT NULL,
    sku         TEXT    NOT NULL,
    forecast_date DATE NOT NULL,
    predicted_qty  DOUBLE PRECISION NOT NULL,
    confidence     DOUBLE PRECISION,
    lower_bound    DOUBLE PRECISION,
    upper_bound    DOUBLE PRECISION,
    model_version  TEXT,
    features_used  TEXT,
    generated_at   TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_sales_forecast UNIQUE(store_id, sku, forecast_date, model_version)
);
CREATE INDEX IF NOT EXISTS idx_forecast_store_date ON sales_forecast(store_id, forecast_date);

-- 表5: order_suggestion — 订货建议
CREATE TABLE IF NOT EXISTS order_suggestion (
    id              SERIAL PRIMARY KEY,
    tenant_id       VARCHAR(64)  NOT NULL DEFAULT '',
    store_id        TEXT    NOT NULL,
    sku             TEXT    NOT NULL,
    suggested_qty   DOUBLE PRECISION NOT NULL,
    unit            TEXT    DEFAULT 'kg',
    current_stock   DOUBLE PRECISION,
    safety_stock    DOUBLE PRECISION,
    forecast_demand DOUBLE PRECISION,
    lead_time_days  INTEGER,
    supplier        TEXT,
    urgency         TEXT    DEFAULT 'normal',
    reason          TEXT,
    status          TEXT    DEFAULT 'pending',
    approved_by     TEXT,
    approved_at     TIMESTAMP WITH TIME ZONE,
    generated_at    TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_order_suggestion UNIQUE(store_id, sku, generated_at)
);

-- 表6: supplier_scorecard — 供应商评分卡
CREATE TABLE IF NOT EXISTS supplier_scorecard (
    id              SERIAL PRIMARY KEY,
    tenant_id       VARCHAR(64)  NOT NULL DEFAULT '',
    store_id        TEXT,
    supplier_name   TEXT    NOT NULL,
    sku             TEXT,
    total_batches   INTEGER DEFAULT 0,
    avg_variance_pct DOUBLE PRECISION,
    avg_yield_rate   DOUBLE PRECISION,
    quality_grade_dist TEXT,
    avg_price         DOUBLE PRECISION,
    price_stability   DOUBLE PRECISION,
    on_time_rate      DOUBLE PRECISION,
    reject_rate       DOUBLE PRECISION,
    total_score       DOUBLE PRECISION,
    score_level       TEXT,
    last_evaluated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_supplier_scorecard UNIQUE(store_id, supplier_name, sku)
);
"""


def get_data_engine_schema() -> str:
    """根据环境变量 HOTPOT_DB_ENGINE 返回对应 DDL（默认 SQLite）。"""
    engine = _os.environ.get("HOTPOT_DB_ENGINE", "sqlite").lower()
    if engine in ("postgres", "postgresql", "pg"):
        return POSTGRES_DATA_ENGINE_SCHEMA
    return SQLITE_DATA_ENGINE_SCHEMA
