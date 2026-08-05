"""供应链持久化层 — SQLite/PostgreSQL 双模式适配器。

设计目的：
    - 替代 manager.py 中各 Manager 的 in-memory dict 存储
    - 支持 SQLite（开发/测试）和 PostgreSQL（生产）透明切换
    - 统一 CRUD 接口，Manager 层无需感知底层数据库

Usage:
    db = SupplyChainDB("sqlite:///data/store.db")
    db.save_receiving_record(record)
    records = db.list_receiving_records("store_yuhuan")
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Dict, Generator, List, Optional, Tuple, Union

logger = logging.getLogger(__name__)

# ── Connection Factory ───────────────────────────────────────────────────────


def _connect_sqlite(db_path: str) -> sqlite3.Connection:
    """创建 SQLite 连接并启用外键约束。"""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


# ── DB Adapter ───────────────────────────────────────────────────────────────


class SupplyChainDB:
    """供应链持久化层，统一 CRUD 接口。

    支持的实体：
    - receiving_records: 收货记录
    - quality_check_results: 质检结果
    - purchase_orders: 采购订单
    - approval_workflows: 审批流程
    - supplier_scores: 供应商评分
    - kpi_feedback: KPI 反馈记录
    """

    def __init__(
        self,
        db_uri: str = "",
        db_path: str = "",
    ) -> None:
        """初始化持久化层。

        Args:
            db_uri: SQLAlchemy 风格 URI，如 "sqlite:///data/store.db" 或 "postgresql://..."
            db_path: SQLite 文件路径（与 db_uri 二选一）
        """
        self._db_type = "sqlite"
        if db_path:
            self._db_path = db_path
        elif db_uri:
            if db_uri.startswith("postgresql://") or db_uri.startswith("postgres://"):
                self._db_type = "postgres"
                self._db_uri = db_uri
                self._db_path = ""
            else:
                self._db_path = db_uri.replace("sqlite:///", "")
        else:
            # 默认路径
            default_path = os.environ.get(
                "SUPPLY_CHAIN_DB",
                "data/supply_chain.db",
            )
            self._db_path = default_path

        if self._db_type == "sqlite":
            self._db_path = os.path.abspath(self._db_path)
            os.makedirs(os.path.dirname(self._db_path) or ".", exist_ok=True)
            self._ensure_tables()

    # ── Connection Management ─────────────────────────────────────────────

    @contextmanager
    def _conn(self) -> Generator[sqlite3.Connection, None, None]:
        """获取数据库连接（上下文管理器）。"""
        if self._db_type == "sqlite":
            conn = _connect_sqlite(self._db_path)
            try:
                yield conn
            finally:
                conn.close()
        else:
            # PostgreSQL 模式占位（生产迁移时启用）
            raise NotImplementedError("PostgreSQL support not yet implemented")

    def _ensure_tables(self) -> None:
        """创建所有必要的表（首次启动时自动执行）。"""
        with self._conn() as conn:
            conn.executescript("""
                -- 收货记录表
                CREATE TABLE IF NOT EXISTS receiving_records (
                    batch_id TEXT PRIMARY KEY,
                    store_id TEXT NOT NULL,
                    po_id TEXT,
                    supplier_id TEXT,
                    supplier_name TEXT,
                    sku TEXT,
                    sku_name TEXT,
                    sku_category TEXT,
                    quantity REAL,
                    unit TEXT,
                    order_weight_kg REAL,
                    actual_weight_kg REAL,
                    variance_pct REAL,
                    temp_c REAL,
                    temp_ok INTEGER,
                    photo_urls TEXT,
                    notes TEXT,
                    receiver TEXT,
                    status TEXT DEFAULT 'submitted',
                    created_at TEXT,
                    updated_at TEXT
                );

                -- 质检结果表
                CREATE TABLE IF NOT EXISTS quality_check_results (
                    check_id TEXT PRIMARY KEY,
                    batch_id TEXT NOT NULL,
                    store_id TEXT NOT NULL,
                    weight_deviation_pct REAL,
                    weight_ok INTEGER,
                    temp_value_c REAL,
                    temp_ok INTEGER,
                    vlm_passed INTEGER,
                    vlm_grade TEXT,
                    vlm_confidence REAL,
                    color_ok INTEGER,
                    freshness_ok INTEGER,
                    texture_ok INTEGER,
                    damage_detected INTEGER,
                    final_grade TEXT,
                    action TEXT,
                    manual_review_needed INTEGER,
                    manual_grade TEXT,
                    reviewer_id TEXT,
                    manual_notes TEXT,
                    reviewed_at TEXT,
                    created_at TEXT,
                    FOREIGN KEY (batch_id) REFERENCES receiving_records(batch_id)
                );

                -- 采购订单表
                CREATE TABLE IF NOT EXISTS purchase_orders (
                    po_id TEXT PRIMARY KEY,
                    store_id TEXT NOT NULL,
                    supplier_id TEXT,
                    supplier_name TEXT,
                    items TEXT,
                    total_amount REAL,
                    status TEXT DEFAULT 'draft',
                    expected_delivery_date TEXT,
                    delivery_address TEXT,
                    created_by TEXT,
                    approver_id TEXT,
                    approved_at TEXT,
                    notes TEXT,
                    urgency TEXT DEFAULT 'normal',
                    created_at TEXT,
                    updated_at TEXT
                );

                -- 审批流程表
                CREATE TABLE IF NOT EXISTS approval_workflows (
                    workflow_id TEXT PRIMARY KEY,
                    entity_type TEXT,
                    entity_id TEXT,
                    action_type TEXT,
                    requested_by TEXT,
                    status TEXT DEFAULT 'pending',
                    risk_level TEXT DEFAULT 'medium',
                    approved_by TEXT,
                    approved_at TEXT,
                    rejection_reason TEXT,
                    metadata TEXT,
                    created_at TEXT
                );

                -- 供应商评分表
                CREATE TABLE IF NOT EXISTS supplier_scores (
                    supplier_id TEXT,
                    store_id TEXT,
                    score REAL,
                    grade TEXT,
                    delivery_on_time_rate REAL,
                    quality_pass_rate REAL,
                    price_competitiveness REAL,
                    response_speed REAL,
                    updated_at TEXT,
                    PRIMARY KEY (supplier_id, store_id)
                );

                -- KPI 反馈表
                CREATE TABLE IF NOT EXISTS kpi_feedback (
                    feedback_id TEXT PRIMARY KEY,
                    store_id TEXT NOT NULL,
                    kpi_name TEXT,
                    event_type TEXT,
                    source TEXT,
                    action_taken TEXT,
                    result REAL,
                    verified_by TEXT,
                    verified_at TEXT,
                    metadata TEXT,
                    created_at TEXT
                );

                -- 库存台账表
                CREATE TABLE IF NOT EXISTS inventory_ledger (
                    ledger_id TEXT PRIMARY KEY,
                    store_id TEXT NOT NULL,
                    sku TEXT,
                    sku_name TEXT,
                    sku_category TEXT,
                    change_type TEXT,
                    change_qty REAL,
                    balance_qty REAL,
                    unit TEXT,
                    related_po_id TEXT,
                    related_batch_id TEXT,
                    operator TEXT,
                    notes TEXT,
                    created_at TEXT
                );

                CREATE INDEX IF NOT EXISTS idx_rr_store ON receiving_records(store_id);
                CREATE INDEX IF NOT EXISTS idx_qc_batch ON quality_check_results(batch_id);
                CREATE INDEX IF NOT EXISTS idx_po_store ON purchase_orders(store_id);
                CREATE INDEX IF NOT EXISTS idx_aw_entity ON approval_workflows(entity_id);
                CREATE INDEX IF NOT EXISTS idx_il_store_sku ON inventory_ledger(store_id, sku);
            """)
            conn.commit()

    # ── Receiving Records ─────────────────────────────────────────────────

    def save_receiving_record(self, record: dict) -> bool:
        """保存收货记录。"""
        try:
            with self._conn() as conn:
                conn.execute("""
                    INSERT OR REPLACE INTO receiving_records
                    (batch_id, store_id, po_id, supplier_id, supplier_name,
                     sku, sku_name, sku_category, quantity, unit,
                     order_weight_kg, actual_weight_kg, variance_pct,
                     temp_c, temp_ok, photo_urls, notes, receiver,
                     status, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    record.get("batch_id", ""),
                    record.get("store_id", ""),
                    record.get("po_id", ""),
                    record.get("supplier_id", ""),
                    record.get("supplier_name", ""),
                    record.get("sku", ""),
                    record.get("sku_name", ""),
                    record.get("sku_category", ""),
                    record.get("quantity", 0.0),
                    record.get("unit", "kg"),
                    record.get("order_weight_kg", 0.0),
                    record.get("actual_weight_kg", 0.0),
                    record.get("variance_pct"),
                    record.get("temp_c"),
                    bool(record.get("temp_ok", True)),
                    json.dumps(record.get("photo_urls", []), ensure_ascii=False),
                    record.get("notes", ""),
                    record.get("receiver", ""),
                    record.get("status", "submitted"),
                    record.get("created_at", _now()),
                    record.get("updated_at", _now()),
                ))
                conn.commit()
            return True
        except Exception as e:
            logger.error(f"Failed to save receiving record: {e}")
            return False

    def get_receiving_record(self, batch_id: str) -> Optional[dict]:
        """获取收货记录。"""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM receiving_records WHERE batch_id = ?", (batch_id,)
            ).fetchone()
            return dict(row) if row else None

    def list_receiving_records(self, store_id: str, limit: int = 50) -> list[dict]:
        """列出门店收货记录。"""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM receiving_records WHERE store_id = ? ORDER BY created_at DESC LIMIT ?",
                (store_id, limit),
            ).fetchall()
            return [dict(r) for r in rows]

    # ── Quality Checks ────────────────────────────────────────────────────

    def save_quality_check(self, check: dict) -> bool:
        """保存质检结果。"""
        try:
            with self._conn() as conn:
                conn.execute("""
                    INSERT OR REPLACE INTO quality_check_results
                    (check_id, batch_id, store_id, weight_deviation_pct, weight_ok,
                     temp_value_c, temp_ok, vlm_passed, vlm_grade, vlm_confidence,
                     color_ok, freshness_ok, texture_ok, damage_detected,
                     final_grade, action, manual_review_needed, manual_grade,
                     reviewer_id, manual_notes, reviewed_at, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    check.get("check_id", ""),
                    check.get("batch_id", ""),
                    check.get("store_id", ""),
                    check.get("weight_deviation_pct"),
                    bool(check.get("weight_ok", True)),
                    check.get("temp_value_c"),
                    bool(check.get("temp_ok", True)),
                    bool(check.get("vlm_passed", False)),
                    check.get("vlm_grade", ""),
                    check.get("vlm_confidence", 0.0),
                    bool(check.get("color_ok", True)),
                    bool(check.get("freshness_ok", True)),
                    bool(check.get("texture_ok", True)),
                    bool(check.get("damage_detected", False)),
                    check.get("final_grade", "C"),
                    check.get("action", ""),
                    bool(check.get("manual_review_needed", False)),
                    check.get("manual_grade", ""),
                    check.get("reviewer_id", ""),
                    check.get("manual_notes", ""),
                    check.get("reviewed_at", ""),
                    check.get("created_at", _now()),
                ))
                conn.commit()
            return True
        except Exception as e:
            logger.error(f"Failed to save quality check: {e}")
            return False

    def get_quality_check(self, check_id: str) -> Optional[dict]:
        """获取质检结果。"""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM quality_check_results WHERE check_id = ?", (check_id,)
            ).fetchone()
            return dict(row) if row else None

    # ── Purchase Orders ───────────────────────────────────────────────────

    def save_purchase_order(self, order: dict) -> bool:
        """保存采购订单。"""
        try:
            with self._conn() as conn:
                conn.execute("""
                    INSERT OR REPLACE INTO purchase_orders
                    (po_id, store_id, supplier_id, supplier_name, items, total_amount,
                     status, expected_delivery_date, delivery_address, created_by,
                     approver_id, approved_at, notes, urgency, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    order.get("po_id", ""),
                    order.get("store_id", ""),
                    order.get("supplier_id", ""),
                    order.get("supplier_name", ""),
                    json.dumps(order.get("items", []), ensure_ascii=False),
                    order.get("total_amount", 0.0),
                    order.get("status", "draft"),
                    order.get("expected_delivery_date", ""),
                    order.get("delivery_address", ""),
                    order.get("created_by", ""),
                    order.get("approver_id", ""),
                    order.get("approved_at", ""),
                    order.get("notes", ""),
                    order.get("urgency", "normal"),
                    order.get("created_at", _now()),
                    order.get("updated_at", _now()),
                ))
                conn.commit()
            return True
        except Exception as e:
            logger.error(f"Failed to save purchase order: {e}")
            return False

    def get_purchase_order(self, po_id: str) -> Optional[dict]:
        """获取采购订单。"""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM purchase_orders WHERE po_id = ?", (po_id,)
            ).fetchone()
            if row:
                d = dict(row)
                items_str = d.get("items", "[]")
                if isinstance(items_str, str):
                    try:
                        d["items"] = json.loads(items_str)
                    except json.JSONDecodeError:
                        d["items"] = []
                return d
            return None

    def list_purchase_orders(self, store_id: str) -> list[dict]:
        """列出门店采购订单。"""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM purchase_orders WHERE store_id = ? ORDER BY created_at DESC",
                (store_id,),
            ).fetchall()
            result = []
            for r in rows:
                d = dict(r)
                items_str = d.get("items", "[]")
                if isinstance(items_str, str):
                    try:
                        d["items"] = json.loads(items_str)
                    except json.JSONDecodeError:
                        d["items"] = []
                result.append(d)
            return result

    # ── Approval Workflows ────────────────────────────────────────────────

    def save_approval(self, approval: dict) -> bool:
        """保存审批记录。"""
        try:
            with self._conn() as conn:
                conn.execute("""
                    INSERT OR REPLACE INTO approval_workflows
                    (workflow_id, entity_type, entity_id, action_type, requested_by,
                     status, risk_level, approved_by, approved_at, rejection_reason,
                     metadata, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    approval.get("workflow_id", ""),
                    approval.get("entity_type", ""),
                    approval.get("entity_id", ""),
                    approval.get("action_type", ""),
                    approval.get("requested_by", ""),
                    approval.get("status", "pending"),
                    approval.get("risk_level", "medium"),
                    approval.get("approved_by", ""),
                    approval.get("approved_at", ""),
                    approval.get("rejection_reason", ""),
                    json.dumps(approval.get("metadata", {}), ensure_ascii=False),
                    approval.get("created_at", _now()),
                ))
                conn.commit()
            return True
        except Exception as e:
            logger.error(f"Failed to save approval: {e}")
            return False

    # ── Supplier Scores ───────────────────────────────────────────────────

    def save_supplier_score(self, score: dict) -> bool:
        """保存供应商评分。"""
        try:
            with self._conn() as conn:
                conn.execute("""
                    INSERT OR REPLACE INTO supplier_scores
                    (supplier_id, store_id, score, grade, delivery_on_time_rate,
                     quality_pass_rate, price_competitiveness, response_speed, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    score.get("supplier_id", ""),
                    score.get("store_id", ""),
                    score.get("score", 0),
                    score.get("grade", "C"),
                    score.get("delivery_on_time_rate", 0),
                    score.get("quality_pass_rate", 0),
                    score.get("price_competitiveness", 0),
                    score.get("response_speed", 0),
                    score.get("updated_at", _now()),
                ))
                conn.commit()
            return True
        except Exception as e:
            logger.error(f"Failed to save supplier score: {e}")
            return False

    def get_supplier_scores(self, store_id: str) -> list[dict]:
        """获取供应商评分列表。"""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM supplier_scores WHERE store_id = ? ORDER BY score DESC",
                (store_id,),
            ).fetchall()
            return [dict(r) for r in rows]

    # ── Product Master ────────────────────────────────────────────────────

    def fetch_products(
        self, store_id: str = "", active_only: bool = True,
        limit: int = 50, offset: int = 0,
    ) -> List[dict]:
        """查询产品主数据（支持 PG 透明切换）。"""
        with self._conn() as conn:
            # 确保 product_master 表存在（首次懒初始化）
            conn.execute("""
                CREATE TABLE IF NOT EXISTS product_master (
                    product_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    category TEXT,
                    unit TEXT DEFAULT 'kg',
                    brand TEXT DEFAULT '',
                    supplier_id TEXT DEFAULT '',
                    price REAL DEFAULT 0.0,
                    is_active INTEGER DEFAULT 1,
                    version INTEGER DEFAULT 1,
                    created_at TEXT,
                    updated_at TEXT
                )
            """)
            conn.commit()

            query = "SELECT * FROM product_master WHERE 1=1"
            params: list = []
            if active_only:
                query += " AND is_active = 1"
            query += " ORDER BY name LIMIT ? OFFSET ?"
            params.extend([limit, offset])
            rows = conn.execute(query, params).fetchall()
            return [dict(r) for r in rows]

    def insert_product(
        self, product_id: str, name: str, category: str = "",
        unit: str = "kg", brand: str = "", supplier_id: str = "",
        price: float = 0.0, is_active: bool = True,
    ) -> bool:
        """插入产品主数据。"""
        try:
            with self._conn() as conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS product_master (
                        product_id TEXT PRIMARY KEY,
                        name TEXT NOT NULL,
                        category TEXT,
                        unit TEXT DEFAULT 'kg',
                        brand TEXT DEFAULT '',
                        supplier_id TEXT DEFAULT '',
                        price REAL DEFAULT 0.0,
                        is_active INTEGER DEFAULT 1,
                        version INTEGER DEFAULT 1,
                        created_at TEXT,
                        updated_at TEXT
                    )
                """)
                conn.execute("""
                    INSERT OR REPLACE INTO product_master
                    (product_id, name, category, unit, brand, supplier_id,
                     price, is_active, version, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
                """, (
                    product_id, name, category, unit, brand, supplier_id,
                    price, int(is_active), _now(), _now(),
                ))
                conn.commit()
            return True
        except Exception as e:
            logger.error(f"Failed to insert product: {e}")
            return False

    # ── Inventory Ledger ──────────────────────────────────────────────────

    def save_ledger_entry(self, entry: dict) -> bool:
        """保存库存台账条目。"""
        try:
            with self._conn() as conn:
                conn.execute("""
                    INSERT OR REPLACE INTO inventory_ledger
                    (ledger_id, store_id, sku, sku_name, sku_category,
                     change_type, change_qty, balance_qty, unit,
                     related_po_id, related_batch_id, operator, notes, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    entry.get("ledger_id", ""),
                    entry.get("store_id", ""),
                    entry.get("sku", ""),
                    entry.get("sku_name", ""),
                    entry.get("sku_category", ""),
                    entry.get("change_type", ""),
                    entry.get("change_qty", 0.0),
                    entry.get("balance_qty", 0.0),
                    entry.get("unit", "kg"),
                    entry.get("related_po_id", ""),
                    entry.get("related_batch_id", ""),
                    entry.get("operator", ""),
                    entry.get("notes", ""),
                    entry.get("created_at", _now()),
                ))
                conn.commit()
            return True
        except Exception as e:
            logger.error(f"Failed to save ledger entry: {e}")
            return False

    def get_inventory_balance(self, store_id: str, sku: str) -> float:
        """获取指定 SKU 的最新库存余额。"""
        with self._conn() as conn:
            row = conn.execute(
                """SELECT balance_qty FROM inventory_ledger
                   WHERE store_id = ? AND sku = ?
                   ORDER BY created_at DESC LIMIT 1""",
                (store_id, sku),
            ).fetchone()
            return float(row["balance_qty"]) if row else 0.0

    # ── KPI Feedback ──────────────────────────────────────────────────────

    def save_kpi_feedback(self, feedback: dict) -> bool:
        """保存 KPI 反馈记录。"""
        try:
            with self._conn() as conn:
                conn.execute("""
                    INSERT OR REPLACE INTO kpi_feedback
                    (feedback_id, store_id, kpi_name, event_type, source,
                     action_taken, result, verified_by, verified_at, metadata, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    feedback.get("feedback_id", ""),
                    feedback.get("store_id", ""),
                    feedback.get("kpi_name", ""),
                    feedback.get("event_type", ""),
                    feedback.get("source", ""),
                    feedback.get("action_taken", ""),
                    feedback.get("result", 0.0),
                    feedback.get("verified_by", ""),
                    feedback.get("verified_at", ""),
                    json.dumps(feedback.get("metadata", {}), ensure_ascii=False),
                    feedback.get("created_at", _now()),
                ))
                conn.commit()
            return True
        except Exception as e:
            logger.error(f"Failed to save KPI feedback: {e}")
            return False

    # ── Health & Stats ────────────────────────────────────────────────────

    def health_check(self) -> dict:
        """数据库健康检查。"""
        try:
            with self._conn() as conn:
                row = conn.execute("SELECT 1").fetchone()
                return {
                    "db_type": self._db_type,
                    "ok": row is not None,
                    "db_path": getattr(self, "_db_path", ""),
                }
        except Exception as e:
            return {"db_type": self._db_type, "ok": False, "error": str(e)}

    def table_counts(self) -> dict:
        """返回各表行数统计。"""
        tables = [
            "receiving_records", "quality_check_results", "purchase_orders",
            "approval_workflows", "supplier_scores", "kpi_feedback", "inventory_ledger",
        ]
        counts = {}
        with self._conn() as conn:
            for table in tables:
                row = conn.execute(f"SELECT COUNT(*) as cnt FROM {table}").fetchone()
                counts[table] = row["cnt"] if row else 0
        return counts


# ── Helpers ──────────────────────────────────────────────────────────────────


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Singleton ────────────────────────────────────────────────────────────────

_db_instance: Optional[SupplyChainDB] = None


def get_db(db_path: str = "") -> SupplyChainDB:
    """获取数据库单例。"""
    global _db_instance
    if _db_instance is None:
        _db_instance = SupplyChainDB(db_path=db_path)
    return _db_instance


def init_db(db_path: str = "") -> SupplyChainDB:
    """初始化并返回数据库实例（强制重建单例）。"""
    global _db_instance
    _db_instance = SupplyChainDB(db_path=db_path)
    return _db_instance
