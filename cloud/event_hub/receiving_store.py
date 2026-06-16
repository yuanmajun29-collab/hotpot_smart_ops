"""Receiving batches and signature persistence (DEV-420 / BL-05)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

REQUIRED_SIGNATURE_ROLES = frozenset({"receiver", "chef"})


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def new_batch_id(store_id: str) -> str:
    day = datetime.now(timezone.utc).strftime("%Y%m%d")
    short = uuid.uuid4().hex[:6].upper()
    suffix = store_id.replace("store_", "")[:8]
    return f"RCV-{day}-{suffix}-{short}"


def variance_pct(weight_kg: float, po_weight_kg: Optional[float]) -> Optional[float]:
    if po_weight_kg is None or po_weight_kg == 0:
        return None
    return round((weight_kg - po_weight_kg) / po_weight_kg * 100.0, 2)


SQLITE_RECEIVING_SCHEMA = """
CREATE TABLE IF NOT EXISTS receiving_batches (
    batch_id TEXT PRIMARY KEY,
    store_id TEXT NOT NULL,
    po_id TEXT NOT NULL,
    sku TEXT NOT NULL,
    weight_kg REAL NOT NULL,
    po_weight_kg REAL,
    variance_pct REAL,
    vlm_grade TEXT,
    temp_c REAL,
    status TEXT NOT NULL DEFAULT 'submitted',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_receiving_batches_store
    ON receiving_batches(store_id, created_at DESC);

CREATE TABLE IF NOT EXISTS receiving_signatures (
    batch_id TEXT NOT NULL,
    store_id TEXT NOT NULL,
    role TEXT NOT NULL,
    signed_by TEXT NOT NULL,
    signed_at TEXT NOT NULL,
    PRIMARY KEY (batch_id, role)
);
CREATE INDEX IF NOT EXISTS idx_receiving_signatures_store
    ON receiving_signatures(store_id, signed_at DESC);
"""

PG_RECEIVING_SCHEMA = """
CREATE TABLE IF NOT EXISTS receiving_batches (
    batch_id TEXT PRIMARY KEY,
    store_id TEXT NOT NULL,
    po_id TEXT NOT NULL,
    sku TEXT NOT NULL,
    weight_kg DOUBLE PRECISION NOT NULL,
    po_weight_kg DOUBLE PRECISION,
    variance_pct DOUBLE PRECISION,
    vlm_grade TEXT,
    temp_c DOUBLE PRECISION,
    status TEXT NOT NULL DEFAULT 'submitted',
    created_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_receiving_batches_store
    ON receiving_batches(store_id, created_at DESC);

CREATE TABLE IF NOT EXISTS receiving_signatures (
    batch_id TEXT NOT NULL,
    store_id TEXT NOT NULL,
    role TEXT NOT NULL,
    signed_by TEXT NOT NULL,
    signed_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (batch_id, role)
);
CREATE INDEX IF NOT EXISTS idx_receiving_signatures_store
    ON receiving_signatures(store_id, signed_at DESC);
"""


class ReceivingStore:
    """SQLite / PostgreSQL receiving audit store."""

    def __init__(self, db: Any) -> None:
        self.db = db

    @property
    def is_pg(self) -> bool:
        return type(self.db).__name__ == "PostgresHubDatabase"

    def _connect(self):
        return self.db._connect()

    @property
    def _lock(self):
        return self.db._lock

    def batch_exists(self, batch_id: str) -> bool:
        with self._lock:
            conn = self._connect()
            try:
                if self.is_pg:
                    with conn.cursor() as cur:
                        cur.execute(
                            "SELECT 1 FROM receiving_batches WHERE batch_id = %s",
                            (batch_id,),
                        )
                        return cur.fetchone() is not None
                row = conn.execute(
                    "SELECT 1 FROM receiving_batches WHERE batch_id = ?",
                    (batch_id,),
                ).fetchone()
                return row is not None
            finally:
                conn.close()

    def submit(
        self,
        store_id: str,
        batch: Dict[str, Any],
        signatures: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        roles = {s["role"] for s in signatures}
        missing = REQUIRED_SIGNATURE_ROLES - roles
        if missing:
            raise ValueError(f"缺少签字角色: {', '.join(sorted(missing))}")

        batch_id = batch["batch_id"]
        if self.batch_exists(batch_id):
            raise ValueError(f"批次已存在: {batch_id}")

        created_at = batch.get("created_at") or utc_now_iso()
        with self._lock:
            conn = self._connect()
            try:
                if self.is_pg:
                    with conn.cursor() as cur:
                        cur.execute(
                            """
                            INSERT INTO receiving_batches(
                                batch_id, store_id, po_id, sku, weight_kg, po_weight_kg,
                                variance_pct, vlm_grade, temp_c, status, created_at
                            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                            """,
                            (
                                batch_id,
                                store_id,
                                batch["po_id"],
                                batch["sku"],
                                batch["weight_kg"],
                                batch.get("po_weight_kg"),
                                batch.get("variance_pct"),
                                batch.get("vlm_grade"),
                                batch.get("temp_c"),
                                batch.get("status", "submitted"),
                                created_at,
                            ),
                        )
                        for sig in signatures:
                            signed_at = sig.get("signed_at") or utc_now_iso()
                            cur.execute(
                                """
                                INSERT INTO receiving_signatures(
                                    batch_id, store_id, role, signed_by, signed_at
                                ) VALUES (%s,%s,%s,%s,%s)
                                """,
                                (
                                    batch_id,
                                    store_id,
                                    sig["role"],
                                    sig["signed_by"],
                                    signed_at,
                                ),
                            )
                    conn.commit()
                else:
                    conn.execute(
                        """
                        INSERT INTO receiving_batches(
                            batch_id, store_id, po_id, sku, weight_kg, po_weight_kg,
                            variance_pct, vlm_grade, temp_c, status, created_at
                        ) VALUES (?,?,?,?,?,?,?,?,?,?,?)
                        """,
                        (
                            batch_id,
                            store_id,
                            batch["po_id"],
                            batch["sku"],
                            batch["weight_kg"],
                            batch.get("po_weight_kg"),
                            batch.get("variance_pct"),
                            batch.get("vlm_grade"),
                            batch.get("temp_c"),
                            batch.get("status", "submitted"),
                            created_at,
                        ),
                    )
                    for sig in signatures:
                        signed_at = sig.get("signed_at") or utc_now_iso()
                        conn.execute(
                            """
                            INSERT INTO receiving_signatures(
                                batch_id, store_id, role, signed_by, signed_at
                            ) VALUES (?,?,?,?,?)
                            """,
                            (
                                batch_id,
                                store_id,
                                sig["role"],
                                sig["signed_by"],
                                signed_at,
                            ),
                        )
                    conn.commit()
            finally:
                conn.close()

        return {
            "batch_id": batch_id,
            "store_id": store_id,
            "status": batch.get("status", "submitted"),
            "created_at": created_at,
            "signatures": signatures,
        }

    def list_batches(
        self,
        store_id: str,
        *,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        with self._lock:
            conn = self._connect()
            try:
                if self.is_pg:
                    with conn.cursor() as cur:
                        cur.execute(
                            """
                            SELECT batch_id, store_id, po_id, sku, weight_kg, po_weight_kg,
                                   variance_pct, vlm_grade, temp_c, status, created_at
                            FROM receiving_batches
                            WHERE store_id = %s
                            ORDER BY created_at DESC
                            LIMIT %s
                            """,
                            (store_id, limit),
                        )
                        cols = [
                            "batch_id",
                            "store_id",
                            "po_id",
                            "sku",
                            "weight_kg",
                            "po_weight_kg",
                            "variance_pct",
                            "vlm_grade",
                            "temp_c",
                            "status",
                            "created_at",
                        ]
                        return [dict(zip(cols, row)) for row in cur.fetchall()]

                rows = conn.execute(
                    """
                    SELECT batch_id, store_id, po_id, sku, weight_kg, po_weight_kg,
                           variance_pct, vlm_grade, temp_c, status, created_at
                    FROM receiving_batches
                    WHERE store_id = ?
                    ORDER BY created_at DESC
                    LIMIT ?
                    """,
                    (store_id, limit),
                ).fetchall()
                return [dict(r) for r in rows]
            finally:
                conn.close()

    def list_signatures(
        self,
        store_id: str,
        *,
        batch_id: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        with self._lock:
            conn = self._connect()
            try:
                if self.is_pg:
                    with conn.cursor() as cur:
                        if batch_id:
                            cur.execute(
                                """
                                SELECT s.batch_id, s.store_id, s.role, s.signed_by, s.signed_at,
                                       b.po_id, b.sku, b.weight_kg, b.variance_pct, b.vlm_grade
                                FROM receiving_signatures s
                                JOIN receiving_batches b ON b.batch_id = s.batch_id
                                WHERE s.store_id = %s AND s.batch_id = %s
                                ORDER BY s.signed_at DESC
                                """,
                                (store_id, batch_id),
                            )
                        else:
                            cur.execute(
                                """
                                SELECT s.batch_id, s.store_id, s.role, s.signed_by, s.signed_at,
                                       b.po_id, b.sku, b.weight_kg, b.variance_pct, b.vlm_grade
                                FROM receiving_signatures s
                                JOIN receiving_batches b ON b.batch_id = s.batch_id
                                WHERE s.store_id = %s
                                ORDER BY s.signed_at DESC
                                LIMIT %s
                                """,
                                (store_id, limit),
                            )
                        cols = [
                            "batch_id",
                            "store_id",
                            "role",
                            "signed_by",
                            "signed_at",
                            "po_id",
                            "sku",
                            "weight_kg",
                            "variance_pct",
                            "vlm_grade",
                        ]
                        return [dict(zip(cols, row)) for row in cur.fetchall()]

                if batch_id:
                    rows = conn.execute(
                        """
                        SELECT s.batch_id, s.store_id, s.role, s.signed_by, s.signed_at,
                               b.po_id, b.sku, b.weight_kg, b.variance_pct, b.vlm_grade
                        FROM receiving_signatures s
                        JOIN receiving_batches b ON b.batch_id = s.batch_id
                        WHERE s.store_id = ? AND s.batch_id = ?
                        ORDER BY s.signed_at DESC
                        """,
                        (store_id, batch_id),
                    ).fetchall()
                else:
                    rows = conn.execute(
                        """
                        SELECT s.batch_id, s.store_id, s.role, s.signed_by, s.signed_at,
                               b.po_id, b.sku, b.weight_kg, b.variance_pct, b.vlm_grade
                        FROM receiving_signatures s
                        JOIN receiving_batches b ON b.batch_id = s.batch_id
                        WHERE s.store_id = ?
                        ORDER BY s.signed_at DESC
                        LIMIT ?
                        """,
                        (store_id, limit),
                    ).fetchall()
                return [dict(r) for r in rows]
            finally:
                conn.close()


def receiving_store(db: Any) -> ReceivingStore:
    return ReceivingStore(db)
