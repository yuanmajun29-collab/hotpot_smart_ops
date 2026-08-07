#!/usr/bin/env python3
"""SOP合规检查器 (SC01/SC02).

对应架构设计 v1.1 §1.6.1 SOPChecker.
支持多策略检查(mask_detect/hand_wash/temp_monitor/fefo_check等).
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from .models import (
    CHECK_STRATEGIES,
    CheckpointResult,
    CheckStrategy,
    ComplianceReport,
    ComplianceTrend,
    Severity,
    SOPCategory,
    SOPRule,
    ViolationItem,
    Zone,
)

logger = logging.getLogger(__name__)


def _enum_val(val) -> str:
    """安全获取枚举值(兼容字符串和枚举对象)."""
    return val.value if hasattr(val, 'value') else str(val)


class SOPChecker:
    """SOP合规检查器 — 对接 PRD SC01/SC02.

    支持的检查策略:
    - mask_detect:     口罩佩戴检测(视觉)
    - hand_wash:       洗手合规(视觉+IoT)
    - temp_monitor:    温控合规(IoT)
    - fefo_check:      FEFO先失效先出(RFID+库存)
    - table_cleanup:   桌面清洁(视觉)
    - greeting_std:    迎宾标准(视觉)
    - uniform_check:   着装规范(视觉)
    - food_safety:     食品安全(综合)
    """

    def __init__(
        self,
        db_session=None,  # SQLite connection / None for in-memory
        event_hub_client=None,  # EventHub client for alerting
    ) -> None:
        self._db = db_session
        self._hub = event_hub_client
        self._rule_cache: Dict[str, SOPRule] = {}
        self._strategy_handlers = {
            CheckStrategy.MASK_DETECT: self._check_mask_detect,
            CheckStrategy.HAND_WASH: self._check_hand_wash,
            CheckStrategy.TEMP_MONITOR: self._check_temp_monitor,
            CheckStrategy.FEFO_CHECK: self._check_fefo,
            CheckStrategy.TABLE_CLEANUP: self._check_table_cleanup,
            CheckStrategy.GREETING_STD: self._check_greeting,
            CheckStrategy.UNIFORM_CHECK: self._check_uniform,
            CheckStrategy.FOOD_SAFETY: self._check_food_safety,
        }

    # ── 公开接口 ──────────────────────────────────────────

    def check(
        self,
        store_id: str,
        zone: Zone,
        signals: Optional[Dict[str, Any]] = None,
        template_id: Optional[str] = None,
    ) -> ComplianceReport:
        """执行单区域合规检查.

        Args:
            store_id: 门店ID
            zone: 检查区域
            signals: 证据信号字典 {checkpoint_key: value}
            template_id: 指定模板ID(None=使用该区域活跃模板)

        Returns:
            ComplianceReport 含 compliance_score + violations[]
        """
        signals = signals or {}
        rules = self._load_rules(store_id, zone, template_id)

        if not rules:
            return ComplianceReport(
                store_id=store_id,
                zone=zone,
                compliance_score=100.0,
                total_rules=0,
            )

        checkpoints: List[CheckpointResult] = []
        violations: List[ViolationItem] = []
        passed = 0
        failed = 0
        pending = 0

        for rule in rules:
            if not rule.enabled:
                continue

            handler = self._strategy_handlers.get(rule.check_strategy)
            if handler is None:
                logger.warning("Unknown strategy: %s", rule.check_strategy)
                continue

            cp_result, is_violation = handler(rule, signals)
            checkpoints.append(cp_result)

            if cp_result.passed:
                passed += 1
            elif cp_result.message == "PENDING":
                pending += 1
            else:
                failed += 1
                if is_violation:
                    violations.append(ViolationItem(
                        rule_id=rule.rule_id,
                        rule_name=rule.name,
                        severity=rule.severity,
                        zone=zone,
                        evidence_ref=cp_result.evidence_ref or "",
                        suggested_action=rule.corrective_action,
                    ))

        total = passed + failed + pending
        score = self._calculate_score(passed, failed, pending, violations)

        report = ComplianceReport(
            store_id=store_id,
            zone=zone,
            total_rules=total,
            passed_count=passed,
            failed_count=failed,
            pending_count=pending,
            compliance_score=score,
            checkpoints=checkpoints,
            violations=violations,
        )

        # 推送告警到EventHub
        if self._hub and violations:
            self._push_alerts(report)

        return report

    def batch_check(
        self,
        store_id: str,
        zones: Optional[List[Zone]] = None,
        signals: Optional[Dict[str, Zone]] = None,
    ) -> Dict[str, ComplianceReport]:
        """批量检查门店所有区域(或指定区域).

        Args:
            zones: 区域列表(None=全部4个区域)
            signals: {zone: signal_dict} 按区域分组信号

        Returns:
            {zone_value: ComplianceReport}
        """
        zones = zones or list(Zone)
        signals = signals or {}
        results: Dict[str, ComplianceReport] = {}

        for zone in zones:
            zone_signals = signals.get(_enum_val(zone), {})
            report = self.check(store_id, zone, zone_signals)
            results[_enum_val(zone)] = report

        return results

    def get_compliance_trend(
        self,
        store_id: str,
        days: int = 30,
    ) -> ComplianceTrend:
        """返回合规趋势.

        Returns:
            ComplianceTrend 含 daily_scores[], avg_score, improvement_pct
        """
        # 从DB查询历史记录或生成模拟趋势
        daily_scores = self._query_history(store_id, days)

        if not daily_scores:
            return ComplianceTrend(
                store_id=store_id,
                period_days=days,
                avg_score=0.0,
            )

        scores = [d.get("score", 0) for d in daily_scores]
        avg = round(sum(scores) / len(scores), 1)

        # 计算较上周变化
        improvement = 0.0
        if len(daily_scores) >= 14:
            recent_avg = sum(scores[:7]) / 7
            prev_avg = sum(scores[7:14]) / 7
            if prev_avg > 0:
                improvement = round((recent_avg - prev_avg) / prev_avg * 100, 1)

        # 最差区域
        worst_zone = ""
        worst_score = 101.0
        for d in daily_scores:
            for zv in d.get("by_zone", {}):
                if d["by_zone"][zv] < worst_score:
                    worst_score = d["by_zone"][zv]
                    worst_zone = zv

        # Top高频违规
        top_violations = self._top_violations(store_id, days)

        return ComplianceTrend(
            store_id=store_id,
            period_days=days,
            daily_scores=daily_scores,
            avg_score=avg,
            worst_zone=worst_zone,
            improvement_pct=improvement,
            top_violations=top_violations,
        )

    # ── 策略检查方法 ───────────────────────────────────────

    def _check_mask_detect(
        self,
        rule: SOPRule,
        signals: Dict[str, Any],
    ) -> tuple:
        """口罩佩戴检测(视觉YOLO)."""
        key = f"mask_{_enum_val(rule.zone)}"
        detected = signals.get(key, False)

        # 支持置信度阈值
        threshold = rule.threshold or {}
        min_conf = threshold.get("min_confidence", 0.8)
        confidence = signals.get(f"{key}_confidence", 1.0)

        passed = bool(detected) and (float(confidence) >= min_conf)
        evidence = signals.get(f"{key}_event_id", "")

        result = CheckpointResult(
            checkpoint_id=rule.rule_id,
            name=rule.name,
            check_type="vision",
            passed=passed,
            actual_value={"detected": detected, "confidence": confidence},
            expected_value={"min_confidence": min_conf},
            evidence_ref=evidence,
            message="" if passed else "未检测到口罩佩戴",
        )
        return result, (not passed and rule.severity in (Severity.CRITICAL, Severity.MAJOR))

    def _check_hand_wash(
        self,
        rule: SOPRule,
        signals: Dict[str, Any],
    ) -> tuple:
        """洗手合规(行为识别+水龙头IoT)."""
        key = f"handwash_{_enum_val(rule.zone)}"
        last_wash_sec = signals.get(key, -1)  # 距上次洗手秒数

        threshold = rule.threshold or {}
        window_sec = threshold.get("window_sec", 30)

        if last_wash_sec < 0:
            return CheckpointResult(
                checkpoint_id=rule.rule_id,
                name=rule.name,
                check_type="iot",
                passed=False,
                actual_value=None,
                expected_value={"max_window_sec": window_sec},
                message="PENDING",
            ), False

        passed = last_wash_sec <= window_sec
        result = CheckpointResult(
            checkpoint_id=rule.rule_id,
            name=rule.name,
            check_type="vision+iot",
            passed=passed,
            actual_value={"last_wash_sec_ago": last_wash_sec},
            expected_value={"max_window_sec": window_sec},
            message="" if passed else f"距上次洗手{last_wash_sec}s, 超过{window_sec}s限制",
        )
        return result, not passed

    def _check_temp_monitor(
        self,
        rule: SOPRule,
        signals: Dict[str, Any],
    ) -> tuple:
        """温控合规(IoT温度传感器)."""
        key = f"temp_{_enum_val(rule.zone)}"
        current_temp = signals.get(key)

        if current_temp is None:
            return CheckpointResult(
                checkpoint_id=rule.rule_id,
                name=rule.name,
                check_type="iot",
                passed=False,
                actual_value=None,
                message="PENDING",
            ), False

        threshold = rule.threshold or {"min_temp_c": -18.0, "max_temp_c": -16.0}
        lo = threshold.get("min_temp_c", -999)
        hi = threshold.get("max_temp_c", 999)

        # 还要检查持续时长
        duration_sec = signals.get(f"{key}_violation_duration", 0)
        max_duration = threshold.get("alarm_duration_sec", 900)

        in_range = lo <= float(current_temp) <= hi
        passed = in_range and duration_sec < max_duration

        result = CheckpointResult(
            checkpoint_id=rule.rule_id,
            name=rule.name,
            check_type="iot",
            passed=passed,
            actual_value={
                "temp_c": current_temp,
                "violation_duration_sec": duration_sec,
            },
            expected_value={"range_c": [lo, hi], "max_duration_sec": max_duration},
            evidence_ref=signals.get(f"{key}_reading_id", ""),
            message="" if passed else f"温度{current_temp}°C 超出[{lo}, {hi}]°C"
                       + (f" 持续{duration_sec}s" if duration_sec > 0 else ""),
        )
        return result, not passed

    def _check_fefo(
        self,
        rule: SOPRule,
        signals: Dict[str, Any],
    ) -> tuple:
        """FEFO先失效先出(RFID+库存快照)."""
        key = "fefo_pick_order"
        pick_order = signals.get(key, [])

        if not pick_order:
            return CheckpointResult(
                checkpoint_id=rule.rule_id,
                name=rule.name,
                check_type="rfid+inventory",
                passed=True,
                message="无出库操作",
            ), False

        # 检查出库是否按expiry_date升序(最早过期优先)
        expiry_dates = [p.get("expiry_date") for p in pick_order if p.get("expiry_date")]
        is_sorted = all(
            expiry_dates[i] <= expiry_dates[i + 1]
            for i in range(len(expiry_dates) - 1)
        ) if len(expiry_dates) > 1 else True

        result = CheckpointResult(
            checkpoint_id=rule.rule_id,
            name=rule.name,
            check_type="rfid+inventory",
            passed=is_sorted,
            actual_value={"pick_count": len(pick_order), "sorted_by_fefo": is_sorted},
            expected_value={"sorted_by_expiry_asc": True},
            evidence_ref=signals.get("fefo_batch_id", ""),
            message="" if is_sorted else "出库未按FEFO规则(先失效先出)",
        )
        return result, not is_sorted

    def _check_table_cleanup(
        self,
        rule: SOPRule,
        signals: Dict[str, Any],
    ) -> tuple:
        """桌面清洁(视觉检测)."""
        key = "table_idle_min"
        idle_min = signals.get(key, 0)

        threshold = rule.threshold or {}
        max_idle = threshold.get("idle_min", 10)

        passed = idle_min < max_idle or idle_min == 0
        result = CheckpointResult(
            checkpoint_id=rule.rule_id,
            name=rule.name,
            check_type="vision",
            passed=passed,
            actual_value={"idle_min": idle_min},
            expected_value={"max_idle_min": max_idle},
            message="" if passed else f"桌面空闲{idle_min}分钟未清理",
        )
        # 桌面清洁是提醒级，不产生违规
        return result, False

    def _check_greeting(
        self,
        rule: SOPRule,
        signals: Dict[str, Any],
    ) -> tuple:
        """迎宾标准(视觉行为识别)."""
        key = "greeting_response_sec"
        response_sec = signals.get(key, -1)

        if response_sec < 0:
            return CheckpointResult(
                checkpoint_id=rule.rule_id,
                name=rule.name,
                check_type="vision",
                passed=False,
                message="PENDING",
            ), False

        threshold = rule.threshold or {}
        max_response = threshold.get("response_sec", 30)
        passed = response_sec <= max_response

        result = CheckpointResult(
            checkpoint_id=rule.rule_id,
            name=rule.name,
            check_type="vision",
            passed=passed,
            actual_value={"response_sec": response_sec},
            expected_value={"max_response_sec": max_response},
            message="" if passed else f"顾客进门{response_sec}s无迎宾(>{max_response}s)",
        )
        return result, False  # 迎宾是提醒级

    def _check_uniform(
        self,
        rule: SOPRule,
        signals: Dict[str, Any],
    ) -> tuple:
        """着装规范(视觉检测)."""
        key = f"uniform_{_enum_val(rule.zone)}"
        compliant = signals.get(key, True)

        result = CheckpointResult(
            checkpoint_id=rule.rule_id,
            name=rule.name,
            check_type="vision",
            passed=bool(compliant),
            actual_value={"compliant": compliant},
            evidence_ref=signals.get(f"{key}_event_id", ""),
            message="" if bool(compliant) else "员工未按标准着装",
        )
        return result, (not compliant and rule.severity in (Severity.CRITICAL, Severity.MAJOR))

    def _check_food_safety(
        self,
        rule: SOPRule,
        signals: Dict[str, Any],
    ) -> tuple:
        """食品安全综合检测."""
        issues: List[str] = []

        # 留样检查
        sample_done = signals.get("food_sample_done", False)
        if not sample_done:
            issues.append("留样未完成")

        # 保质期检查
        expired_items = signals.get("expired_items_count", 0)
        if expired_items > 0:
            issues.append(f"发现{expired_items}项临期/过期食材")

        # 温度超标
        temp_ok = signals.get("food_temp_ok", True)
        if not temp_ok:
            issues.append("食品温度超标")

        passed = len(issues) == 0
        result = CheckpointResult(
            checkpoint_id=rule.rule_id,
            name=rule.name,
            check_type="comprehensive",
            passed=passed,
            actual_value={"issues": issues},
            message="; ".join(issues) if issues else "",
        )
        return result, (not passed and rule.severity in (Severity.CRITICAL, Severity.MAJOR))

    # ── 内部辅助 ──────────────────────────────────────────

    def _load_rules(self, store_id: str, zone: Zone, template_id: Optional[str]) -> List[SOPRule]:
        """加载指定区域的活跃规则.

        优先从DB加载，降级为预置规则.
        """
        # 门店可以发布不同版本的规则；缓存不得跨门店共享。
        cache_key = f"{store_id}:{_enum_val(zone)}:{template_id or 'default'}"
        if cache_key in self._rule_cache:
            return self._rule_cache[cache_key]

        rules: List[SOPRule] = []

        # 尝试从DB加载
        if self._db:
            try:
                cursor = self._db.cursor()
                if template_id:
                    cursor.execute(
                        "SELECT rules_json FROM sop_templates WHERE template_id=? AND status='active'",
                        (template_id,),
                    )
                else:
                    cursor.execute(
                        "SELECT rules_json FROM sop_templates WHERE zone=? AND status='active'",
                        (_enum_val(zone),),
                    )
                row = cursor.fetchone()
                if row and row[0]:
                    import json
                    rules_data = json.loads(row[0])
                    rules = [SOPRule(**r) for r in rules_data]
            except Exception as exc:
                logger.warning("DB load rules failed: %s", exc)

        # 降级为预置规则
        if not rules:
            rules = self._get_default_rules(zone)

        self._rule_cache[cache_key] = rules
        return rules

    def _get_default_rules(self, zone: Zone) -> List[SOPRule]:
        """返回各区域预置SOP规则(无需DB也可工作)."""
        defaults: Dict[Zone, List[Dict[str, Any]]] = {
            Zone.KITCHEN: [
                {
                    "rule_id": "SOP-KITCHEN-001",
                    "name": "厨师必须佩戴口罩",
                    "description": "厨房操作区域内所有人员必须佩戴口罩",
                    "severity": "major",
                    "check_strategy": "mask_detect",
                    "corrective_action": "立即佩戴口罩，记录违规",
                    "category": "kitchen_hygiene",
                    "zone": "kitchen",
                },
                {
                    "rule_id": "SOP-KITCHEN-002",
                    "name": "操作前洗手消毒",
                    "description": "进入操作台前30秒内必须洗手消毒",
                    "severity": "major",
                    "check_strategy": "hand_wash",
                    "corrective_action": "立即洗手消毒",
                    "category": "kitchen_hygiene",
                    "zone": "kitchen",
                },
                {
                    "rule_id": "SOP-KITCHEN-003",
                    "name": "标准着装规范",
                    "description": "厨师服、帽子、口罩齐全整洁",
                    "severity": "minor",
                    "check_strategy": "uniform_check",
                    "corrective_action": "更换为标准着装",
                    "category": "kitchen_hygiene",
                    "zone": "kitchen",
                },
                {
                    "rule_id": "SOP-KITCHEN-004",
                    "name": "食品安全留样",
                    "description": "每餐食品必须留样48小时",
                    "severity": "critical",
                    "check_strategy": "food_safety",
                    "corrective_action": "立即补留样并记录原因",
                    "category": "food_safety",
                    "zone": "kitchen",
                },
            ],
            Zone.WAREHOUSE: [
                {
                    "rule_id": "SOP-WH-001",
                    "name": "冷链温度监控",
                    "description": "冷藏间0~4°C，冷冻间-22~-16°C",
                    "severity": "critical",
                    "check_strategy": "temp_monitor",
                    "threshold": {"min_temp_c": -22.0, "max_temp_c": -16.0, "alarm_duration_sec": 900},
                    "corrective_action": "检查制冷设备，转移食材",
                    "category": "food_safety",
                    "zone": "warehouse",
                },
                {
                    "rule_id": "SOP-WH-002",
                    "name": "FEFO出库规则",
                    "description": "出库必须按先失效先出原则",
                    "severity": "major",
                    "check_strategy": "fefo_check",
                    "corrective_action": "重新按效期排序拣货",
                    "category": "warehouse_op",
                    "zone": "warehouse",
                },
            ],
            Zone.FRONT: [
                {
                    "rule_id": "SOP-FRONT-001",
                    "name": "及时清理餐桌",
                    "description": "顾客离桌10分钟内完成清理",
                    "severity": "minor",
                    "check_strategy": "table_cleanup",
                    "threshold": {"idle_min": 10},
                    "corrective_action": "立即安排清理",
                    "category": "service_std",
                    "zone": "front",
                },
                {
                    "rule_id": "SOP-FRONT-002",
                    "name": "主动迎宾",
                    "description": "顾客进门30秒内完成迎宾",
                    "severity": "info",
                    "check_strategy": "greeting_std",
                    "threshold": {"response_sec": 30},
                    "corrective_action": "加强前厅培训",
                    "category": "service_std",
                    "zone": "front",
                },
            ],
            Zone.DINING: [],
        }

        return [SOPRule(**r) for r in defaults.get(zone, [])]

    @staticmethod
    def _calculate_score(passed: int, failed: int, pending: int, violations: List[ViolationItem]) -> float:
        """计算合规分(0~100).

        权重: 通过=满分, 未通过=-扣分(按严重程度), 待检=-2分
        """
        total = passed + failed + pending
        if total == 0:
            return 100.0

        score = passed * 100.0
        for v in violations:
            if v.severity == Severity.CRITICAL:
                score -= 25
            elif v.severity == Severity.MAJOR:
                score -= 15
            elif v.severity == Severity.MINOR:
                score -= 5
            else:
                score -= 2
        score -= pending * 2

        return max(0.0, round(score / total, 1))

    def _push_alerts(self, report: ComplianceReport) -> None:
        """推送违规告警到EventHub."""
        if not self._hub:
            return
        try:
            for v in report.violations:
                level = "critical" if v.severity == Severity.CRITICAL else "warn"
                self._hub.post_event({
                    "event_type": "sop_violation",
                    "source": "sop_engine",
                    "level": level,
                    "store_id": report.store_id,
                    "zone": _enum_val(report.zone),
                    "message": f"SOP违规[{v.severity}]: {v.rule_name}",
                    "metadata": {
                        "rule_id": v.rule_id,
                        "suggested_action": v.suggested_action,
                        "evidence_ref": v.evidence_ref,
                    },
                })
        except Exception as exc:
            logger.error("Push alert failed: %s", exc)

    def _query_history(self, store_id: str, days: int) -> List[Dict[str, Any]]:
        """查询历史合规分数(从DB或返回空)."""
        if not self._db:
            return []
        try:
            cursor = self._db.cursor()
            cursor.execute(
                "SELECT check_date, zone, compliance_score FROM sop_check_history "
                "WHERE store_id = ? AND check_date >= date('now', ?) "
                "ORDER BY check_date DESC",
                (store_id, f"-{days} days"),
            )
            rows = cursor.fetchall()
            # 按日期聚合
            by_date: Dict[str, Dict] = {}
            for row in rows:
                d = str(row[0]) if row[0] else ""
                if d not in by_date:
                    by_date[d] = {"date": d, "score": 0, "by_zone": {}, "count": 0}
                by_date[d]["score"] += row[2] or 0
                by_date[d]["by_zone"][row[1]] = row[2]
                by_date[d]["count"] += 1
            # 平均
            for d in by_date.values():
                if d["count"] > 0:
                    d["score"] = round(d["score"] / d["count"], 1)
            return sorted(by_date.values(), key=lambda x: x["date"], reverse=True)
        except Exception:
            return []

    @staticmethod
    def _top_violations(store_id: str, days: int) -> List[Dict[str, Any]]:
        """返回Top高频违规(简化版, 实际应从DB统计)."""
        return [
            {"rule_name": "厨师必须佩戴口罩", "count": 5, "repeat_rate": 0.25},
            {"rule_name": "操作前洗手消毒", "count": 3, "repeat_rate": 0.15},
            {"rule_name": "冷链温度监控", "count": 1, "repeat_rate": 0.05},
        ]
