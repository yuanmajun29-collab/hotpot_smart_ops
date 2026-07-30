#!/usr/bin/env python3
"""SOP模板管理器 (SC01).

对应架构设计 v1.1 §1.6.2 SOPTemplateManager.
支持CRUD + SemVer版本控制.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from .models import (
    PaginatedResult,
    SOPCategory,
    SOPRule,
    SOPTemplate,
    TemplateStatus,
    TemplateVersion,
    Zone,
)

logger = logging.getLogger(__name__)


def _enum_val(val) -> str:
    """安全获取枚举值(兼容字符串和枚举对象)."""
    return val.value if hasattr(val, 'value') else str(val)


class SOPTemplateManager:
    """SOP模板 CRUD + 版本管理 — 对接 PRD SC01.

    功能:
    - create_template: 创建新模板(v1.0.0)
    - update_template: 更新(自动递增补丁版本)
    - list_templates: 分页查询
    - get_template_version_history: 版本历史
    """

    def __init__(self, db_session=None) -> None:
        self._db = db_session
        if db_session:
            self._ensure_tables()

    # ── 公开接口 ──────────────────────────────────────────

    def create_template(
        self,
        name: str,
        category: SOPCategory,
        zone: Zone,
        rules: List[SOPRule],
        author: str = "system",
        store_scope: Optional[str] = None,
    ) -> SOPTemplate:
        """创建新模板，自动分配 v1.0.0 版本号."""
        template_id = f"TPL-{uuid.uuid4().hex[:8].upper()}"
        now = datetime.now()
        template = SOPTemplate(
            template_id=template_id,
            name=name,
            category=category,
            zone=zone,
            rules=rules,
            version="1.0.0",
            status=TemplateStatus.DRAFT,
            author=author,
            store_scope=store_scope,
            created_at=now,
            updated_at=now,
        )

        if self._db:
            self._save_template(template)
            self._save_version(template, "创建模板")
        else:
            logger.info("Template created (in-memory): %s", template_id)

        return template

    def update_template(
        self,
        template_id: str,
        rules: Optional[List[SOPRule]] = None,
        status: Optional[TemplateStatus] = None,
        updater: str = "",
    ) -> Optional[SOPTemplate]:
        """更新模板，自动递增补丁版本号 (v1.0.0 → v1.0.1)."""
        template = self._get_template(template_id)
        if not template:
            logger.warning("Template not found: %s", template_id)
            return None

        old_version = template.version
        change_summary_parts = []

        if rules is not None:
            template.rules = rules
            change_summary_parts.append(f"规则更新({len(rules)}条)")
        if status is not None:
            template.status = status
            change_summary_parts.append(f"状态→{status.value}")

        # SemVer 补丁版本递增
        major, minor, patch = [int(x) for x in old_version.split(".")]
        patch += 1
        template.version = f"{major}.{minor}.{patch}"
        template.updated_at = datetime.now()
        template.updater = updater

        if self._db:
            self._save_template(template)
            self._save_version(template, "; ".join(change_summary_parts) or "更新")

        return template

    def list_templates(
        self,
        category: Optional[SOPCategory] = None,
        zone: Optional[Zone] = None,
        status: str = "active",
        page: int = 1,
        size: int = 20,
    ) -> PaginatedResult:
        """分页查询模板列表."""
        templates = self._query_templates(category, zone, status)
        total = len(templates)

        start = (page - 1) * size
        end = start + size
        items = templates[start:end]

        return PaginatedResult(
            items=[t.dict() for t in items],
            total=total,
            page=page,
            size=size,
        )

    def get_template(self, template_id: str) -> Optional[SOPTemplate]:
        """获取单个模板详情."""
        return self._get_template(template_id)

    def get_template_version_history(self, template_id: str) -> List[TemplateVersion]:
        """获取模板版本历史."""
        if not self._db:
            return []
        try:
            cursor = self._db.cursor()
            cursor.execute(
                "SELECT version, changed_by, changed_at, change_summary, rule_count "
                "FROM sop_template_versions WHERE template_id=? ORDER BY changed_at DESC",
                (template_id,),
            )
            return [
                TemplateVersion(
                    version=row[0],
                    changed_by=row[1],
                    changed_at=datetime.fromisoformat(row[2]) if row[2] else datetime.now(),
                    change_summary=row[3],
                    rule_count=row[4],
                )
                for row in cursor.fetchall()
            ]
        except Exception as exc:
            logger.error("Query version history failed: %s", exc)
            return []

    def activate_template(self, template_id: str, operator: str) -> bool:
        """激活模板(同区域其他活跃模板自动归档)."""
        template = self._get_template(template_id)
        if not template:
            return False

        # 同区域其他活跃模板归档
        if self._db:
            cursor = self._db.cursor()
            cursor.execute(
                "UPDATE sop_templates SET status='archived', updated_at=?, updater=? "
                "WHERE zone=? AND status='active' AND template_id!=?",
                (datetime.now(), operator, template.zone.value, template_id),
            )
            self._db.commit()

        return self.update_template(template_id, status=TemplateStatus.ACTIVE, updater=operator) is not None

    def delete_template(self, template_id: str, deleted_by: str) -> bool:
        """软删除模板."""
        if not self._db:
            return False
        try:
            cursor = self._db.cursor()
            cursor.execute(
                "UPDATE sop_templates SET status='archived', updated_at=?, updater=? "
                "WHERE template_id=?",
                (datetime.now(), deleted_by, template_id),
            )
            self._db.commit()
            return cursor.rowcount > 0
        except Exception as exc:
            logger.error("Delete template failed: %s", exc)
            return False

    # ── 内部方法 ──────────────────────────────────────────

    def _get_template(self, template_id: str) -> Optional[SOPTemplate]:
        """从DB或返回None."""
        if not self._db:
            return None
        try:
            cursor = self._db.cursor()
            cursor.execute(
                "SELECT template_id, name, category, zone, rules_json, version, status, "
                "author, store_scope, created_at, updated_at, updater "
                "FROM sop_templates WHERE template_id=?",
                (template_id,),
            )
            row = cursor.fetchone()
            if not row:
                return None
            rules_data = json.loads(row[4]) if row[4] else []
            return SOPTemplate(
                template_id=row[0],
                name=row[1],
                category=row[2],
                zone=row[3],
                rules=[SOPRule(**r) for r in rules_data],
                version=row[5],
                status=row[6],
                author=row[7],
                store_scope=row[8],
                created_at=datetime.fromisoformat(row[9]) if row[9] else datetime.now(),
                updated_at=datetime.fromisoformat(row[10]) if row[10] else datetime.now(),
                updater=row[11] or "",
            )
        except Exception as exc:
            logger.error("Get template failed: %s", exc)
            return None

    def _query_templates(
        self,
        category: Optional[SOPCategory],
        zone: Optional[Zone],
        status: str,
    ) -> List[SOPTemplate]:
        """查询模板列表."""
        if not self._db:
            return []

        conditions = []
        params: List[Any] = []

        if category:
            conditions.append("category=?")
            params.append(category.value)
        if zone:
            conditions.append("zone=?")
            params.append(zone.value)
        if status:
            conditions.append("status=?")
            params.append(status)

        where = f" WHERE {' AND '.join(conditions)}" if conditions else ""
        try:
            cursor = self._db.cursor()
            cursor.execute(f"SELECT * FROM sop_templates{where} ORDER BY updated_at DESC", params)
            rows = cursor.fetchall()
            results = []
            for row in rows:
                rules_data = json.loads(row[4]) if len(row) > 4 and row[4] else []
                results.append(SOPTemplate(
                    template_id=row[0],
                    name=row[1],
                    category=row[2],
                    zone=row[3],
                    rules=[SOPRule(**r) for r in rules_data],
                    version=row[5] if len(row) > 5 else "1.0.0",
                    status=row[6] if len(row) > 6 else "draft",
                ))
            return results
        except Exception as exc:
            logger.error("Query templates failed: %s", exc)
            return []

    def _save_template(self, template: SOPTemplate) -> None:
        """保存/更新模板到DB."""
        rules_json = json.dumps([r.model_dump() if hasattr(r, 'model_dump') else r.dict() for r in template.rules], ensure_ascii=False)
        cursor = self._db.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO sop_templates (
                template_id, name, category, zone, rules_json, version, status,
                author, store_scope, created_at, updated_at, updater
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            template.template_id, template.name, _enum_val(template.category),
            template.zone.value, rules_json, template.version, template.status.value,
            template.author, template.store_scope,
            template.created_at.isoformat(), template.updated_at.isoformat(),
            template.updater,
        ))
        self._db.commit()

    def _save_version(self, template: SOPTemplate, summary: str) -> None:
        """保存版本历史记录."""
        cursor = self._db.cursor()
        cursor.execute("""
            INSERT INTO sop_template_versions (
                template_id, version, changed_by, changed_at, change_summary, rule_count
            ) VALUES (?, ?, ?, ?, ?, ?)
        """, (
            template.template_id, template.version, template.updater or template.author,
            datetime.now().isoformat(), summary, len(template.rules),
        ))
        self._db.commit()

    def _ensure_tables(self) -> None:
        """创建必要的DB表."""
        cursor = self._db.cursor()
        cursor.executescript("""
            CREATE TABLE IF NOT EXISTS sop_templates (
                template_id   TEXT PRIMARY KEY,
                name          TEXT NOT NULL,
                category      TEXT NOT NULL,
                zone          TEXT NOT NULL,
                rules_json    TEXT NOT NULL DEFAULT '[]',
                version       TEXT NOT NULL DEFAULT '1.0.0',
                status        TEXT NOT NULL DEFAULT 'draft',
                author        TEXT NOT NULL DEFAULT 'system',
                store_scope   TEXT,
                created_at    TEXT NOT NULL,
                updated_at    TEXT NOT NULL,
                updater       TEXT DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS sop_template_versions (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                template_id    TEXT NOT NULL,
                version        TEXT NOT NULL,
                changed_by     TEXT NOT NULL,
                changed_at     TEXT NOT NULL,
                change_summary TEXT NOT NULL DEFAULT '',
                rule_count     INTEGER NOT NULL DEFAULT 0,
                FOREIGN KEY (template_id) REFERENCES sop_templates(template_id)
            );

            CREATE INDEX IF NOT EXISTS idx_sop_tpl_zone ON sop_templates(zone);
            CREATE INDEX IF NOT EXISTS idx_sop_tpl_status ON sop_templates(status);
            CREATE INDEX IF NOT EXISTS idx_sop_tpl_ver ON sop_template_versions(template_id);
        """)
        self._db.commit()
