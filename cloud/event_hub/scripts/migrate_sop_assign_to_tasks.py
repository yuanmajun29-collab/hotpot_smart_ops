#!/usr/bin/env python3
"""Migrate sop_assignments -> tasks / task_events  (DEV-520, ADR-010).

Generalizes the legacy SOP-only assignment store into the unified task engine.

Design refs:
  - docs/task_supervision_engine_design.md  §4 (state machine) / §7 (data model & migration)
  - docs/architecture_decisions.md          ADR-010

Hard requirements implemented here (per Codex review + merge V1.2):
  1. Idempotent   : re-runnable; keyed on legacy assignment_id -> tasks.source_id (UNIQUE),
                    UPSERT so re-runs never duplicate.
  2. Unique source: tasks.source_id UNIQUE index guarantees 1:1 mapping.
  3. Count check  : asserts count + per-status distribution before/after; rolls back on mismatch.
  4. Compat       : does NOT drop sop_assignments; the table stays for the API adapter layer
                    and the return-layer `sop_assignments` compatibility view.
  5. Missing assignee backfill: the real table has assignee NOT NULL, so this is only a
                    safety net for blank/whitespace values -> role queue + needs_triage.

Status mapping (legacy -> task main state, 5-state model):
    open -> pending ,  done -> submitted ,  verified -> closed

Field mapping:
    assignment_id -> source_id (idempotency key)      assignee   -> assignee_id
    assigned_by   -> created_by                        sop_id     -> ref_id (+ ref_type='sop')
    event_id      -> ref_id (preferred when present)   sop_name   -> title
    note          -> detail                            created_at/updated_at -> preserved

Usage:
    python migrate_sop_assign_to_tasks.py --db /path/to/hub.db [--dry-run] [--verbose]
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
import uuid
from datetime import datetime, timezone

# ---- mapping tables --------------------------------------------------------

STATUS_MAP = {"open": "pending", "done": "submitted", "verified": "closed"}

# legacy status -> resulting task status, used for the post-migration count assertion
EXPECTED_TARGET_STATUS = dict(STATUS_MAP)

KITCHEN_HINTS = ("kitchen", "后厨", "chef", "厨", "sop")  # -> backfill chef on blank assignee


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


# ---- target schema (idempotent) -------------------------------------------

TASKS_SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (
    task_id         TEXT PRIMARY KEY,
    source_id       TEXT UNIQUE,
    store_id        TEXT NOT NULL,
    task_type       TEXT NOT NULL,
    priority        TEXT NOT NULL DEFAULT 'P1',
    status          TEXT NOT NULL DEFAULT 'pending',
    source          TEXT NOT NULL DEFAULT 'migrated',
    ref_type        TEXT,
    ref_id          TEXT,
    assignee_id     TEXT,
    assignee_status TEXT NOT NULL DEFAULT 'assigned',
    assignee_group  TEXT,
    created_by      TEXT,
    sla_policy      TEXT NOT NULL DEFAULT 'keep_original_due_at',
    title           TEXT,
    detail          TEXT DEFAULT '',
    due_at          TEXT,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_tasks_source ON tasks(source_id);
CREATE INDEX IF NOT EXISTS idx_tasks_store  ON tasks(store_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(store_id, status);
CREATE INDEX IF NOT EXISTS idx_tasks_triage ON tasks(store_id, assignee_status);

CREATE TABLE IF NOT EXISTS task_events (
    event_id      TEXT PRIMARY KEY,
    task_id       TEXT NOT NULL,
    event_type    TEXT NOT NULL,
    actor_id      TEXT,
    from_status   TEXT,
    to_status     TEXT,
    from_assignee TEXT,
    to_assignee   TEXT,
    sla_policy    TEXT,
    old_due_at    TEXT,
    note          TEXT DEFAULT '',
    ts            TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_task_events_task ON task_events(task_id, ts);
"""


def task_id_for(source_id: str) -> str:
    """Deterministic task_id derived from the legacy assignment_id (stable across re-runs)."""
    return f"T-{source_id}"


def backfill_assignee(assignee: str, sop_id: str, sop_name: str):
    """Return (assignee_id, assignee_status). Real schema has assignee NOT NULL, so this only
    rescues blank/whitespace values; never silently injects a random user."""
    if assignee and assignee.strip():
        return assignee.strip(), "assigned"
    ctx = f"{sop_id} {sop_name}".lower()
    role = "chef" if any(h in ctx for h in KITCHEN_HINTS) else "store_manager"
    return role, "needs_triage"


# ---- core ------------------------------------------------------------------

def fetch_legacy(conn: sqlite3.Connection):
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute("SELECT * FROM sop_assignments").fetchall()
    except sqlite3.OperationalError:
        return []  # table absent -> nothing to migrate
    return rows


