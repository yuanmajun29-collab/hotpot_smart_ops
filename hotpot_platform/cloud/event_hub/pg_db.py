"""PostgreSQL persistence for Event Hub (DEV-101 P0).

Connection-pooled, drop-in replacement for db.HubDatabase.
Activate via: export HOTPOT_DATABASE_URL=postgresql://user:pass@host/db
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone, date as date_type
from typing import Any, Dict, List, Optional, Union
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

from hotpot_platform.cloud.event_hub.daily_report_store import PG_DAILY_REPORTS_SCHEMA
from hotpot_platform.cloud.event_hub.iot_readings_store import PG_IOT_READINGS_SCHEMA
from hotpot_platform.cloud.event_hub.receiving_store import PG_RECEIVING_SCHEMA
from hotpot_platform.cloud.event_hub.sop_assign_store import PG_SOP_ASSIGN_SCHEMA
from hotpot_platform.cloud.event_hub.task_store import PG_TASKS_SCHEMA
from hotpot_platform.cloud.event_hub.domain.waste_timeseries import (
    check_alert,
    compute_trend_comparison,
    format_alert_message,
)

# ── ADR-003: 供应链产品主数据表 (S01) ──
PG_SUPPLY_PRODUCT_MASTER_SCHEMA = """
CREATE TABLE IF NOT EXISTS supply_product_master (
    sku_code TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    specification TEXT NOT NULL,
    brand TEXT NOT NULL,
    unit_price REAL NOT NULL DEFAULT 0,
    unit TEXT DEFAULT '份',
    category TEXT NOT NULL,
    supplier_id TEXT,
    supplier_name TEXT,
    image_url TEXT,
    location_code TEXT,
    location_name TEXT,
    storage_area TEXT,
    shelf_life_days INTEGER,
    min_stock_qty REAL,
    tags TEXT[] DEFAULT '{}',
    status TEXT DEFAULT 'draft',
    locked BOOLEAN DEFAULT FALSE,
    version INTEGER DEFAULT 1,
    tenant_id       VARCHAR(64)  NOT NULL DEFAULT '',
    brand_id        VARCHAR(64)  NOT NULL DEFAULT '',
    region_id       VARCHAR(64)  NOT NULL DEFAULT '',
    store_id TEXT NOT NULL DEFAULT '',
    created_by TEXT,
    created_at TIMESTAMPTZ,
    updated_by TEXT,
    updated_at TIMESTAMPTZ,
    payload JSONB NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_spm_store ON supply_product_master(store_id);
CREATE INDEX IF NOT EXISTS idx_spm_category ON supply_product_master(category);
CREATE INDEX IF NOT EXISTS idx_spm_status ON supply_product_master(status);
"""

# S03 — 采购订单 (Purchase Order) Hub PG 主写表
PG_SUPPLY_PURCHASE_ORDER_SCHEMA = """
CREATE TABLE IF NOT EXISTS supply_purchase_order (
    po_number       VARCHAR(32)  PRIMARY KEY,
    tenant_id       VARCHAR(64)  NOT NULL DEFAULT '',
    brand_id        VARCHAR(64)  NOT NULL DEFAULT '',
    region_id       VARCHAR(64)  NOT NULL DEFAULT '',
    store_id        VARCHAR(64)  NOT NULL,
    ordered_by      VARCHAR(64),
    ordered_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
    items           JSONB        NOT NULL DEFAULT '[]'::jsonb,
    total_amount    NUMERIC(12,2) NOT NULL DEFAULT 0,
    status          VARCHAR(20)  NOT NULL DEFAULT 'draft',
                    CHECK (status IN ('draft','submitted','confirmed','partial','received','cancelled')),
    supplier        VARCHAR(128),
    delivery_address TEXT,
    notes           TEXT,
    forecast_ref    VARCHAR(64),
    auto_generated  BOOLEAN      NOT NULL DEFAULT FALSE,
    -- 审计字段
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
    payload         JSONB        NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX IF NOT EXISTS idx_spo_store_id ON supply_purchase_order(store_id);
CREATE INDEX IF NOT EXISTS idx_spo_status ON supply_purchase_order(status);
CREATE INDEX IF NOT EXISTS idx_spo_ordered_at ON supply_purchase_order(ordered_at DESC);
"""

# ── G4: KPI指标快照表 (KPI Metrics Snapshot) ──
# 用于持久化任务完成时自动回写的KPI指标，完成"感知→决策→执行→验证→回写"闭环
PG_KPI_METRICS_SCHEMA = """
CREATE TABLE IF NOT EXISTS kpi_metrics (
    id              SERIAL PRIMARY KEY,
    tenant_id       VARCHAR(64)  NOT NULL DEFAULT '',
    brand_id        VARCHAR(64)  NOT NULL DEFAULT '',
    region_id       VARCHAR(64)  NOT NULL DEFAULT '',
    store_id        TEXT NOT NULL,
    metric_id       TEXT NOT NULL,               -- 指标ID (如 cleaning_response_time, waste_rate)
    metric_name     TEXT NOT NULL,               -- 中文名称 (如 "清台响应时间", "损耗率")
    value           REAL NOT NULL DEFAULT 0,     -- 指标值
    unit            TEXT NOT NULL DEFAULT '',    -- 单位 (如 "seconds", "%", "¥", "次")
    target          REAL,                        -- 目标值 (用于判定状态)
    status          TEXT NOT NULL DEFAULT 'normal',  -- normal/good/warning/critical
    trend           TEXT NOT NULL DEFAULT 'unknown',  -- up/down/stable/unknown
    change_pct      REAL NOT NULL DEFAULT 0,     -- 变化百分比
    period_start    TIMESTAMPTZ NOT NULL,        -- 统计周期开始
    period_end      TIMESTAMPTZ NOT NULL,        -- 统计周期结束
    source_task_id  TEXT,                        -- 触发此KPI的任务ID (可追溯)
    source_event_id TEXT,                        -- 触发事件ID
    category        TEXT NOT NULL DEFAULT 'operation',  -- revenue/cost/operation/quality/inventory/staffing
    dimensions      JSONB NOT NULL DEFAULT '{}'::jsonb,  -- 维度标签 (如 {"table_id":"T02"})
    provenance      JSONB NOT NULL DEFAULT '{}'::jsonb,  -- 数据溯源信息
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_kpi_store_metric ON kpi_metrics(store_id, metric_id);
CREATE INDEX IF NOT EXISTS idx_kpi_period ON kpi_metrics(period_start DESC, period_end DESC);
CREATE INDEX IF NOT EXISTS idx_kpi_category ON kpi_metrics(category);
CREATE INDEX IF NOT EXISTS idx_kpi_task ON kpi_metrics(source_task_id);
"""

# ── P0-D: 销售事件表 (Sales Events) — 第四闭环: 销售增长与服务培训 ──
# 来源: POS Bridge (pos_bridge.py) → 边缘采集 → Hub PG 主写
PG_SALES_EVENTS_SCHEMA = """
CREATE TABLE IF NOT EXISTS sales_events (
    id              BIGSERIAL PRIMARY KEY,
    event_id        VARCHAR(64)  NOT NULL UNIQUE,         -- 全局唯一事件ID (幂等键)
    tenant_id       VARCHAR(64)  NOT NULL DEFAULT '',
    brand_id        VARCHAR(64)  NOT NULL DEFAULT '',
    region_id       VARCHAR(64)  NOT NULL DEFAULT '',
    store_id        VARCHAR(64)  NOT NULL,
    -- 交易核心字段
    transaction_id  VARCHAR(64)  NOT NULL,                -- POS原始交易单号
    table_id        VARCHAR(16),                          -- 桌号 (堂食)
    order_type      VARCHAR(20)  NOT NULL DEFAULT 'dine_in',
                    CHECK (order_type IN ('dine_in','takeout','delivery','wechat')),
    shift           VARCHAR(10)  NOT NULL,                -- lunch / dinner / late_night
    -- 金额字段
    subtotal        NUMERIC(12,2) NOT NULL DEFAULT 0,     -- 小计
    discount_amount NUMERIC(12,2) NOT NULL DEFAULT 0,     -- 折扣金额 (⚠️ 仅记录，Agent禁止自动发起)
    service_fee     NUMERIC(12,2) NOT NULL DEFAULT 0,     -- 服务费
    total_amount    NUMERIC(12,2) NOT NULL,               -- 实收总额
    payment_method  VARCHAR(20),                          -- cash/wechat/alipay/card
    -- 客单价衍生字段
    guest_count     INTEGER      NOT NULL DEFAULT 1,      -- 用餐人数
    avg_check       NUMERIC(10,2) NOT NULL DEFAULT 0,     -- 客单价 = total / guests
    -- 时间戳
    occurred_at     TIMESTAMPTZ  NOT NULL,                -- 交易发生时间 (POS时间)
    received_at     TIMESTAMPTZ  NOT NULL DEFAULT now(),   -- 平台接收时间
    -- 数据溯源
    pos_source      VARCHAR(64)  NOT NULL DEFAULT 'pos_bridge_file',  -- 数据来源
    source_batch_id VARCHAR(64),                          -- 批次ID (用于批量导入去重)
    -- 状态与审计
    status          VARCHAR(16)  NOT NULL DEFAULT 'confirmed',
                    CHECK (status IN ('pending','confirmed','reversed','voided')),
    payload         JSONB        NOT NULL DEFAULT '{}'::jsonb,  -- 原始POS数据完整副本
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ  NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_sales_store ON sales_events(store_id);
CREATE INDEX IF NOT EXISTS idx_sales_transaction ON sales_events(transaction_id);
CREATE INDEX IF NOT EXISTS idx_sales_occurred ON sales_events(occurred_at DESC);
CREATE INDEX IF NOT EXISTS idx_sales_shift ON sales_events(store_id, shift, occurred_at);
CREATE INDEX IF NOT EXISTS idx_sales_table ON sales_events(table_id) WHERE table_id IS NOT NULL;
"""

# ── P0-D: 销售明细表 (Transaction Details) ──
PG_SALES_TRANSACTION_DETAIL_SCHEMA = """
CREATE TABLE IF NOT EXISTS sales_transaction_detail (
    id              BIGSERIAL PRIMARY KEY,
    detail_id       VARCHAR(64)  NOT NULL UNIQUE,
    sales_event_id  VARCHAR(64)  NOT NULL REFERENCES sales_events(event_id) ON DELETE CASCADE,
    -- 菜品信息
    sku_code        VARCHAR(32)  NOT NULL,                -- SKU编码 (关联 supply_product_master)
    dish_name       TEXT         NOT NULL,                -- 菜品名称
    category        VARCHAR(32),                          -- 分类 (荤菜/素菜/海鲜/甜品/饮品)
    unit_price      NUMERIC(10,2) NOT NULL DEFAULT 0,     -- 单价
    quantity        REAL         NOT NULL DEFAULT 1,       -- 数量
    subtotal        NUMERIC(12,2) NOT NULL DEFAULT 0,     -- 小计
    -- 标记字段
    is_recommended  BOOLEAN      NOT NULL DEFAULT FALSE,  -- 是否为员工推荐菜品
    is_promo        BOOLEAN      NOT NULL DEFAULT FALSE,  -- 是否参与促销
    promo_type      VARCHAR(20),                          -- 促销类型 (如有)
    -- 审计
    payload         JSONB        NOT NULL DEFAULT '{}'::jsonb,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_detail_event ON sales_transaction_detail(sales_event_id);
CREATE INDEX IF NOT EXISTS idx_detail_sku ON sales_transaction_detail(sku_code);
CREATE INDEX IF NOT EXISTS idx_detail_category ON sales_transaction_detail(category);
"""

MAX_EVENTS_PER_STORE = 500
POOL_MIN_CONN = 2
POOL_MAX_CONN = 10


class PostgresHubDatabase:
    """PostgreSQL backend with same interface as HubDatabase.

    Uses psycopg2 ThreadedConnectionPool instead of a global threading.Lock,
    so multiple tenants can read/write concurrently without lock contention.
    """

    def __init__(self, database_url: str) -> None:
        try:
            import psycopg2
            import psycopg2.extras
            from psycopg2 import pool as pg_pool
        except ImportError as exc:
            raise RuntimeError(
                "psycopg2-binary required for PostgreSQL: pip install psycopg2-binary"
            ) from exc

        self.database_url = database_url
        self._psycopg2 = psycopg2
        self._psycopg2_extras = psycopg2.extras

        # ── connection pool ──
        self._pool = pg_pool.ThreadedConnectionPool(
            minconn=POOL_MIN_CONN,
            maxconn=POOL_MAX_CONN,
            dsn=database_url,
        )

        self._init_schema()

    @property
    def db_path(self):
        """Sidecar sqlite path compatibility — for log messages."""
        parsed = urlparse(self.database_url)
        dbname = (parsed.path or "/hotpot").lstrip("/")
        return f"pg://{parsed.hostname}/{dbname}"

    # ── thread-local pool helpers ───────────────────────────────

    def _getconn(self):
        """Borrow a connection from the pool."""
        return self._pool.getconn()

    def _putconn(self, conn, *, close: bool = False):
        """Return (or close) a connection to the pool."""
        if close:
            self._pool.putconn(conn, close=True)
        else:
            self._pool.putconn(conn)

    # ── schema ──────────────────────────────────────────────────

    def _init_schema(self) -> None:
        conn = self._getconn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS events (
                        event_id TEXT PRIMARY KEY,
                        tenant_id TEXT NOT NULL DEFAULT '',
                        brand_id TEXT NOT NULL DEFAULT '',
                        region_id TEXT NOT NULL DEFAULT '',
                        store_id TEXT NOT NULL,
                        level TEXT,
                        source TEXT,
                        payload JSONB NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL
                    );
                    CREATE INDEX IF NOT EXISTS idx_events_store
                        ON events(store_id, created_at DESC);

                    CREATE TABLE IF NOT EXISTS store_snapshots (
                        tenant_id TEXT NOT NULL DEFAULT '',
                        brand_id TEXT NOT NULL DEFAULT '',
                        region_id TEXT NOT NULL DEFAULT '',
                        store_id TEXT NOT NULL,
                        kind TEXT NOT NULL,
                        payload JSONB NOT NULL,
                        updated_at TIMESTAMPTZ NOT NULL,
                        PRIMARY KEY (store_id, kind)
                    );

                    CREATE TABLE IF NOT EXISTS device_registry (
                        tenant_id TEXT NOT NULL DEFAULT '',
                        brand_id TEXT NOT NULL DEFAULT '',
                        region_id TEXT NOT NULL DEFAULT '',
                        device_id TEXT PRIMARY KEY,
                        payload JSONB NOT NULL,
                        updated_at TIMESTAMPTZ NOT NULL
                    );
                    """
                    + PG_RECEIVING_SCHEMA
                    + PG_SOP_ASSIGN_SCHEMA
                    + PG_TASKS_SCHEMA
                    + PG_IOT_READINGS_SCHEMA
                    + PG_DAILY_REPORTS_SCHEMA
                    + PG_SUPPLY_PRODUCT_MASTER_SCHEMA
                    + PG_SUPPLY_PURCHASE_ORDER_SCHEMA
                    + PG_KPI_METRICS_SCHEMA
                    + """
                    CREATE TABLE IF NOT EXISTS waste_timeseries (
                        id SERIAL PRIMARY KEY,
                        tenant_id TEXT NOT NULL DEFAULT '',
                        brand_id TEXT NOT NULL DEFAULT '',
                        region_id TEXT NOT NULL DEFAULT '',
                        store_id TEXT NOT NULL,
                        date TEXT NOT NULL,
                        total_count INTEGER NOT NULL DEFAULT 0,
                        event_count INTEGER NOT NULL DEFAULT 0,
                        top_skus TEXT NOT NULL DEFAULT '[]',
                        generated_at TIMESTAMPTZ NOT NULL,
                        UNIQUE(store_id, date)
                    );
                    CREATE INDEX IF NOT EXISTS idx_wts_store_date
                        ON waste_timeseries(store_id, date DESC);

                    CREATE TABLE IF NOT EXISTS waste_alerts (
                        id SERIAL PRIMARY KEY,
                        tenant_id TEXT NOT NULL DEFAULT '',
                        brand_id TEXT NOT NULL DEFAULT '',
                        region_id TEXT NOT NULL DEFAULT '',
                        store_id TEXT NOT NULL,
                        date TEXT NOT NULL,
                        alert_type TEXT NOT NULL DEFAULT 'spike',
                        current_count INTEGER NOT NULL,
                        baseline_avg REAL NOT NULL,
                        ratio REAL NOT NULL,
                        message TEXT NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL,
                        acknowledged INTEGER NOT NULL DEFAULT 0,
                        UNIQUE(store_id, date, alert_type)
                    );
                    """
                )
            conn.commit()
        finally:
            self._putconn(conn)

    # ── event persistence ───────────────────────────────────────

    def persist_event(self, store_id: str, event: Dict[str, Any]) -> None:
        conn = self._getconn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO events(event_id, store_id, level, source, payload, created_at)
                    VALUES (%s, %s, %s, %s, %s::jsonb, %s)
                    ON CONFLICT (event_id) DO UPDATE SET
                        payload = EXCLUDED.payload,
                        level = EXCLUDED.level,
                        source = EXCLUDED.source
                    """,
                    (
                        event["event_id"],
                        store_id,
                        event.get("level"),
                        event.get("source"),
                        json.dumps(event, ensure_ascii=False),
                        event.get("timestamp") or datetime.now(timezone.utc).isoformat(),
                    ),
                )
                cur.execute(
                    """
                    DELETE FROM events WHERE event_id IN (
                        SELECT event_id FROM events WHERE store_id = %s
                        ORDER BY created_at DESC OFFSET %s
                    )
                    """,
                    (store_id, MAX_EVENTS_PER_STORE),
                )
            conn.commit()
        finally:
            self._putconn(conn)

    def persist_snapshot(self, store_id: str, kind: str, payload: Any) -> None:
        updated_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        conn = self._getconn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO store_snapshots(store_id, kind, payload, updated_at)
                    VALUES (%s, %s, %s::jsonb, %s)
                    ON CONFLICT (store_id, kind) DO UPDATE SET
                        payload = EXCLUDED.payload,
                        updated_at = EXCLUDED.updated_at
                    """,
                    (store_id, kind, json.dumps(payload, ensure_ascii=False), updated_at),
                )
            conn.commit()
        finally:
            self._putconn(conn)

    def get_snapshot(self, store_id: str, kind: str) -> Optional[Any]:
        """Read a persisted store snapshot payload by kind."""
        conn = self._getconn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT payload FROM store_snapshots
                    WHERE store_id = %s AND kind = %s
                    """,
                    (store_id, kind),
                )
                row = cur.fetchone()
                if not row:
                    return None
                payload = row[0]
                return payload if isinstance(payload, dict) else json.loads(payload)
        finally:
            self._putconn(conn)

    def update_devices(self, devices: Dict[str, Any]) -> None:
        updated_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        conn = self._getconn()
        try:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM device_registry")
                for device_id, payload in devices.items():
                    cur.execute(
                        """
                        INSERT INTO device_registry(device_id, payload, updated_at)
                        VALUES (%s, %s::jsonb, %s)
                        ON CONFLICT (device_id) DO UPDATE SET
                            payload = EXCLUDED.payload,
                            updated_at = EXCLUDED.updated_at
                        """,
                        (device_id, json.dumps(payload, ensure_ascii=False), updated_at),
                    )
            conn.commit()
        finally:
            self._putconn(conn)

    def get_devices(self) -> Dict[str, Any]:
        conn = self._getconn()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT device_id, payload FROM device_registry")
                return {
                    device_id: payload if isinstance(payload, dict) else json.loads(payload)
                    for device_id, payload in cur.fetchall()
                }
        finally:
            self._putconn(conn)

    def load_store_into(self, hub: Any, store_id: str) -> None:
        store = hub.get_store(store_id)
        conn = self._getconn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT payload FROM events WHERE store_id = %s
                    ORDER BY created_at DESC LIMIT %s
                    """,
                    (store_id, MAX_EVENTS_PER_STORE),
                )
                rows = cur.fetchall()
                events = [row[0] if isinstance(row[0], dict) else json.loads(row[0]) for row in rows]
                store.load_events_batch(events)

                cur.execute(
                    "SELECT kind, payload FROM store_snapshots WHERE store_id = %s",
                    (store_id,),
                )
                for kind, payload in cur.fetchall():
                    data = payload if isinstance(payload, dict) else json.loads(payload)
                    store.load_snapshot(kind, data)
        finally:
            self._putconn(conn)

    def _check_connectivity(self) -> None:
        """Lightweight connectivity probe — raises on failure."""
        conn = self._getconn()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
        finally:
            self._putconn(conn)

    def is_empty(self) -> bool:
        conn = self._getconn()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM events")
                return cur.fetchone()[0] == 0
        finally:
            self._putconn(conn)

    def hydrate_hub(self, hub: Any, store_ids: Optional[List[str]] = None) -> None:
        ids = store_ids or [s["store_id"] for s in hub.list_stores()]
        for sid in ids:
            self.load_store_into(hub, sid)

    def on_persist(self, store_id: str, kind: str, payload: Any) -> None:
        if kind == "event":
            self.persist_event(store_id, payload)
        else:
            self.persist_snapshot(store_id, kind, payload)

    # ── waste count stats (from events, real-time) ──────────────

    def query_waste_count_stats(
        self, store_id: str, days: int = 7
    ) -> Dict[str, Any]:
        """Query last N days of vlm_waste_estimate events, aggregated by day."""
        cutoff = (
            datetime.now(timezone.utc) - timedelta(days=days)
        ).strftime("%Y-%m-%d")

        conn = self._getconn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT payload, created_at FROM events
                    WHERE store_id = %s
                      AND payload->>'event_type' = 'vlm_waste_estimate'
                      AND created_at >= %s
                    ORDER BY created_at DESC
                    """,
                    (store_id, cutoff),
                )
                rows = cur.fetchall()
        finally:
            self._putconn(conn)

        # ── aggregate by day ──
        daily_map: Dict[str, Dict[str, Any]] = {}
        for payload_val, created_at in rows:
            try:
                if isinstance(payload_val, dict):
                    payload = payload_val
                else:
                    payload = json.loads(payload_val)
            except (json.JSONDecodeError, TypeError):
                continue

            meta = payload.get("metadata", {})
            items = meta.get("items", [])
            total_count = meta.get("total_waste_count", 0)

            if not total_count:
                for item in items:
                    c = item.get("count", 0)
                    if isinstance(c, (int, float)):
                        total_count += int(c)

            # PG returns datetime objects for TIMESTAMPTZ
            if isinstance(created_at, datetime):
                date_key = created_at.strftime("%Y-%m-%d")
            else:
                date_key = str(created_at)[:10] if created_at else "unknown"

            if date_key not in daily_map:
                daily_map[date_key] = {
                    "date": date_key,
                    "total_count": 0,
                    "event_count": 0,
                    "items": [],
                }

            entry = daily_map[date_key]
            entry["total_count"] += total_count
            entry["event_count"] += 1

            for item in items:
                sku = item.get("sku", "unknown")
                count = item.get("count", 0)
                if isinstance(count, (int, float)) and count > 0:
                    entry["items"].append({
                        "sku": sku,
                        "count": int(count),
                        "waste_type": item.get("waste_type", "备餐废弃"),
                    })

        # ── sort + fill gaps ──
        daily = sorted(daily_map.values(), key=lambda d: d["date"])

        today = date_type.today()
        full_daily: list = []
        cursor = date_type.fromisoformat(cutoff) if cutoff else today - timedelta(days=days)
        while cursor <= today:
            date_key = cursor.isoformat()
            entry = daily_map.get(date_key)
            if entry:
                full_daily.append(entry)
            else:
                full_daily.append({
                    "date": date_key,
                    "total_count": 0,
                    "event_count": 0,
                    "items": [],
                })
            cursor += timedelta(days=1)
        daily = full_daily

        trend = [d["total_count"] for d in daily]
        dates = [d["date"] for d in daily]

        return {
            "store_id": store_id,
            "days": days,
            "daily": daily,
            "trend": trend,
            "dates": dates,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

    # ── waste timeseries (K-002) ────────────────────────────────

    def upsert_waste_timeseries(
        self, store_id: str, date: str, total_count: int,
        event_count: int, top_skus: list,
    ) -> None:
        """UPSERT waste_timeseries row."""
        generated_at = datetime.now(timezone.utc).isoformat()
        top_skus_json = json.dumps(top_skus, ensure_ascii=False)
        conn = self._getconn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO waste_timeseries
                        (store_id, date, total_count, event_count, top_skus, generated_at)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT(store_id, date) DO UPDATE SET
                        total_count = EXCLUDED.total_count,
                        event_count = EXCLUDED.event_count,
                        top_skus = EXCLUDED.top_skus,
                        generated_at = EXCLUDED.generated_at
                    """,
                    (store_id, date, total_count, event_count, top_skus_json, generated_at),
                )
            conn.commit()
        finally:
            self._putconn(conn)

    # ── G4: KPI 指标持久化 ─────────────────────────────────────

    def upsert_kpi_metric(
        self,
        store_id: str,
        metric_id: str,
        metric_name: str,
        value: float,
        unit: str = "",
        target: Optional[float] = None,
        status: str = "normal",
        trend: str = "unknown",
        change_pct: float = 0.0,
        period_start: Optional[str] = None,
        period_end: Optional[str] = None,
        source_task_id: Optional[str] = None,
        source_event_id: Optional[str] = None,
        category: str = "operation",
        dimensions: Optional[Dict] = None,
        provenance: Optional[Dict] = None,
    ) -> int:
        """UPSERT 一条 KPI 指标记录到 kpi_metrics 表.

        这是 G4 闭环回写的核心方法：任务完成时自动调用此方法将KPI写入Hub PG.

        Args:
            store_id: 门店ID
            metric_id: 指标ID (如 cleaning_response_time, waste_rate)
            metric_name: 中文名称
            value: 指标值
            unit: 单位
            target: 目标值
            status: 状态 (normal/good/warning/critical)
            trend: 趋势 (up/down/stable/unknown)
            change_pct: 变化百分比
            period_start: 统计周期开始 (ISO格式)
            period_end: 统计周期结束
            source_task_id: 触发任务ID (可追溯)
            source_event_id: 触发事件ID
            category: 指标类别
            dimensions: 维度标签 (JSON)
            provenance: 数据溯源信息 (JSON)

        Returns:
            新插入或更新的记录ID

        Raises:
            RuntimeError: PG未连接时
        """
        if not self._pool:
            raise RuntimeError("PostgreSQL 未连接，无法写入 KPI")

        now = datetime.now(timezone.utc).isoformat()
        if period_start is None:
            period_start = now
        if period_end is None:
            period_end = now
        if dimensions is None:
            dimensions = {}
        if provenance is None:
            provenance = {}

        conn = self._getconn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO kpi_metrics
                        (store_id, metric_id, metric_name, value, unit, target,
                         status, trend, change_pct, period_start, period_end,
                         source_task_id, source_event_id, category, dimensions,
                         provenance, created_at, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING id
                    """,
                    (
                        store_id, metric_id, metric_name, value, unit, target,
                        status, trend, change_pct, period_start, period_end,
                        source_task_id, source_event_id, category,
                        json.dumps(dimensions, ensure_ascii=False),
                        json.dumps(provenance, ensure_ascii=False),
                        now, now,
                    ),
                )
                result = cur.fetchone()
                record_id = result[0] if result else -1
            conn.commit()
            return record_id
        finally:
            self._putconn(conn)

    def batch_upsert_kpi_metrics(
        self, metrics: List[Dict[str, Any]]
    ) -> int:
        """批量写入多条 KPI 指标.

        Args:
            metrics: KPI字典列表，每个字典包含 upsert_kpi_metric 所需字段

        Returns:
            成功写入的记录数
        """
        success_count = 0
        for m in metrics:
            try:
                self.upsert_kpi_metric(**m)
                success_count += 1
            except Exception as exc:
                logger.warning("批量KPI写入失败 (metric=%s): %s", m.get("metric_id"), exc)
        return success_count

    def query_kpi_metrics(
        self,
        store_id: str,
        metric_id: Optional[str] = None,
        category: Optional[str] = None,
        period_start: Optional[str] = None,
        period_end: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """查询 KPI 指标历史记录.

        Args:
            store_id: 门店ID
            metric_id: 可选，筛选特定指标
            category: 可选，筛选类别
            period_start: 可选，周期起始
            period_end: 可选，周期结束
            limit: 返回条数上限

        Returns:
            KPI记录列表 (每条为dict)
        """
        if not self._pool:
            return []

        conditions = ["store_id = %s"]
        params: list = [store_id]

        if metric_id:
            conditions.append("metric_id = %s")
            params.append(metric_id)
        if category:
            conditions.append("category = %s")
            params.append(category)
        if period_start:
            conditions.append("period_start >= %s")
            params.append(period_start)
        if period_end:
            conditions.append("period_end <= %s")
            params.append(period_end)

        where_clause = " AND ".join(conditions)
        params.append(limit)

        conn = self._getconn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT id, store_id, metric_id, metric_name, value, unit,
                           target, status, trend, change_pct,
                           period_start, period_end, source_task_id,
                           source_event_id, category, dimensions, provenance,
                           created_at, updated_at
                    FROM kpi_metrics
                    WHERE {where_clause}
                    ORDER BY created_at DESC
                    LIMIT %s
                    """,
                    params,
                )
                columns = [desc[0] for desc in cur.description]
                rows = cur.fetchall()
                return [dict(zip(columns, row)) for row in rows]
        finally:
            self._putconn(conn)

    def query_kpi_latest(
        self, store_id: str, metric_ids: Optional[List[str]] = None,
    ) -> Dict[str, Dict[str, Any]]:
        """查询每个指标的最新一条记录 (用于Dashboard展示).

        Args:
            store_id: 门店ID
            metric_ids: 可选，只查这些指标；None则查全部

        Returns:
            {metric_id: latest_record_dict} 的字典
        """
        if not self._pool:
            return {}

        conn = self._getconn()
        try:
            with conn.cursor() as cur:
                if metric_ids:
                    # 查询指定指标的最新值
                    placeholders = ",".join(["%s"] * len(metric_ids))
                    cur.execute(
                        f"""
                        DISTINCT ON (metric_id) id, store_id, metric_id, metric_name,
                            value, unit, target, status, trend, change_pct,
                            period_start, period_end, source_task_id, category,
                            created_at
                        FROM kpi_metrics
                        WHERE store_id = %s AND metric_id IN ({placeholders})
                        ORDER BY metric_id, created_at DESC
                        """,
                        [store_id] + metric_ids,
                    )
                else:
                    # 查询所有指标的最新值
                    cur.execute(
                        """
                        DISTINCT ON (metric_id) id, store_id, metric_id, metric_name,
                            value, unit, target, status, trend, change_pct,
                            period_start, period_end, source_task_id, category,
                            created_at
                        FROM kpi_metrics
                        WHERE store_id = %s
                        ORDER BY metric_id, created_at DESC
                        """,
                        [store_id],
                    )

                columns = [desc[0] for desc in cur.description]
                rows = cur.fetchall()
                result = {}
                for row in rows:
                    record = dict(zip(columns, row))
                    result[record["metric_id"]] = record
                return result
        finally:
            self._putconn(conn)

    def query_waste_trend(
        self, store_id: str, days: int = 30, include_compare: bool = True,
    ) -> dict:
        """Query waste_timeseries trend; fill missing dates with 0."""
        cutoff_dt = date_type.today() - timedelta(days=days - 1)
        cutoff = cutoff_dt.isoformat()

        daily_map: Dict[str, Dict[str, Any]] = {}
        conn = self._getconn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT date, total_count, event_count, top_skus
                    FROM waste_timeseries
                    WHERE store_id = %s AND date >= %s
                    ORDER BY date ASC
                    """,
                    (store_id, cutoff),
                )
                rows = cur.fetchall()
        finally:
            self._putconn(conn)

        for date_val, total_count, event_count, top_skus_val in rows:
            try:
                top_skus = json.loads(top_skus_val) if top_skus_val else []
            except (json.JSONDecodeError, TypeError):
                top_skus = []
            date_str = str(date_val)[:10] if date_val else ""
            daily_map[date_str] = {
                "date": date_str,
                "total_count": total_count,
                "event_count": event_count,
                "top_skus": top_skus,
            }

        # fill missing dates
        today = date_type.today()
        cursor = cutoff_dt
        full_daily: list = []
        while cursor <= today:
            date_key = cursor.isoformat()
            entry = daily_map.get(date_key)
            if entry:
                full_daily.append(entry)
            else:
                full_daily.append({
                    "date": date_key,
                    "total_count": 0,
                    "event_count": 0,
                    "top_skus": [],
                })
            cursor += timedelta(days=1)

        trend = [d["total_count"] for d in full_daily]
        dates = [d["date"] for d in full_daily]

        result: Dict[str, Any] = {
            "store_id": store_id,
            "days": days,
            "daily": full_daily,
            "trend": trend,
            "dates": dates,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

        if include_compare:
            result["comparison"] = compute_trend_comparison(full_daily)

        return result

    def check_and_create_waste_alert(
        self, store_id: str, date: str,
    ) -> dict:
        """Check if today's waste count triggers a spike alert (idempotent)."""
        today_count = 0
        seven_day_avg = 0.0

        conn = self._getconn()
        try:
            with conn.cursor() as cur:
                # today
                cur.execute(
                    "SELECT total_count FROM waste_timeseries WHERE store_id = %s AND date = %s",
                    (store_id, date),
                )
                row = cur.fetchone()
                if row:
                    today_count = row[0]

                # 7-day average (prior 7 non-zero days)
                cur.execute(
                    """
                    SELECT total_count FROM waste_timeseries
                    WHERE store_id = %s AND date < %s AND total_count > 0
                    ORDER BY date DESC LIMIT 7
                    """,
                    (store_id, date),
                )
                vals_7d = [r[0] for r in cur.fetchall()]
                seven_day_avg = sum(vals_7d) / len(vals_7d) if vals_7d else 0.0
        finally:
            self._putconn(conn)

        triggered, ratio = check_alert(today_count, seven_day_avg)
        alert_id = None

        if triggered:
            message = format_alert_message(date, today_count, seven_day_avg, ratio)
            created_at = datetime.now(timezone.utc).isoformat()
            conn = self._getconn()
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO waste_alerts
                            (store_id, date, alert_type, current_count,
                             baseline_avg, ratio, message, created_at)
                        VALUES (%s, %s, 'spike', %s, %s, %s, %s, %s)
                        ON CONFLICT (store_id, date, alert_type) DO NOTHING
                        """,
                        (store_id, date, today_count, round(seven_day_avg, 1),
                         ratio, message, created_at),
                    )
                conn.commit()

                # Get id of inserted/existing alert
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT id FROM waste_alerts WHERE store_id = %s AND date = %s AND alert_type = 'spike'",
                        (store_id, date),
                    )
                    row = cur.fetchone()
                    if row:
                        alert_id = row[0]
            finally:
                self._putconn(conn)

        return {
            "store_id": store_id,
            "date": date,
            "alert_triggered": triggered,
            "current_count": today_count,
            "seven_day_avg": round(seven_day_avg, 1),
            "ratio": ratio,
            "threshold": 1.5,
            "alert_id": alert_id,
        }

    def list_waste_alerts(self, store_id: str, days: int = 7) -> list:
        """List waste alerts for last N days."""
        cutoff = (date_type.today() - timedelta(days=days - 1)).isoformat()
        conn = self._getconn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, store_id, date, alert_type, current_count,
                           baseline_avg, ratio, message, created_at, acknowledged
                    FROM waste_alerts
                    WHERE store_id = %s AND date >= %s
                    ORDER BY date DESC, id DESC
                    """,
                    (store_id, cutoff),
                )
                columns = [desc[0] for desc in cur.description]
                return [dict(zip(columns, row)) for row in cur.fetchall()]
        finally:
            self._putconn(conn)

    def ack_waste_alert(self, alert_id: int) -> bool:
        """Acknowledge a waste alert. Returns True if updated."""
        conn = self._getconn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE waste_alerts SET acknowledged = 1 WHERE id = %s",
                    (alert_id,),
                )
                conn.commit()
                return cur.rowcount > 0
        finally:
            self._putconn(conn)

    # ── multi-tenant query helpers ──────────────────────────────

    def query_events_by_tenant(
        self,
        tenant_id: str,
        limit: int = 100,
        event_type: Optional[str] = None,
        level: Optional[str] = None,
        since: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Tenant-scoped event query (tenant_id = store_id)."""
        conn = self._getconn()
        try:
            with conn.cursor() as cur:
                conditions = ["store_id = %s"]
                params: List[Any] = [tenant_id]

                if event_type:
                    conditions.append("payload->>'event_type' = %s")
                    params.append(event_type)
                if level:
                    conditions.append("level = %s")
                    params.append(level)
                if since:
                    conditions.append("created_at >= %s")
                    params.append(since)

                where = " AND ".join(conditions)
                cur.execute(
                    f"""
                    SELECT payload FROM events
                    WHERE {where}
                    ORDER BY created_at DESC LIMIT %s
                    """,
                    params + [limit],
                )
                return [
                    row[0] if isinstance(row[0], dict) else json.loads(row[0])
                    for row in cur.fetchall()
                ]
        finally:
            self._putconn(conn)

    def query_tenant_stats(
        self, tenant_id: str, days: int = 7
    ) -> Dict[str, Any]:
        """Aggregated stats for a tenant (= store_id) across all event types."""
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        conn = self._getconn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT level, COUNT(*) as cnt
                    FROM events WHERE store_id = %s AND created_at >= %s
                    GROUP BY level
                    """,
                    (tenant_id, cutoff.isoformat()),
                )
                by_level = {row[0] or "none": row[1] for row in cur.fetchall()}

                cur.execute(
                    """
                    SELECT payload->>'event_type' as event_type, COUNT(*) as cnt
                    FROM events WHERE store_id = %s AND created_at >= %s
                    GROUP BY payload->>'event_type'
                    """,
                    (tenant_id, cutoff.isoformat()),
                )
                by_type = {row[0] or "none": row[1] for row in cur.fetchall()}

                return {
                    "tenant_id": tenant_id,
                    "days": days,
                    "by_level": by_level,
                    "by_type": by_type,
                    "total": sum(by_level.values()),
                }
        finally:
            self._putconn(conn)

    def list_tenants(self) -> List[Dict[str, Any]]:
        """List all tenants (store_ids) with event counts."""
        conn = self._getconn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT store_id, COUNT(*) as event_count,
                           MAX(created_at) as last_seen
                    FROM events GROUP BY store_id
                    ORDER BY last_seen DESC
                    """
                )
                return [
                    {
                        "tenant_id": row[0],
                        "event_count": row[1],
                        "last_seen": row[2].isoformat() if row[2] else None,
                    }
                    for row in cur.fetchall()
                ]
        finally:
            self._putconn(conn)

    def multi_tenant_summary(self) -> Dict[str, Any]:
        """Cross-tenant summary for the unified dashboard."""
        conn = self._getconn()
        try:
            with conn.cursor() as cur:
                # Total tenants
                cur.execute("SELECT COUNT(DISTINCT store_id) FROM events")
                total_tenants = cur.fetchone()[0]

                # Recent alerts (last 24h)
                cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
                cur.execute(
                    """
                    SELECT level, COUNT(*) as cnt
                    FROM events WHERE created_at >= %s
                    AND level IN ('critical','warning')
                    GROUP BY level
                    """,
                    (cutoff.isoformat(),),
                )
                alert_counts = {row[0]: row[1] for row in cur.fetchall()}

                # Total events today
                today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
                cur.execute(
                    """
                    SELECT COUNT(*) FROM events
                    WHERE created_at::date = %s
                    """,
                    (today,),
                )
                today_events = cur.fetchone()[0]

                return {
                    "total_tenants": total_tenants,
                    "critical_alerts_24h": alert_counts.get("critical", 0),
                    "warning_alerts_24h": alert_counts.get("warning", 0),
                    "events_today": today_events,
                    "generated_at": datetime.now(timezone.utc).isoformat(),
                }
        finally:
            self._putconn(conn)

    # ═══════════════════════════════════════════════════════════
    # S02 — 收货质检 (Receiving) 写入/查询方法
    # ═══════════════════════════════════════════════════════════

    def upsert_receiving_batch(
        self, batch_data: Dict[str, Any]
    ) -> Optional[int]:
        """写入或更新收货批次记录到 receiving_batches 表 (S02).

        Args:
            batch_data: 收货批次数据字典，必须包含:
                - batch_id: 批次ID (主键)
                - store_id: 门店ID
                - po_id: 采购单号
                - sku: SKU编码
                - weight_kg: 实收重量(kg)
                可选字段:
                - po_weight_kg: 订单重量
                - variance_pct: 短重率(%)
                - vlm_grade: VLM等级(A/B/C/D)
                - temp_c: 到货温度(°C)
                - status: 状态(submitted/approved/rejected)

        Returns:
            新插入或更新的记录ID；失败返回 None

        Raises:
            RuntimeError: PG未连接时
        """
        if not self._pool:
            raise RuntimeError("PostgreSQL 未连接，无法写入收货记录")

        required_fields = ["batch_id", "store_id", "po_id", "sku", "weight_kg"]
        for field in required_fields:
            if field not in batch_data:
                logger.warning(f"upsert_receiving_batch: 缺少必填字段 {field}")
                return None

        now = datetime.now(timezone.utc).isoformat()
        conn = self._getconn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO receiving_batches
                        (batch_id, store_id, po_id, sku, weight_kg,
                         po_weight_kg, variance_pct, vlm_grade, temp_c,
                         status, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (batch_id) DO UPDATE SET
                        weight_kg = EXCLUDED.weight_kg,
                        po_weight_kg = COALESCE(EXCLUDED.po_weight_kg, receiving_batches.po_weight_kg),
                        variance_pct = COALESCE(EXCLUDED.variance_pct, receiving_batches.variance_pct),
                        vlm_grade = COALESCE(EXCLUDED.vlm_grade, receiving_batches.vlm_grade),
                        temp_c = COALESCE(EXCLUDED.temp_c, receiving_batches.temp_c),
                        status = EXCLUDED.status
                    RETURNING batch_id
                    """,
                    (
                        batch_data["batch_id"],
                        batch_data["store_id"],
                        batch_data["po_id"],
                        batch_data["sku"],
                        batch_data["weight_kg"],
                        batch_data.get("po_weight_kg"),
                        batch_data.get("variance_pct"),
                        batch_data.get("vlm_grade"),
                        batch_data.get("temp_c"),
                        batch_data.get("status", "submitted"),
                        now,
                    ),
                )
                result = cur.fetchone()
                batch_id = result[0] if result else None
            conn.commit()
            return batch_id
        finally:
            self._putconn(conn)

    def upsert_receiving_signature(
        self, signature_data: Dict[str, Any],
    ) -> bool:
        """写入或更新收货签名记录到 receiving_signatures 表.

        Args:
            signature_data: 签名数据字典，必须包含:
                - batch_id: 批次ID
                - store_id: 门店ID
                - role: 角色(receiver/inspector/approver)
                - signed_by: 签名人
            可选:
                - signed_at: 签名时间(默认now)

        Returns:
            True 如果写入成功
        """
        if not self._pool:
            raise RuntimeError("PostgreSQL 未连接，无法写入签名记录")

        required_fields = ["batch_id", "store_id", "role", "signed_by"]
        for field in required_fields:
            if field not in signature_data:
                logger.warning(f"upsert_receiving_signature: 缺少必填字段 {field}")
                return False

        now = signature_data.get(
            "signed_at", datetime.now(timezone.utc).isoformat(),
        )
        conn = self._getconn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO receiving_signatures
                        (batch_id, store_id, role, signed_by, signed_at)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (batch_id, role) DO UPDATE SET
                        signed_by = EXCLUDED.signed_by,
                        signed_at = EXCLUDED.signed_at
                    """,
                    (
                        signature_data["batch_id"],
                        signature_data["store_id"],
                        signature_data["role"],
                        signature_data["signed_by"],
                        now,
                    ),
                )
            conn.commit()
            return True
        finally:
            self._putconn(conn)

    def query_receiving_batches(
        self, store_id: str, days: int = 30,
        status: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """查询门店收货批次列表.

        Args:
            store_id: 门店ID
            days: 查询最近N天
            status: 可选，筛选状态(approved/rejected/submitted)

        Returns:
            收货批次记录列表
        """
        if not self._pool:
            return []

        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        conn = self._getconn()
        try:
            with conn.cursor() as cur:
                params = [store_id, cutoff]
                sql = """
                    SELECT batch_id, store_id, po_id, sku, weight_kg,
                           po_weight_kg, variance_pct, vlm_grade, temp_c,
                           status, created_at
                    FROM receiving_batches
                    WHERE store_id = %s AND created_at >= %s
                """
                if status:
                    sql += " AND status = %s"
                    params.append(status)

                sql += " ORDER BY created_at DESC"
                cur.execute(sql, params)
                columns = [desc[0] for desc in cur.description]
                return [dict(zip(columns, row)) for row in cur.fetchall()]
        finally:
            self._putconn(conn)

    def query_receiving_stats(
        self, store_id: str, days: int = 30,
    ) -> Dict[str, Any]:
        """查询收货统计概览 (用于Dashboard).

        Args:
            store_id: 门店ID
            days: 统计周期(天)

        Returns:
            包含 total_batches / approved_rate / avg_variance / rejection_count 的字典
        """
        if not self._pool:
            return {}

        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        conn = self._getconn()
        try:
            with conn.cursor() as cur:
                # 总批次数 & 各状态计数
                cur.execute(
                    """
                    SELECT
                        COUNT(*) AS total_batches,
                        COUNT(*) FILTER (WHERE status = 'approved') AS approved_count,
                        COUNT(*) FILTER (WHERE status = 'rejected') AS rejected_count,
                        COUNT(*) FILTER (WHERE status = 'submitted') AS submitted_count,
                        AVG(weight_kg) AS avg_weight,
                        AVG(variance_pct) AS avg_variance
                    FROM receiving_batches
                    WHERE store_id = %s AND created_at >= %s
                    """,
                    (store_id, cutoff),
                )
                row = cur.fetchone()
                columns = [desc[0] for desc in cur.description]
                stats = dict(zip(columns, row)) if row else {}

                # 计算通过率
                total = stats.get("total_batches", 0)
                approved = stats.get("approved_count", 0)
                stats["approval_rate"] = round(
                    approved / total * 100, 1,
                ) if total > 0 else 0.0

                stats["store_id"] = store_id
                stats["period_days"] = days
                stats["generated_at"] = datetime.now(timezone.utc).isoformat()

                return stats
        finally:
            self._putconn(conn)
