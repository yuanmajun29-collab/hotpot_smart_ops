#!/usr/bin/env python3
"""SQLite → PostgreSQL 多租户迁移脚本.

功能:
  1. 导出 SQLite 数据为 JSON
  2. 创建 PostgreSQL 多租户表结构 (tenant_id 列隔离)
  3. 导入数据到 PostgreSQL

多租户策略: column-based isolation (tenant_id column)
  - 所有门店数据存同一组表
  - 每行记录带 tenant_id (= store_id)
  - 查询时 WHERE tenant_id = $1 隔离
  - 索引: (tenant_id, created_at) 复合索引

数据库 URL: $HOTPOT_DATABASE_URL 环境变量
  格式: postgresql://user:pass@host:5432/hotpot_smart_ops

用法:
  # 仅导出
  python3 scripts/migrate_sqlite_to_pg.py --export --sqlite demo/data/hub.db

  # 完整迁移 (导出 → 建表 → 导入)
  python3 scripts/migrate_sqlite_to_pg.py --migrate --sqlite demo/data/hub.db

  # 仅建表 (已有 PostgreSQL)
  python3 scripts/migrate_sqlite_to_pg.py --init-schema

  # 试运行 (不实际写入)
  python3 scripts/migrate_sqlite_to_pg.py --migrate --dry-run --sqlite demo/data/hub.db
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# ── Constants ────────────────────────────────────────────────────
BATCH_SIZE = 500
MAX_EVENTS_PER_STORE = 2000


def get_pg_connection():
    """Get psycopg2 connection from HOTPOT_DATABASE_URL."""
    url = os.environ.get("HOTPOT_DATABASE_URL", "")
    if not url:
        print("ERROR: HOTPOT_DATABASE_URL not set", file=sys.stderr)
        print("Example: postgresql://user:pass@localhost:5432/hotpot_smart_ops", file=sys.stderr)
        sys.exit(1)

    try:
        import psycopg2
        import psycopg2.extras
    except ImportError:
        print("ERROR: psycopg2-binary required. pip install psycopg2-binary", file=sys.stderr)
        sys.exit(1)

    conn = psycopg2.connect(url)
    conn.autocommit = False
    return conn


def get_sqlite_connection(db_path: str):
    """Get sqlite3 connection."""
    import sqlite3

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


# ── Export ────────────────────────────────────────────────────────


def export_sqlite(db_path: str) -> Dict[str, Any]:
    """Export all SQLite data as a JSON-serializable dict."""
    print(f"[Export] Reading SQLite: {db_path}")
    conn = get_sqlite_connection(db_path)

    data: Dict[str, Any] = {
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "source": db_path,
        "events": [],
        "snapshots": [],
        "devices": [],
        "receiving": [],
        "sop_assignments": [],
        "iot_readings": [],
        "daily_reports": [],
        "tasks": [],
        "org_stores": [],
    }

    tables_to_export = {
        "events": "events",
        "store_snapshots": "snapshots",
        "device_registry": "devices",
        "receiving_records": "receiving",
        "sop_assignments": "sop_assignments",
        "iot_readings": "iot_readings",
        "daily_reports": "daily_reports",
        "tasks": "tasks",
    }

    for db_table, key in tables_to_export.items():
        try:
            cursor = conn.execute(f"SELECT * FROM {db_table}")
            rows = cursor.fetchall()
            data[key] = [dict(row) for row in rows]
            print(f"  [Export] {db_table}: {len(rows)} rows")
        except Exception as e:
            print(f"  [Export] {db_table}: SKIP ({e})")

    # Org stores
    try:
        cursor = conn.execute("SELECT * FROM stores")
        data["org_stores"] = [dict(row) for row in cursor.fetchall()]
        print(f"  [Export] stores: {len(data['org_stores'])} rows")
    except Exception:
        pass

    # Waste timeseries
    try:
        cursor = conn.execute("SELECT * FROM waste_timeseries")
        rows = cursor.fetchall()
        data["waste_timeseries"] = [dict(row) for row in rows]
        print(f"  [Export] waste_timeseries: {len(rows)} rows")
    except Exception:
        pass

    # Waste alerts
    try:
        cursor = conn.execute("SELECT * FROM waste_alerts")
        rows = cursor.fetchall()
        data["waste_alerts"] = [dict(row) for row in rows]
        print(f"  [Export] waste_alerts: {len(rows)} rows")
    except Exception:
        pass

    conn.close()
    return data


# ── Multi-tenant Schema ──────────────────────────────────────────

MULTI_TENANT_SCHEMA_SQL = """
-- ============================================================
-- Hotpot Smart Ops — PostgreSQL Multi‑Tenant Schema
-- Strategy: column-based isolation (tenant_id column)
-- ============================================================