def migrate(conn: sqlite3.Connection, *, dry_run: bool, verbose: bool) -> int:
    conn.executescript(TASKS_SCHEMA)

    legacy = fetch_legacy(conn)
    src_total = len(legacy)
    src_dist: dict[str, int] = {}
    for r in legacy:
        src_dist[r["status"]] = src_dist.get(r["status"], 0) + 1

    if verbose:
        print(f"[scan] sop_assignments rows = {src_total}  dist = {src_dist}")

    migrated = triaged = 0
    for r in legacy:
        legacy_status = r["status"]
        if legacy_status not in STATUS_MAP:
            print(f"[warn] unknown legacy status '{legacy_status}' "
                  f"(assignment_id={r['assignment_id']}) -> skipped", file=sys.stderr)
            continue

        source_id = r["assignment_id"]
        assignee_id, assignee_status = backfill_assignee(
            r["assignee"], r["sop_id"] or "", r["sop_name"] or "")
        if assignee_status == "needs_triage":
            triaged += 1

        ref_id = r["event_id"] or r["sop_id"]  # prefer the OpsEvent id when present
        row = {
            "task_id": task_id_for(source_id),
            "source_id": source_id,
            "store_id": r["store_id"],
            "task_type": "sop_violation",
            "priority": "P1",
            "status": STATUS_MAP[legacy_status],
            "source": "migrated",
            "ref_type": "ops_event" if r["event_id"] else "sop",
            "ref_id": ref_id,
            "assignee_id": assignee_id,
            "assignee_status": assignee_status,
            "assignee_group": "kitchen",
            "created_by": r["assigned_by"] or "",
            "sla_policy": "keep_original_due_at",
            "title": r["sop_name"] or r["sop_id"],
            "detail": r["note"] or "",
            "due_at": r["due_at"],
            "created_at": r["created_at"],   # preserve, never overwrite with migration time
            "updated_at": r["updated_at"],
        }

        if not dry_run:
            # UPSERT on source_id -> idempotent; re-runs refresh, never duplicate.
            conn.execute(
                """
                INSERT INTO tasks (task_id, source_id, store_id, task_type, priority, status,
                    source, ref_type, ref_id, assignee_id, assignee_status, assignee_group,
                    created_by, sla_policy, title, detail, due_at, created_at, updated_at)
                VALUES (:task_id, :source_id, :store_id, :task_type, :priority, :status,
                    :source, :ref_type, :ref_id, :assignee_id, :assignee_status, :assignee_group,
                    :created_by, :sla_policy, :title, :detail, :due_at, :created_at, :updated_at)
                ON CONFLICT(source_id) DO UPDATE SET
                    status=excluded.status, assignee_id=excluded.assignee_id,
                    assignee_status=excluded.assignee_status, detail=excluded.detail,
                    due_at=excluded.due_at, updated_at=excluded.updated_at
                """,
                row,
            )
            conn.execute(
                """
                INSERT INTO task_events (event_id, task_id, event_type, actor_id,
                    from_status, to_status, note, ts)
                VALUES (?, ?, 'migrate', 'system', NULL, ?, ?, ?)
                """,
                (uuid.uuid4().hex, row["task_id"], row["status"],
                 f"migrated from sop_assignments status={legacy_status}", utc_now_iso()),
            )
        migrated += 1
        if verbose:
            print(f"  [ok] {source_id} -> {row['task_id']} "
                  f"({legacy_status}->{row['status']}, assignee_status={assignee_status})")

    # ---- count + distribution assertion ----------------------------------
    if not dry_run:
        tgt_total = conn.execute(
            "SELECT COUNT(*) FROM tasks WHERE task_type='sop_violation'").fetchone()[0]
        expected = {EXPECTED_TARGET_STATUS[s]: c for s, c in src_dist.items()
                    if s in EXPECTED_TARGET_STATUS}
        tgt_dist = {}
        for st, c in conn.execute(
            "SELECT status, COUNT(*) FROM tasks WHERE task_type='sop_violation' GROUP BY status"
        ).fetchall():
            tgt_dist[st] = c

        ok_total = tgt_total == migrated
        ok_dist = all(tgt_dist.get(k, 0) >= v for k, v in expected.items())
        if not (ok_total and ok_dist):
            conn.rollback()
            print(f"[FAIL] count/dist mismatch: migrated={migrated} tasks={tgt_total} "
                  f"expected_dist={expected} got={tgt_dist} -> ROLLED BACK", file=sys.stderr)
            return 2
        conn.commit()
        print(f"[done] migrated={migrated} (triaged={triaged}) tasks_total={tgt_total} "
              f"dist={tgt_dist}  [count+dist OK]")
    else:
        print(f"[dry-run] would migrate {migrated} rows (triaged={triaged}); no writes")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Migrate sop_assignments -> tasks/task_events")
    ap.add_argument("--db", required=True, help="path to the hub SQLite database")
    ap.add_argument("--dry-run", action="store_true", help="scan + validate, write nothing")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    conn = sqlite3.connect(args.db)
    try:
        return migrate(conn, dry_run=args.dry_run, verbose=args.verbose)
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
