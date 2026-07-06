"""IoT time-series readings persistence (DEV-412 stub / BL-02)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

SQLITE_IOT_READINGS_SCHEMA = """
CREATE TABLE IF NOT EXISTS iot_readings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    store_id TEXT NOT NULL,
    sensor_id TEXT NOT NULL,
    sensor_type TEXT NOT NULL,
    value REAL,
    unit TEXT DEFAULT '',
    recorded_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_iot_readings_store_sensor
    ON iot_readings(store_id, sensor_id, recorded_at DESC);
"""

PG_IOT_READINGS_SCHEMA = """
CREATE TABLE IF NOT EXISTS iot_readings (
    id SERIAL PRIMARY KEY,
    store_id TEXT NOT NULL,
    sensor_id TEXT NOT NULL,
    sensor_type TEXT NOT NULL,
    value DOUBLE PRECISION,
    unit TEXT DEFAULT '',
    recorded_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_iot_readings_store_sensor
    ON iot_readings(store_id, sensor_id, recorded_at DESC);
"""


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


class IotReadingsStore:
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

    def insert(
        self,
        store_id: str,
        sensor_id: str,
        sensor_type: str,
        value: float,
        unit: str = "",
        recorded_at: Optional[str] = None,
    ) -> None:
        ts = recorded_at or utc_now_iso()
        with self._lock:
            conn = self._connect()
            try:
                if self.is_pg:
                    with conn.cursor() as cur:
                        cur.execute(
                            """
                            INSERT INTO iot_readings(store_id, sensor_id, sensor_type, value, unit, recorded_at)
                            VALUES (%s,%s,%s,%s,%s,%s)
                            """,
                            (store_id, sensor_id, sensor_type, value, unit, ts),
                        )
                    conn.commit()
                else:
                    conn.execute(
                        """
                        INSERT INTO iot_readings(store_id, sensor_id, sensor_type, value, unit, recorded_at)
                        VALUES (?,?,?,?,?,?)
                        """,
                        (store_id, sensor_id, sensor_type, value, unit, ts),
                    )
                    conn.commit()
            finally:
                conn.close()

    def insert_batch(self, store_id: str, readings: List[Dict[str, Any]]) -> int:
        n = 0
        for r in readings:
            self.insert(
                store_id,
                r["sensor_id"],
                r.get("sensor_type", r.get("type", "unknown")),
                float(r["value"]),
                r.get("unit", ""),
                r.get("recorded_at"),
            )
            n += 1
        return n

    def list_readings(
        self,
        store_id: str,
        *,
        sensor_id: Optional[str] = None,
        hours: float = 24,
        limit: int = 500,
    ) -> List[Dict[str, Any]]:
        since = (datetime.now(timezone.utc) - timedelta(hours=hours)).replace(microsecond=0).isoformat()
        with self._lock:
            conn = self._connect()
            try:
                if self.is_pg:
                    clauses = ["store_id = %s", "recorded_at >= %s"]
                    params: List[Any] = [store_id, since]
                    if sensor_id:
                        clauses.append("sensor_id = %s")
                        params.append(sensor_id)
                    sql = f"""
                        SELECT sensor_id, sensor_type, value, unit, recorded_at
                        FROM iot_readings
                        WHERE {' AND '.join(clauses)}
                        ORDER BY recorded_at ASC
                        LIMIT %s
                    """
                    params.append(limit)
                    with conn.cursor() as cur:
                        cur.execute(sql, tuple(params))
                        cols = ["sensor_id", "sensor_type", "value", "unit", "recorded_at"]
                        return [dict(zip(cols, row)) for row in cur.fetchall()]

                clauses = ["store_id = ?", "recorded_at >= ?"]
                params = [store_id, since]
                if sensor_id:
                    clauses.append("sensor_id = ?")
                    params.append(sensor_id)
                sql = f"""
                    SELECT sensor_id, sensor_type, value, unit, recorded_at
                    FROM iot_readings
                    WHERE {' AND '.join(clauses)}
                    ORDER BY recorded_at ASC
                    LIMIT ?
                """
                params.append(limit)
                rows = conn.execute(sql, tuple(params)).fetchall()
                return [dict(r) for r in rows]
            finally:
                conn.close()


def iot_readings_store(db: Any) -> IotReadingsStore:
    return IotReadingsStore(db)
