"""SOP violation assignment persistence (DEV-421 / BL-05)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

ASSIGNMENT_STATUSES = frozenset({"open", "done", "verified"})


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def new_assignment_id(store_id: str) -> str:
    day = datetime.now(timezone.utc).strftime("%Y%m%d")
    short = uuid.uuid4().hex[:6].upper()
    suffix = store_id.replace("store_", "")[:8]
    return f"SOP-{day}-{suffix}-{short}"


SQLITE_SOP_ASSIGN_SCHEMA = """
CREATE TABLE IF NOT EXISTS sop_assignments (
    assignment_id TEXT PRIMARY KEY,
    store_id TEXT NOT NULL,
    sop_id TEXT NOT NULL,
    sop_name TEXT,
    assignee TEXT NOT NULL,
    assigned_by TEXT,
    event_id TEXT,
    note TEXT DEFAULT '',
    status TEXT NOT NULL DEFAULT 'open',
    due_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sop_assignments_store
    ON sop_assignments(store_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_sop_assignments_status
    ON sop_assignments(store_id, status);
"""

PG_SOP_ASSIGN_SCHEMA = """
CREATE TABLE IF NOT EXISTS sop_assignments (
    assignment_id TEXT PRIMARY KEY,
    store_id TEXT NOT NULL,
    sop_id TEXT NOT NULL,
    sop_name TEXT,
    assignee TEXT NOT NULL,
    assigned_by TEXT,
    event_id TEXT,
    note TEXT DEFAULT '',
    status TEXT NOT NULL DEFAULT 'open',
    due_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sop_assignments_store
    ON sop_assignments(store_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_sop_assignments_status
    ON sop_assignments(store_id, status);
"""


class SopAssignStore:
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

    def create(
        self,
        store_id: str,
        *,
        sop_id: str,
        assignee: str,
        sop_name: Optional[str] = None,
        assigned_by: Optional[str] = None,
        event_id: Optional[str] = None,
        note: str = "",
        due_at: Optional[str] = None,
        assignment_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        aid = assignment_id or new_assignment_id(store_id)
        now = utc_now_iso()
        row = {
            "assignment_id": aid,
            "store_id": store_id,
            "sop_id": sop_id,
            "sop_name": sop_name or sop_id,
            "assignee": assignee,
            "assigned_by": assigned_by or "",
            "event_id": event_id or "",
            "note": note,
            "status": "open",
            "due_at": due_at,
            "created_at": now,
            "updated_at": now,
        }
        with self._lock:
            conn = self._connect()
            try:
                if self.is_pg:
                    with conn.cursor() as cur:
                        cur.execute(
                            """
                            INSERT INTO sop_assignments(
                                assignment_id, store_id, sop_id, sop_name, assignee,
                                assigned_by, event_id, note, status, due_at,
                                created_at, updated_at
                            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                            """,
                            (
                                aid,
                                store_id,
                                sop_id,
                                row["sop_name"],
                                assignee,
                                row["assigned_by"],
                                row["event_id"],
                                note,
                                "open",
                                due_at,
                                now,
                                now,
                            ),
                        )
                    conn.commit()
                else:
                    conn.execute(
                        """
                        INSERT INTO sop_assignments(
                            assignment_id, store_id, sop_id, sop_name, assignee,
                            assigned_by, event_id, note, status, due_at,
                            created_at, updated_at
                        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                        """,
                        (
                            aid,
                            store_id,
                            sop_id,
                            row["sop_name"],
                            assignee,
                            row["assigned_by"],
                            row["event_id"],
                            note,
                            "open",
                            due_at,
                            now,
                            now,
                        ),
                    )
                    conn.commit()
            finally:
                conn.close()
        return row

    def update_status(
        self,
        assignment_id: str,
        store_id: str,
        status: str,
    ) -> Optional[Dict[str, Any]]:
        if status not in ASSIGNMENT_STATUSES:
            raise ValueError(f"无效状态: {status}")
        now = utc_now_iso()
        with self._lock:
            conn = self._connect()
            try:
                if self.is_pg:
                    with conn.cursor() as cur:
                        cur.execute(
                            """
                            UPDATE sop_assignments
                            SET status = %s, updated_at = %s
                            WHERE assignment_id = %s AND store_id = %s
                            RETURNING assignment_id, store_id, sop_id, sop_name, assignee,
                                      assigned_by, event_id, note, status, due_at,
                                      created_at, updated_at
                            """,
                            (status, now, assignment_id, store_id),
                        )
                        row = cur.fetchone()
                    conn.commit()
                    if not row:
                        return None
                    cols = [
                        "assignment_id",
                        "store_id",
                        "sop_id",
                        "sop_name",
                        "assignee",
                        "assigned_by",
                        "event_id",
                        "note",
                        "status",
                        "due_at",
                        "created_at",
                        "updated_at",
                    ]
                    return dict(zip(cols, row))

                cur = conn.execute(
                    """
                    UPDATE sop_assignments
                    SET status = ?, updated_at = ?
                    WHERE assignment_id = ? AND store_id = ?
                    """,
                    (status, now, assignment_id, store_id),
                )
                conn.commit()
                if cur.rowcount == 0:
                    return None
            finally:
                conn.close()
        return self.get(assignment_id, store_id)

    def get(self, assignment_id: str, store_id: str) -> Optional[Dict[str, Any]]:
        rows = self.list_assignments(store_id, assignment_id=assignment_id, limit=1)
        return rows[0] if rows else None

    def list_assignments(
        self,
        store_id: str,
        *,
        status: Optional[str] = None,
        assignment_id: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        with self._lock:
            conn = self._connect()
            try:
                if self.is_pg:
                    clauses = ["store_id = %s"]
                    params: List[Any] = [store_id]
                    if assignment_id:
                        clauses.append("assignment_id = %s")
                        params.append(assignment_id)
                    if status:
                        clauses.append("status = %s")
                        params.append(status)
                    sql = f"""
                        SELECT assignment_id, store_id, sop_id, sop_name, assignee,
                               assigned_by, event_id, note, status, due_at,
                               created_at, updated_at
                        FROM sop_assignments
                        WHERE {' AND '.join(clauses)}
                        ORDER BY created_at DESC
                        LIMIT %s
                    """
                    params.append(limit)
                    with conn.cursor() as cur:
                        cur.execute(sql, tuple(params))
                        cols = [
                            "assignment_id",
                            "store_id",
                            "sop_id",
                            "sop_name",
                            "assignee",
                            "assigned_by",
                            "event_id",
                            "note",
                            "status",
                            "due_at",
                            "created_at",
                            "updated_at",
                        ]
                        return [dict(zip(cols, row)) for row in cur.fetchall()]

                clauses = ["store_id = ?"]
                params = [store_id]
                if assignment_id:
                    clauses.append("assignment_id = ?")
                    params.append(assignment_id)
                if status:
                    clauses.append("status = ?")
                    params.append(status)
                sql = f"""
                    SELECT assignment_id, store_id, sop_id, sop_name, assignee,
                           assigned_by, event_id, note, status, due_at,
                           created_at, updated_at
                    FROM sop_assignments
                    WHERE {' AND '.join(clauses)}
                    ORDER BY created_at DESC
                    LIMIT ?
                """
                params.append(limit)
                rows = conn.execute(sql, tuple(params)).fetchall()
                return [dict(r) for r in rows]
            finally:
                conn.close()


def sop_assign_store(db: Any) -> SopAssignStore:
    return SopAssignStore(db)
