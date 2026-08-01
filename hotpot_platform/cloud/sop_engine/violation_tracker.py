#!/usr/bin/env python3
"""违规记录与追踪器 (SC03).

对应架构设计 v1.1 §1.6.3 ViolationTracker.
输出: Event Hub critical/warn 事件 + sop_violations 表持久化.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from .models import (
    ComplianceReport,
    PaginatedResult,
    Severity,
    ViolationRecord,
    ViolationStats,
    ViolationStatus,
    Zone,
)

logger = logging.getLogger(__name__)


def _enum_val(val) -> str:
    """安全获取枚举值(兼容字符串和枚举对象)."""
    return val.value if hasattr(val, 'value') else str(val)


class ViolationTracker:
    """违规记录与追踪 — 对接 PRD SC03.

    功能:
    - record_violation: 记录违规(自动推送告警)
    - acknowledge: 确认处理
    - query_violations: 分页查询
    - getViolationStats: 统计分析
    """

    def __init__(self, db_session=None, alert_gateway=None) -> None:
        self._db = db_session
        self._alert = alert_gateway
        if db_session:
            self._ensure_tables()

    # ── 公开接口 ──────────────────────────────────────────

    def record_violation(
        self,
        report: ComplianceReport,
        auto_acknowledge: bool = False,
    ) -> List[ViolationRecord]:
        """记录合规报告中的所有违规.

        - critical/major → 自动推送告警
        - minor → 仅记录
        - auto_acknowledge=True → minor级别自动确认

        Returns:
            新创建的ViolationRecord列表
        """
        records: List[ViolationRecord] = []
        for v in report.violations:
            should_auto_ack = auto_acknowledge and v.severity in (Severity.MINOR, Severity.INFO)
            record = ViolationRecord(
                violation_id=f"VIO-{uuid.uuid4().hex[:10].upper()}",
                report=report,
                severity=v.severity,
                status=ViolationStatus.ACKNOWLEDGED if should_auto_ack else ViolationStatus.OPEN,
                store_id=report.store_id,
                zone=v.zone,
                rule_id=v.rule_id,
                rule_name=v.rule_name,
                detected_at=v.detected_at,
                auto_acknowledged=should_auto_ack,
            )

            # 持久化
            if self._db:
                self._insert_record(record)

            # 推送告警
            if self._alert and not should_auto_ack:
                self._send_alert(record)

            records.append(record)

        logger.info(
            "Recorded %d violations for store=%s zone=%s (auto_ack=%s)",
            len(records), report.store_id, report.zone, auto_acknowledge,
        )
        return records

    def acknowledge(
        self,
        violation_id: str,
        ack_by: str,
        note: str = "",
        corrective_evidence: Optional[str] = None,
    ) -> Optional[ViolationRecord]:
        """确认违规已处理."""
        record = self._find_record(violation_id)
        if not record:
            logger.warning("Violation not found: %s", violation_id)
            return None

        record.status = ViolationStatus.ACKNOWLEDGED
        record.acknowledged_at = datetime.now()
        record.acknowledged_by = ack_by
        record.ack_note = note
        record.corrective_evidence = corrective_evidence

        if self._db:
            cursor = self._db.cursor()
            cursor.execute("""
                UPDATE sop_violations SET status=?, acknowledged_at=?,
                    acknowledged_by=?, ack_note=?, corrective_evidence=?
                WHERE violation_id=?
            """, (
                "acknowledged", datetime.now().isoformat(), ack_by, note,
                corrective_evidence, violation_id,
            ))
            self._db.commit()

        return record

    def resolve(
        self,
        violation_id: str,
        resolved_by: str,
    ) -> Optional[ViolationRecord]:
        """标记违规为已解决."""
        record = self._find_record(violation_id)
        if not record:
            return None

        record.status = ViolationStatus.RESOLVED
        record.resolved_at = datetime.now()
        record.resolved_by = resolved_by

        if self._db:
            cursor = self._db.cursor()
            cursor.execute("""
                UPDATE sop_violations SET status='resolved', resolved_at=?, resolved_by=?
                WHERE violation_id=?
            """, (datetime.now().isoformat(), resolved_by, violation_id))
            self._db.commit()

        return record

    def query_violations(
        self,
        store_id: str,
        start_date: Optional[Any] = None,
        end_date: Optional[Any] = None,
        severity: Optional[str] = None,
        status: Optional[str] = None,
        page: int = 1,
        size: int = 20,
    ) -> PaginatedResult:
        """分页查询违规记录."""
        conditions = ["store_id=?"]
        params: List[Any] = [store_id]

        if start_date:
            conditions.append("detected_at >= ?")
            params.append(start_date)
        if end_date:
            conditions.append("detected_at <= ?")
            params.append(end_date)
        if severity:
            conditions.append("severity=?")
            params.append(severity)
        if status:
            conditions.append("status=?")
            params.append(status)

        where = f" WHERE {' AND '.join(conditions)}"

        # 总数
        if self._db:
            cursor = self._db.cursor()
            cursor.execute(f"SELECT COUNT(*) FROM sop_violations{where}", params)
            total = cursor.fetchone()[0]
        else:
            total = 0

        # 分页
        offset = (page - 1) * size
        params.extend([size, offset])
        items = []
        if self._db:
            cursor = self._db.cursor()
            cursor.execute(
                f"SELECT * FROM sop_violations{where} ORDER BY detected_at DESC LIMIT ? OFFSET ?",
                params,
            )
            for row in cursor.fetchall():
                items.append(self._row_to_dict(row))

        return PaginatedResult(
            items=items,
            total=total,
            page=page,
            size=size,
        )

    def getViolationStats(
        self,
        store_id: str,
        period_days: int = 30,
    ) -> ViolationStats:
        """返回违规统计.

        Returns:
            ViolationStats 含 by_severity/by_category/repeat_rate/top_3_repeat_rules
        """
        stats = ViolationStats(store_id=store_id, period_days=period_days)

        if not self._db:
            return stats

        try:
            cursor = self._db.cursor()

            # 总数
            cursor.execute(
                "SELECT COUNT(*) FROM sop_violations WHERE store_id=? "
                "AND detected_at >= date('now', ?)",
                (store_id, f"-{period_days} days"),
            )
            stats.total_violations = cursor.fetchone()[0]

            # 按严重程度分组
            cursor.execute(
                "SELECT severity, COUNT(*) FROM sop_violations WHERE store_id=? "
                "AND detected_at >= date('now', ?) GROUP BY severity",
                (store_id, f"-{period_days} days"),
            )
            stats.by_severity = dict(cursor.fetchall())

            # 按分类分组(rule_name前缀近似category)
            cursor.execute(
                "SELECT rule_id, COUNT(*) as cnt FROM sop_violations WHERE store_id=? "
                "AND detected_at >= date('now', ?) GROUP BY rule_id ORDER BY cnt DESC LIMIT 10",
                (store_id, f"-{period_days} days"),
            )
            rule_counts = cursor.fetchall()
            stats.top_3_repeat_rules = [
                {"rule_id": r[0], "count": r[1]} for r in rule_counts[:3]
            ]

            # 重复率: 同一规则出现>1次的占比
            if rule_counts:
                repeated = sum(1 for _, c in rule_counts if c > 1)
                stats.repeat_rate = round(repeated / len(rule_counts), 2)

            # 平均解决时长
            cursor.execute(
                "SELECT AVG(julianday(resolved_at) - julianday(detected_at)) * 24 "
                "FROM sop_violations WHERE store_id=? AND status='resolved' "
                "AND detected_at >= date('now', ?)",
                (store_id, f"-{period_days} days"),
            )
            row = cursor.fetchone()
            if row and row[0]:
                stats.avg_resolution_hours = round(row[0], 1)

        except Exception as exc:
            logger.error("Get violation stats failed: %s", exc)

        return stats

    # ── 内部方法 ──────────────────────────────────────────

    def _insert_record(self, record: ViolationRecord) -> None:
        """插入违规记录到DB."""
        cursor = self._db.cursor()
        cursor.execute("""
            INSERT INTO sop_violations (
                violation_id, store_id, zone, rule_id, rule_name, severity,
                status, detected_at, acknowledged_at, acknowledged_by,
                ack_note, corrective_evidence, resolved_at, resolved_by,
                auto_acknowledged
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            record.violation_id, record.store_id, _enum_val(record.zone),
            record.rule_id, record.rule_name, _enum_val(record.severity),
            _enum_val(record.status), record.detected_at.isoformat(),
            record.acknowledged_at.isoformat() if record.acknowledged_at else None,
            record.acknowledged_by, record.ack_note, record.corrective_evidence,
            record.resolved_at.isoformat() if record.resolved_at else None,
            record.resolved_by, int(record.auto_acknowledged),
        ))
        self._db.commit()

    def _find_record(self, violation_id: str) -> Optional[ViolationRecord]:
        """查找单条违规记录."""
        if not self._db:
            return None
        try:
            cursor = self._db.cursor()
            cursor.execute("SELECT * FROM sop_violations WHERE violation_id=?", (violation_id,))
            row = cursor.fetchone()
            if row:
                return self._row_to_record(row)
        except Exception as exc:
            logger.error("Find violation failed: %s", exc)
        return None

    @staticmethod
    def _row_to_dict(row: tuple) -> Dict[str, Any]:
        """将DB行转为字典."""
        columns = [
            "violation_id", "store_id", "zone", "rule_id", "rule_name",
            "severity", "status", "detected_at", "acknowledged_at",
            "acknowledged_by", "ack_note", "corrective_evidence",
            "resolved_at", "resolved_by", "auto_acknowledged",
        ]
        return {col: row[i] for i, col in enumerate(columns) if i < len(row)}

    @staticmethod
    def _row_to_record(row: tuple) -> ViolationRecord:
        """将DB行转为ViolationRecord对象."""
        d = ViolationTracker._row_to_dict(row)
        return ViolationRecord(**d)

    def _send_alert(self, record: ViolationRecord) -> None:
        """推送告警."""
        if not self._alert:
            return
        try:
            level = "critical" if record.severity == Severity.CRITICAL else "warn"
            self._alert.send({
                "type": "sop_violation_alert",
                "level": level,
                "violation_id": record.violation_id,
                "store_id": record.store_id,
                "zone": record.zone.value,
                "rule_id": record.rule_id,
                "rule_name": record.rule_name,
                "severity": record.severity.value,
                "message": f"[SOP违规-{record.severity.value}] {record.rule_name}",
            })
        except Exception as exc:
            logger.error("Send alert failed: %s", exc)

    def _ensure_tables(self) -> None:
        """创建违规记录表."""
        cursor = self._db.cursor()
        cursor.executescript("""
            CREATE TABLE IF NOT EXISTS sop_violations (
                violation_id       TEXT PRIMARY KEY,
                store_id           TEXT NOT NULL,
                zone               TEXT NOT NULL,
                rule_id            TEXT NOT NULL,
                rule_name          TEXT NOT NULL,
                severity           TEXT NOT NULL,
                status             TEXT NOT NULL DEFAULT 'open',
                detected_at        TEXT NOT NULL,
                acknowledged_at    TEXT,
                acknowledged_by    TEXT,
                ack_note           TEXT DEFAULT '',
                corrective_evidence TEXT,
                resolved_at        TEXT,
                resolved_by        TEXT,
                auto_acknowledged   INTEGER NOT NULL DEFAULT 0
            );

            CREATE INDEX IF NOT EXISTS idx_sop_vio_store ON sop_violations(store_id);
            CREATE INDEX IF NOT EXISTS idx_sop_vio_status ON sop_violations(status);
            CREATE INDEX IF NOT EXISTS idx_sop_vio_severity ON sop_violations(severity);
            CREATE INDEX IF NOT EXISTS idx_sop_vio_detected ON sop_violations(detected_at);

            -- 合规检查历史表(供趋势分析)
            CREATE TABLE IF NOT EXISTS sop_check_history (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                store_id         TEXT NOT NULL,
                zone             TEXT NOT NULL,
                check_date       TEXT NOT NULL DEFAULT (date('now')),
                compliance_score REAL NOT NULL DEFAULT 0,
                passed_count     INTEGER NOT NULL DEFAULT 0,
                failed_count     INTEGER NOT NULL DEFAULT 0,
                pending_count    INTEGER NOT NULL DEFAULT 0,
                total_rules      INTEGER NOT NULL DEFAULT 0,
                checked_at       TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_sop_hist_store ON sop_check_history(store_id);
        """)
        self._db.commit()
