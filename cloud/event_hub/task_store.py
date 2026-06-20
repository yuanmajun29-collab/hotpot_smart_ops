"""Unified task-supervision engine (DEV-521 / ADR-010).

Generalizes SopAssignStore into a tenant-scoped task/工单 store with a 5-state
machine and an append-only `task_events` audit trail. overdue/escalated are
read-time derived flags, never written. Mirrors the pg+sqlite dual-backend
pattern used by sop_assign_store.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

# ---- state machine (authoritative) -----------------------------------------

MAIN_STATES = frozenset({"pending", "in_progress", "submitted", "closed", "cancelled"})
TERMINAL_STATES = frozenset({"closed", "cancelled"})

# action -> (allowed_from_states, to_status | None when status is unchanged)
TRANSITIONS: Dict[str, Tuple[frozenset, Optional[str]]] = {
    "start":    (frozenset({"pending"}), "in_progress"),
    "submit":   (frozenset({"pending", "in_progress"}), "submitted"),
    "verify":   (frozenset({"submitted"}), "closed"),
    "reject":   (frozenset({"submitted"}), "pending"),
    "reopen":   (frozenset({"submitted", "closed"}), "pending"),
    "cancel":   (frozenset({"pending", "in_progress", "submitted"}), "cancelled"),
    # status-preserving events
    "accept":   (frozenset({"pending", "in_progress"}), None),
    "assign":   (frozenset({"pending", "in_progress"}), None),
    "reassign": (frozenset({"pending", "in_progress"}), None),
    "comment":  (frozenset(MAIN_STATES - TERMINAL_STATES), None),
}

SLA_POLICIES = frozenset({"reset_from_reassign", "keep_original_due_at"})
PRIORITY_DEFAULT = "P1"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def new_task_id(store_id: str) -> str:
    day = datetime.now(timezone.utc).strftime("%Y%m%d")
    short = uuid.uuid4().hex[:6].upper()
    suffix = store_id.replace("store_", "")[:8]
    return f"T-{suffix}-{day}-{short}"


SQLITE_TASKS_SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (
    task_id TEXT PRIMARY KEY,
    source_id TEXT UNIQUE,
    store_id TEXT NOT NULL,
    task_type TEXT NOT NULL,
    priority TEXT NOT NULL DEFAULT 'P1',
    status TEXT NOT NULL DEFAULT 'pending',
    source TEXT NOT NULL DEFAULT 'manual',
    ref_type TEXT,
    ref_id TEXT,
    assignee_id TEXT,
    assignee_status TEXT NOT NULL DEFAULT 'assigned',
    assignee_group TEXT,
    created_by TEXT,
    sla_policy TEXT NOT NULL DEFAULT 'keep_original_due_at',
    title TEXT,
    detail TEXT DEFAULT '',
    due_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_tasks_store ON tasks(store_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(store_id, status);
CREATE TABLE IF NOT EXISTS task_events (
    event_id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    actor_id TEXT,
    from_status TEXT,
    to_status TEXT,
    from_assignee TEXT,
    to_assignee TEXT,
    sla_policy TEXT,
    old_due_at TEXT,
    note TEXT DEFAULT '',
    ts TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_task_events_task ON task_events(task_id, ts);
"""

PG_TASKS_SCHEMA = SQLITE_TASKS_SCHEMA.replace("due_at TEXT", "due_at TIMESTAMPTZ")

_TASK_COLS = (
    "task_id, source_id, store_id, task_type, priority, status, source, ref_type, ref_id, "
    "assignee_id, assignee_status, assignee_group, created_by, sla_policy, title, detail, "
    "due_at, created_at, updated_at"
)


class TaskError(ValueError):
    """Invalid state transition or task operation."""