CREATE TABLE IF NOT EXISTS events (
    event_id TEXT NOT NULL,
    tenant_id TEXT NOT NULL,  -- store_id for multi-tenant isolation
    level TEXT,
    source TEXT,
    event_type TEXT DEFAULT '',
    message TEXT DEFAULT '',
    payload JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (event_id, tenant_id)
);
CREATE INDEX IF NOT EXISTS idx_events_tenant_ts
    ON events(tenant_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_events_tenant_type
    ON events(tenant_id, event_type) WHERE event_type IS NOT NULL AND event_type != '';

CREATE TABLE IF NOT EXISTS store_snapshots (
    tenant_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    payload JSONB NOT NULL DEFAULT '{}',
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (tenant_id, kind)
);

CREATE TABLE IF NOT EXISTS device_registry (
    device_id TEXT NOT NULL,
    tenant_id TEXT NOT NULL,
    payload JSONB NOT NULL DEFAULT '{}',
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (device_id, tenant_id)
);
CREATE INDEX IF NOT EXISTS idx_devices_tenant ON device_registry(tenant_id);

CREATE TABLE IF NOT EXISTS receiving_records (
    id SERIAL,
    tenant_id TEXT NOT NULL,
    batch_id TEXT,
    sku TEXT,
    quantity REAL,
    unit TEXT DEFAULT '',
    supplier TEXT DEFAULT '',
    received_at TIMESTAMPTZ,
    payload JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (id, tenant_id)
);
CREATE INDEX IF NOT EXISTS idx_receiving_tenant ON receiving_records(tenant_id, received_at DESC);

CREATE TABLE IF NOT EXISTS sop_assignments (
    id SERIAL,
    tenant_id TEXT NOT NULL,
    task_id TEXT,
    assignee TEXT,
    zone TEXT,
    status TEXT DEFAULT 'pending',
    deadline TIMESTAMPTZ,
    payload JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (id, tenant_id)
);
CREATE INDEX IF NOT EXISTS idx_sop_tenant ON sop_assignments(tenant_id, status);

CREATE TABLE IF NOT EXISTS iot_readings (
    id SERIAL,
    tenant_id TEXT NOT NULL,
    device_id TEXT,
    metric TEXT,
    value REAL,
    unit TEXT DEFAULT '',
    recorded_at TIMESTAMPTZ DEFAULT NOW(),
    payload JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (id, tenant_id)
);
CREATE INDEX IF NOT EXISTS idx_iot_tenant_ts ON iot_readings(tenant_id, recorded_at DESC);

CREATE TABLE IF NOT EXISTS daily_reports (
    id SERIAL,
    tenant_id TEXT NOT NULL,
    report_date DATE NOT NULL,
    report_type TEXT DEFAULT 'daily',
    payload JSONB NOT NULL DEFAULT '{}',
    generated_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (id, tenant_id)
);
CREATE INDEX IF NOT EXISTS idx_daily_tenant_date ON daily_reports(tenant_id, report_date DESC);

CREATE TABLE IF NOT EXISTS tasks (
    id SERIAL,
    tenant_id TEXT NOT NULL,
    task_type TEXT,
    status TEXT DEFAULT 'pending',
    priority TEXT DEFAULT 'normal',
    payload JSONB DEFAULT '{}',
    due_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (id, tenant_id)
);
CREATE INDEX IF NOT EXISTS idx_tasks_tenant_status ON tasks(tenant_id, status);

CREATE TABLE IF NOT EXISTS org_stores (
    store_id TEXT NOT NULL,
    tenant_id TEXT NOT NULL,
    name TEXT DEFAULT '',
    region TEXT DEFAULT '',
    zone TEXT DEFAULT '',
    payload JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (store_id, tenant_id)
);

CREATE TABLE IF NOT EXISTS waste_timeseries (
    id SERIAL,
    tenant_id TEXT NOT NULL,
    date DATE NOT NULL,
    total_count INTEGER DEFAULT 0,
    event_count INTEGER DEFAULT 0,
    items JSONB DEFAULT '[]',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (id, tenant_id),
    UNIQUE (tenant_id, date)
);
CREATE INDEX IF NOT EXISTS idx_waste_ts_tenant ON waste_timeseries(tenant_id, date DESC);

CREATE TABLE IF NOT EXISTS waste_alerts (
    id SERIAL,
    tenant_id TEXT NOT NULL,
    date DATE NOT NULL,
    alert_type TEXT DEFAULT 'spike',
    severity TEXT DEFAULT 'warning',
    message TEXT DEFAULT '',
    acked BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (id, tenant_id)
);
CREATE INDEX IF NOT EXISTS idx_waste_alerts_tenant ON waste_alerts(tenant_id, created_at DESC);
"""


def init_pg_schema(conn) -> None:
    """Create multi-tenant schema in PostgreSQL."""
    print("[Schema] Creating multi-tenant tables...")
    with conn.cursor() as cur:
        cur.execute(MULTI_TENANT_SCHEMA_SQL)
    conn.commit()
    print("[Schema] Done.")


# ── Import ───────────────────────────────────────────────────────


def get_tenant_id(row: Dict[str, Any]) -> str:
    """Extract tenant_id from a row, trying multiple column names."""
    for col in ("tenant_id", "store_id", "store"):
        if col in row and row[col]:
            return row[col]
    return "unknown"


def import_data(conn, data: Dict[str, Any], dry_run: bool = False) -> None:
    """Import exported JSON data into PostgreSQL."""
    import psycopg2.extras

    table_map = {
        "events": {
            "columns": ["event_id", "tenant_id", "level", "source", "payload", "created_at"],
            "conflict": "ON CONFLICT (event_id, tenant_id) DO UPDATE SET payload=EXCLUDED.payload, level=EXCLUDED.level, source=EXCLUDED.source",
        },
        "snapshots": {
            "columns": ["tenant_id", "kind", "payload", "updated_at"],
            "conflict": "ON CONFLICT (tenant_id, kind) DO UPDATE SET payload=EXCLUDED.payload, updated_at=EXCLUDED.updated_at",
        },
        "devices": {
            "columns": ["device_id", "tenant_id", "payload", "updated_at"],
            "conflict": "ON CONFLICT (device_id, tenant_id) DO UPDATE SET payload=EXCLUDED.payload, updated_at=EXCLUDED.updated_at",
        },
    }

    for key, config in table_map.items():
        rows = data.get(key, [])
        if not rows:
            continue

        pg_table = {"events": "events", "snapshots": "store_snapshots", "devices": "device_registry"}[key]
        columns = config["columns"]
        conflict = config["conflict"]

        print(f"  [Import] {pg_table}: {len(rows)} rows" + (" (DRY RUN)" if dry_run else ""))

        if dry_run:
            continue

        with conn.cursor() as cur:
            sql = f"INSERT INTO {pg_table} ({', '.join(columns)}) VALUES %s {conflict}"
            values = []
            for row in rows:
                tenant = get_tenant_id(row)
                payload = row.get("payload")
                if isinstance(payload, dict):
                    payload = json.dumps(payload, ensure_ascii=False)
                elif isinstance(payload, str):
                    pass
                else:
                    payload = json.dumps(dict(row), ensure_ascii=False, default=str)

                ts = row.get("created_at") or row.get("updated_at") or row.get("timestamp") or datetime.now(timezone.utc).isoformat()

                if pg_table == "events":
                    values.append((
                        row.get("event_id", ""),
                        tenant,
                        row.get("level"),
                        row.get("source"),
                        payload,
                        ts,
                    ))
                elif pg_table == "store_snapshots":
                    values.append((
                        tenant,
                        row.get("kind", ""),
                        payload,
                        ts,
                    ))
                elif pg_table == "device_registry":
                    values.append((
                        row.get("device_id", ""),
                        tenant,
                        payload,
                        ts,
                    ))

            if values:
                psycopg2.extras.execute_values(cur, sql, values, page_size=BATCH_SIZE)

        conn.commit()

    # Import org stores
    org_rows = data.get("org_stores", [])
    if org_rows:
        print(f"  [Import] org_stores: {len(org_rows)} rows" + (" (DRY RUN)" if dry_run else ""))
        if not dry_run:
            with conn.cursor() as cur:
                for row in org_rows:
                    tenant = get_tenant_id(row)
                    sid = row.get("store_id") or row.get("id") or tenant
                    cur.execute(
                        """INSERT INTO org_stores (store_id, tenant_id, name, region, zone, payload)
                           VALUES (%s, %s, %s, %s, %s, %s::jsonb)
                           ON CONFLICT (store_id, tenant_id) DO UPDATE SET
                             name=EXCLUDED.name, region=EXCLUDED.region, zone=EXCLUDED.zone, payload=EXCLUDED.payload""",
                        (
                            sid,
                            tenant,
                            row.get("name", sid),
                            row.get("region", ""),
                            row.get("zone", ""),
                            json.dumps(dict(row), ensure_ascii=False, default=str),
                        ),
                    )
            conn.commit()


# ── CLI ──────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(
        description="SQLite → PostgreSQL multi-tenant migration"
    )
    parser.add_argument("--sqlite", default="hotpot_platform/demo/data/hub.db", help="SQLite DB path")
    parser.add_argument("--export", action="store_true", help="Export SQLite to JSON")
    parser.add_argument("--export-file", default="migration_export.json", help="Export output file")
    parser.add_argument("--init-schema", action="store_true", help="Create PG multi-tenant schema only")
    parser.add_argument("--migrate", action="store_true", help="Full migration: export → schema → import")
    parser.add_argument("--import-file", default="migration_export.json", help="Import from JSON file")
    parser.add_argument("--dry-run", action="store_true", help="Dry run (no writes to PG)")
    args = parser.parse_args()

    if args.export:
        data = export_sqlite(args.sqlite)
        with open(args.export_file, "w") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"[Export] Written to {args.export_file}")
        return

    if args.init_schema:
        conn = get_pg_connection()
        try:
            init_pg_schema(conn)
        finally:
            conn.close()
        return

    if args.migrate:
        # Step 1: Export
        print("=" * 60)
        print("Step 1/3: Exporting SQLite data")
        print("=" * 60)
        data = export_sqlite(args.sqlite)
        with open(args.export_file, "w") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        # Step 2: Schema
        print()
        print("=" * 60)
        print("Step 2/3: Creating PostgreSQL schema")
        print("=" * 60)
        if not args.dry_run:
            conn = get_pg_connection()
            try:
                init_pg_schema(conn)
            finally:
                conn.close()

        # Step 3: Import
        print()
        print("=" * 60)
        print("Step 3/3: Importing data to PostgreSQL")
        print("=" * 60)
        if not args.dry_run:
            conn = get_pg_connection()
            try:
                import_data(conn, data, dry_run=False)
            finally:
                conn.close()

        print()
        print("=" * 60)
        print("✅ Migration complete!")
        print(f"   Source: {args.sqlite}")
        print(f"   Target: {os.environ.get('HOTPOT_DATABASE_URL', 'N/A')}")
        print(f"   Export: {args.export_file}")
        print("=" * 60)
        return

    parser.print_help()


if __name__ == "__main__":
    main()
