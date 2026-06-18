"""Daily report persistence (DEV-423 / BL-06)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

SQLITE_DAILY_REPORTS_SCHEMA = """
CREATE TABLE IF NOT EXISTS daily_reports (
    report_id TEXT PRIMARY KEY,
    store_id TEXT NOT NULL,
    report_date TEXT NOT NULL,
    markdown TEXT NOT NULL,
    summary_json TEXT,
    pushed INTEGER DEFAULT 0,
    created_at TEXT NOT NULL,
    UNIQUE(store_id, report_date)
);
CREATE INDEX IF NOT EXISTS idx_daily_reports_store ON daily_reports(store_id, report_date DESC);
"""

PG_DAILY_REPORTS_SCHEMA = """
CREATE TABLE IF NOT EXISTS daily_reports (
    report_id TEXT PRIMARY KEY,
    store_id TEXT NOT NULL,
    report_date TEXT NOT NULL,
    markdown TEXT NOT NULL,
    summary_json JSONB,
    pushed BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL,
    UNIQUE(store_id, report_date)
);
CREATE INDEX IF NOT EXISTS idx_daily_reports_store ON daily_reports(store_id, report_date DESC);
"""


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def report_id_for(store_id: str, report_date: str) -> str:
    return f"RPT-{report_date.replace('-', '')}-{store_id.replace('store_', '')}"


class DailyReportStore:
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

    def get_by_date(self, store_id: str, report_date: str) -> Optional[Dict[str, Any]]:
        rows = self.list_reports(store_id, limit=1, report_date=report_date)
        return rows[0] if rows else None

    def save(
        self,
        store_id: str,
        report_date: str,
        markdown: str,
        summary_json: str = "",
        *,
        pushed: bool = False,
    ) -> Dict[str, Any]:
        rid = report_id_for(store_id, report_date)
        now = utc_now_iso()
        with self._lock:
            conn = self._connect()
            try:
                if self.is_pg:
                    with conn.cursor() as cur:
                        cur.execute(
                            """
                            INSERT INTO daily_reports(
                                report_id, store_id, report_date, markdown,
                                summary_json, pushed, created_at
                            ) VALUES (%s,%s,%s,%s,%s::jsonb,%s,%s)
                            ON CONFLICT (store_id, report_date) DO UPDATE SET
                                markdown = EXCLUDED.markdown,
                                summary_json = EXCLUDED.summary_json,
                                pushed = EXCLUDED.pushed,
                                created_at = EXCLUDED.created_at
                            """,
                            (
                                rid,
                                store_id,
                                report_date,
                                markdown,
                                summary_json or "{}",
                                pushed,
                                now,
                            ),
                        )
                    conn.commit()
                else:
                    conn.execute(
                        """
                        INSERT INTO daily_reports(
                            report_id, store_id, report_date, markdown,
                            summary_json, pushed, created_at
                        ) VALUES (?,?,?,?,?,?,?)
                        ON CONFLICT(store_id, report_date) DO UPDATE SET
                            markdown = excluded.markdown,
                            summary_json = excluded.summary_json,
                            pushed = excluded.pushed,
                            created_at = excluded.created_at
                        """,
                        (
                            rid,
                            store_id,
                            report_date,
                            markdown,
                            summary_json or "{}",
                            1 if pushed else 0,
                            now,
                        ),
                    )
                    conn.commit()
            finally:
                conn.close()
        return {
            "report_id": rid,
            "store_id": store_id,
            "report_date": report_date,
            "pushed": pushed,
            "created_at": now,
        }

    def mark_pushed(self, store_id: str, report_date: str) -> None:
        with self._lock:
            conn = self._connect()
            try:
                if self.is_pg:
                    with conn.cursor() as cur:
                        cur.execute(
                            "UPDATE daily_reports SET pushed = TRUE WHERE store_id = %s AND report_date = %s",
                            (store_id, report_date),
                        )
                    conn.commit()
                else:
                    conn.execute(
                        "UPDATE daily_reports SET pushed = 1 WHERE store_id = ? AND report_date = ?",
                        (store_id, report_date),
                    )
                    conn.commit()
            finally:
                conn.close()

    def list_reports(
        self,
        store_id: str,
        *,
        limit: int = 30,
        report_date: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        with self._lock:
            conn = self._connect()
            try:
                if self.is_pg:
                    if report_date:
                        sql = """
                            SELECT report_id, store_id, report_date, markdown, pushed, created_at
                            FROM daily_reports WHERE store_id = %s AND report_date = %s
                        """
                        params = (store_id, report_date)
                    else:
                        sql = """
                            SELECT report_id, store_id, report_date, markdown, pushed, created_at
                            FROM daily_reports WHERE store_id = %s
                            ORDER BY report_date DESC LIMIT %s
                        """
                        params = (store_id, limit)
                    with conn.cursor() as cur:
                        cur.execute(sql, params)
                        cols = ["report_id", "store_id", "report_date", "markdown", "pushed", "created_at"]
                        return [dict(zip(cols, row)) for row in cur.fetchall()]

                if report_date:
                    rows = conn.execute(
                        """
                        SELECT report_id, store_id, report_date, markdown, pushed, created_at
                        FROM daily_reports WHERE store_id = ? AND report_date = ?
                        """,
                        (store_id, report_date),
                    ).fetchall()
                else:
                    rows = conn.execute(
                        """
                        SELECT report_id, store_id, report_date, markdown, pushed, created_at
                        FROM daily_reports WHERE store_id = ?
                        ORDER BY report_date DESC LIMIT ?
                        """,
                        (store_id, limit),
                    ).fetchall()
                return [dict(r) for r in rows]
            finally:
                conn.close()


def daily_report_store(db: Any) -> DailyReportStore:
    return DailyReportStore(db)