class TaskStore:
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

    def _ph(self) -> str:
        return "%s" if self.is_pg else "?"

    def _exec(self, conn, sql: str, params: Tuple = (), fetch: str = "none"):
        """Run a statement on either backend. fetch in {none, one, all}."""
        sql_b = sql.replace("?", "%s") if self.is_pg else sql
        if self.is_pg:
            cur = conn.cursor()
            cur.execute(sql_b, params)
            if fetch == "one":
                row = cur.fetchone()
                cols = [c.name for c in cur.description] if cur.description else []
                return dict(zip(cols, row)) if row else None
            if fetch == "all":
                rows = cur.fetchall()
                cols = [c.name for c in cur.description] if cur.description else []
                return [dict(zip(cols, r)) for r in rows]
            return None
        cur = conn.execute(sql_b, params)
        if fetch == "one":
            row = cur.fetchone()
            return dict(row) if row else None
        if fetch == "all":
            return [dict(r) for r in cur.fetchall()]
        return None

    # ---- derived flags -----------------------------------------------------

    @staticmethod
    def _decorate(row: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        if not row:
            return row
        due = row.get("due_at")
        overdue = bool(due) and str(due) < utc_now_iso() and row.get("status") not in TERMINAL_STATES
        row["is_overdue"] = overdue
        row["is_escalated"] = overdue  # escalation SLA handled by scheduler; flag mirrors overdue
        return row

    # ---- create ------------------------------------------------------------

    def create(
        self,
        store_id: str,
        *,
        task_type: str,
        title: str,
        created_by: str,
        priority: str = PRIORITY_DEFAULT,
        source: str = "manual",
        ref_type: Optional[str] = None,
        ref_id: Optional[str] = None,
        assignee_id: Optional[str] = None,
        assignee_group: Optional[str] = None,
        detail: str = "",
        due_at: Optional[str] = None,
        sla_policy: str = "keep_original_due_at",
        task_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        if sla_policy not in SLA_POLICIES:
            raise TaskError(f"unknown sla_policy: {sla_policy}")
        tid = task_id or new_task_id(store_id)
        now = utc_now_iso()
        assignee_status = "assigned" if assignee_id else "needs_triage"
        row = {
            "task_id": tid, "source_id": None, "store_id": store_id, "task_type": task_type,
            "priority": priority, "status": "pending", "source": source,
            "ref_type": ref_type, "ref_id": ref_id, "assignee_id": assignee_id,
            "assignee_status": assignee_status, "assignee_group": assignee_group,
            "created_by": created_by, "sla_policy": sla_policy, "title": title,
            "detail": detail, "due_at": due_at, "created_at": now, "updated_at": now,
        }
        with self._lock:
            conn = self._connect()
            try:
                self._exec(
                    conn,
                    f"INSERT INTO tasks({_TASK_COLS}) VALUES ({','.join(['?'] * 19)})",
                    tuple(row[c] for c in _TASK_COLS.replace(" ", "").split(",")),
                )
                self._write_event(conn, tid, "create", created_by, None, "pending",
                                   to_assignee=assignee_id)
                conn.commit()
            finally:
                conn.close()
        return self._decorate(row)

    def _write_event(self, conn, task_id, event_type, actor_id, from_status, to_status,
                     *, from_assignee=None, to_assignee=None, sla_policy=None,
                     old_due_at=None, note=""):
        self._exec(
            conn,
            "INSERT INTO task_events(event_id, task_id, event_type, actor_id, from_status, "
            "to_status, from_assignee, to_assignee, sla_policy, old_due_at, note, ts) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (uuid.uuid4().hex, task_id, event_type, actor_id, from_status, to_status,
             from_assignee, to_assignee, sla_policy, old_due_at, note, utc_now_iso()),
        )

    # ---- read --------------------------------------------------------------

    def get(self, task_id: str, store_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            conn = self._connect()
            try:
                row = self._exec(
                    conn, "SELECT * FROM tasks WHERE task_id=? AND store_id=?",
                    (task_id, store_id), fetch="one")
            finally:
                conn.close()
        return self._decorate(row)

    def timeline(self, task_id: str) -> List[Dict[str, Any]]:
        with self._lock:
            conn = self._connect()
            try:
                return self._exec(
                    conn, "SELECT * FROM task_events WHERE task_id=? ORDER BY ts ASC",
                    (task_id,), fetch="all") or []
            finally:
                conn.close()

    def list_tasks(self, store_id: str, *, status: Optional[str] = None,
                   task_type: Optional[str] = None, assignee_id: Optional[str] = None,
                   overdue: Optional[bool] = None, limit: int = 50) -> List[Dict[str, Any]]:
        sql = "SELECT * FROM tasks WHERE store_id=?"
        params: List[Any] = [store_id]
        if status:
            sql += " AND status=?"; params.append(status)
        if task_type:
            sql += " AND task_type=?"; params.append(task_type)
        if assignee_id:
            sql += " AND assignee_id=?"; params.append(assignee_id)
        sql += " ORDER BY created_at DESC LIMIT ?"; params.append(limit)
        with self._lock:
            conn = self._connect()
            try:
                rows = self._exec(conn, sql, tuple(params), fetch="all") or []
            finally:
                conn.close()
        rows = [self._decorate(r) for r in rows]
        if overdue is not None:
            rows = [r for r in rows if r["is_overdue"] == overdue]
        return rows

    # ---- transition --------------------------------------------------------

    def transition(self, task_id: str, store_id: str, action: str, *, actor_id: str,
                   assignee_id: Optional[str] = None, sla_policy: Optional[str] = None,
                   reason: str = "", detail: Optional[str] = None) -> Dict[str, Any]:
        if action not in TRANSITIONS:
            raise TaskError(f"unknown action: {action}")
        allowed_from, to_status = TRANSITIONS[action]
        with self._lock:
            conn = self._connect()
            try:
                cur = self._exec(conn, "SELECT * FROM tasks WHERE task_id=? AND store_id=?",
                                 (task_id, store_id), fetch="one")
                if not cur:
                    raise TaskError("task not found")
                frm = cur["status"]
                if frm not in allowed_from:
                    raise TaskError(f"illegal transition {action}: {frm} not in {sorted(allowed_from)}")
                if action == "verify" and cur.get("created_by") and reason == "__selfcheck__":
                    pass  # placeholder; submitter!=verifier enforced at router via actor check
                now = utc_now_iso()
                new_status = to_status or frm
                fields, params = ["status=?", "updated_at=?"], [new_status, now]
                from_assignee = cur.get("assignee_id")
                to_assignee = from_assignee
                pol = None
                old_due = cur.get("due_at")
                if action in ("assign", "reassign"):
                    if not assignee_id:
                        raise TaskError(f"{action} requires assignee_id")
                    to_assignee = assignee_id
                    fields += ["assignee_id=?", "assignee_status=?"]; params += [assignee_id, "assigned"]
                    pol = sla_policy or cur.get("sla_policy") or "keep_original_due_at"
                    if pol not in SLA_POLICIES:
                        raise TaskError(f"unknown sla_policy: {pol}")
                    fields.append("sla_policy=?"); params.append(pol)
                if action == "accept" and not cur.get("assignee_id"):
                    to_assignee = actor_id
                    fields += ["assignee_id=?", "assignee_status=?"]; params += [actor_id, "assigned"]
                if detail is not None:
                    fields.append("detail=?"); params.append(detail)
                params += [task_id, store_id]
                self._exec(conn, f"UPDATE tasks SET {','.join(fields)} WHERE task_id=? AND store_id=?",
                           tuple(params))
                self._write_event(conn, task_id, action, actor_id,
                                  frm, new_status if to_status else None,
                                  from_assignee=from_assignee if action in ("assign", "reassign", "accept") else None,
                                  to_assignee=to_assignee if action in ("assign", "reassign", "accept") else None,
                                  sla_policy=pol, old_due_at=old_due if pol else None, note=reason)
                conn.commit()
                row = self._exec(conn, "SELECT * FROM tasks WHERE task_id=? AND store_id=?",
                                 (task_id, store_id), fetch="one")
            finally:
                conn.close()
        return self._decorate(row)


def task_store(db: Any) -> TaskStore:
    return TaskStore(db)
