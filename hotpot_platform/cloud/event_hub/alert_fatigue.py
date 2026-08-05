"""
告警疲劳保护模块 (P1-05)

功能:
1. 事件频率限制 — 同一类型事件在窗口期内去重/合并
2. 告警升级策略 — 连续N次触发后自动提升 severity
3. 静默期配置 — 冷却时间，防止同一问题反复告警
4. 用户自定义阈值 — 按事件类型/摄像头/区域设置不同策略

设计原则:
- 无状态设计: 可多实例部署，不依赖外部存储
- 线程安全: 使用 threading.Lock 保护内部状态
- 可配置: 所有时限/阈值可通过构造函数参数调整

使用方式:
    from hotpot_platform.cloud.event_hub.alert_fatigue import AlertFatigueGuard

    guard = AlertFatigueGuard()

    # 处理事件前先检查
    result = guard.check(event_type, event_key, severity)
    if result.action == "DROP":
        return  # 丢弃重复告警
    elif result.action == "ESCALATE":
        severity = result.effective_severity  # 升级后的级别
    # 正常处理...
"""

from __future__ import annotations

import logging
import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class FatigueAction(str, Enum):
    """告警疲劳保护动作"""
    PASS = "pass"           # 正常放行
    DROP = "drop"           # 丢弃 (冷却期内)
    MERGE = "merge"         # 合并 (累计计数)
    ESCALATE = "escalate"   # 升级严重级别


@dataclass
class FatigueCheckResult:
    """疲劳检查结果"""
    action: FatigueAction
    should_send: bool       # 是否应该发送通知
    effective_severity: str = ""  # 升级后的严重级别
    reason: str = ""
    window_count: int = 0          # 当前窗口内累计次数
    total_suppressed: int = 0      # 本次被抑制的次数
    cooldown_remaining_s: float = 0.0  # 冷却剩余秒数


@dataclass
class EventTypePolicy:
    """单类事件的疲劳保护策略"""
    window_seconds: int = 60      # 滑动窗口大小(秒)
    max_per_window: int = 3        # 窗口内最大允许次数
    cooldown_seconds: int = 300    # 触发上限后的静默期(秒)
    escalate_after: int = 5        # 连续触发多少次后升级
    escalate_to: str = "critical"  # 升级目标级别
    merge_enabled: bool = True     # 是否启用合并模式


# ── 默认策略配置 ──

DEFAULT_POLICIES: Dict[str, EventTypePolicy] = {
    # 后厨废料检测 — 较高频，适度限制
    "waste_detected": EventTypePolicy(
        window_seconds=60, max_per_window=5, cooldown_seconds=180,
        escalate_after=10, escalate_to="critical",
    ),
    # 脏桌检测 — 中频
    "table_dirty": EventTypePolicy(
        window_seconds=120, max_per_window=3, cooldown_seconds=300,
        escalate_after=5, escalate_to="warning",
    ),
    # SOP违规 — 低频但重要
    "sop_violation": EventTypePolicy(
        window_seconds=300, max_per_window=2, cooldown_seconds=600,
        escalate_after=3, escalate_to="critical",
    ),
    # 温度异常 — 高频但需关注
    "temp_anomaly": EventTypePolicy(
        window_seconds=30, max_per_window=10, cooldown_seconds=120,
        escalate_after=15, escalate_to="error",
    ),
    # 收货异常 — 低频
    "receiving_anomaly": EventTypePolicy(
        window_seconds=600, max_per_window=2, cooldown_seconds=900,
        escalate_after=3, escalate_to="error",
    ),
    # 默认策略 — 用于未明确配置的事件类型
    "__default__": EventTypePolicy(
        window_seconds=60, max_per_window=3, cooldown_seconds=300,
        escalate_after=8, escalate_to="warning",
    ),
}


class AlertFatigueGuard:
    """告警疲劳保护器

    核心机制:
    1. 滑动窗口计数: 每个 (event_type, event_key) 组合维护一个时间窗口内的触发次数
    2. 静默期: 超过 max_per_window 后进入 cooldown，期间所有同类事件被丢弃
    3. 升级: 同一 key 连续触发 escalate_after 次后自动提升 severity
    4. 合并: 在窗口内的事件被合并计数，只发送一次通知但附带 count
    """

    def __init__(
        self,
        policies: Optional[Dict[str, EventTypePolicy]] = None,
        enable_global_stats: bool = True,
    ):
        self._policies = policies or dict(DEFAULT_POLICIES)
        self._enable_stats = enable_global_stats

        # 内部状态
        self._lock = threading.RLock()  # 可重入锁: get_status()等方法在持锁期间调用get_stats()需重入

        # { (event_type, event_key) -> [ (timestamp, ... ), ... ] } 时间窗口
        self._windows: Dict[tuple, List[float]] = defaultdict(list)

        # { (event_type, event_key) -> int } 连续触发计数 (用于升级判定)
        self._consecutive: Dict[tuple, int] = defaultdict(int)

        # { (event_type, event_key) -> float } 进入静默期的时间点
        self._cooldown_until: Dict[tuple, float] = {}

        # 全局统计
        self._stats = {
            "total_checked": 0,
            "passed": 0,
            "dropped": 0,
            "merged": 0,
            "escalated": 0,
        }

    def _get_policy(self, event_type: str) -> EventTypePolicy:
        """获取事件类型的策略"""
        return self._policies.get(event_type, self._policies.get("__default__", DEFAULT_POLICIES["__default__"]))

    def _cleanup_window(self, key: tuple, policy: EventTypePolicy, now: float):
        """清理过期的时间窗口条目"""
        cutoff = now - policy.window_seconds
        self._windows[key] = [t for t in self._windows[key] if t > cutoff]

    def check(
        self,
        event_type: str,
        event_key: str = "",
        severity: str = "info",
        timestamp: Optional[float] = None,
    ) -> FatigueCheckResult:
        """检查事件是否应该被放行

        Args:
            event_type: 事件类型 (如 waste_detected, table_dirty)
            event_key: 事件唯一标识 (如 camera_id+zone 或 table_id)
            severity: 原始严重级别
            timestamp: 事件时间戳 (默认当前时间)

        Returns:
            FatigueCheckResult 包含动作建议和原因
        """
        if timestamp is None:
            timestamp = time.time()

        with self._lock:
            if self._enable_stats:
                self._stats["total_checked"] += 1

            key = (event_type, event_key)
            policy = self._get_policy(event_type)

            # 1. 检查是否在静默期内
            cooldown_end = self._cooldown_until.get(key, 0)
            if timestamp < cooldown_end:
                remaining = cooldown_end - timestamp
                if self._enable_stats:
                    self._stats["dropped"] += 1
                return FatigueCheckResult(
                    action=FatigueAction.DROP,
                    should_send=False,
                    reason=f"静默期内 (剩余{remaining:.0f}s)",
                    cooldown_remaining_s=remaining,
                )

            # 2. 清理时间窗口
            self._cleanup_window(key, policy, timestamp)

            # 3. 记录本次事件到窗口
            self._windows[key].append(timestamp)
            window_count = len(self._windows[key])
            self._consecutive[key] += 1

            # 4. 判断是否超过窗口上限
            if window_count > policy.max_per_window:
                # 进入静默期
                self._cooldown_until[key] = timestamp + policy.cooldown_seconds

                # 5. 检查是否需要升级
                cons = self._consecutive[key]
                effective_severity = severity
                if cons >= policy.escalate_after:
                    effective_severity = policy.escalate_to
                    if self._enable_stats:
                        self._stats["escalated"] += 1
                    logger.info(
                        "[AlertFatigue] %s[%s] 升级: %s → %s (连续%d次)",
                        event_type, event_key, severity, effective_severity, cons,
                    )

                if policy.merge_enabled:
                    if self._enable_stats:
                        self._stats["merged"] += 1
                    return FatigueCheckResult(
                        action=FatigueAction.MERGE,
                        should_send=True,  # 合并时仍发送一次，但带累计计数
                        effective_severity=effective_severity,
                        reason=f"窗口内第{window_count}次触发 (上限{policy.max_per_window})，已合并并进入静默期",
                        window_count=window_count,
                    )
                else:
                    if self._enable_stats:
                        self._stats["dropped"] += 1
                    return FatigueCheckResult(
                        action=FatigueAction.DROP,
                        should_send=False,
                        reason=f"超过频率上限 ({window_count}/{policy.max_per_window})，已静默",
                        window_count=window_count,
                        cooldown_remaining_s=policy.cooldown_seconds,
                    )

            # 6. 正常放行
            if self._enable_stats:
                self._stats["passed"] += 1

            # 检查是否达到升级阈值 (即使未超频)
            effective_severity = severity
            if self._consecutive[key] >= policy.escalate_after:
                effective_severity = policy.escalate_to
                return FatigueCheckResult(
                    action=FatigueAction.ESCALATE,
                    should_send=True,
                    effective_severity=effective_severity,
                    reason=f"连续{self._consecutive[key]}次触发，已升级为{effective_severity}",
                    window_count=window_count,
                )

            return FatigueCheckResult(
                action=FatigueAction.PASS,
                should_send=True,
                effective_severity=severity,
                window_count=window_count,
            )

    def reset(self, event_type: Optional[str] = None, event_key: Optional[str] = None):
        """重置疲劳状态

        Args:
            event_type: 重置指定类型 (None=全部)
            event_key: 重置指定key (None=该type下全部)
        """
        with self._lock:
            if event_type is None:
                self._windows.clear()
                self._consecutive.clear()
                self._cooldown_until.clear()
                logger.info("[AlertFatigue] 全部状态已重置")
            elif event_key is None:
                keys_to_remove = [k for k in self._windows.keys() if k[0] == event_type]
                for k in keys_to_remove:
                    del self._windows[k]
                    self._consecutive.pop(k, None)
                    self._cooldown_until.pop(k, None)
                logger.info("[AlertFatigue] 类型 %s 的全部状态已重置", event_type)
            else:
                key = (event_type, event_key)
                self._windows.pop(key, None)
                self._consecutive.pop(key, None)
                self._cooldown_until.pop(key, None)
                logger.info("[AlertFatigue] %s[%s] 状态已重置", event_type, event_key)

    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        with self._lock:
            base = dict(self._stats)
            base["active_windows"] = len(self._windows)
            base["in_cooldown"] = len([k for k, v in self._cooldown_until.items() if v > time.time()])
            base["tracked_keys"] = len(self._consecutive)
            return base

    def get_status(self) -> Dict[str, Any]:
        """获取详细状态 (用于运维监控)"""
        with self._lock:
            now = time.time()
            active_cooldowns = {
                f"{k[0]}:{k[1]}": {"until": v, "remaining_s": max(v - now, 0)}
                for k, v in self._cooldown_until.items()
                if v > now
            }
            hot_keys = [
                {"type": k[0], "key": k[1], "count": len(w), "consecutive": self._consecutive.get(k, 0)}
                for k, w in sorted(self._windows.items(), key=lambda x: -len(x[1]))[:10]
            ]
            return {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "policies": list(self._policies.keys()),
                "active_cooldowns": active_cooldowns,
                "hot_keys": hot_keys,
                **self.get_stats(),
            }


# 全局默认实例
_default_guard: Optional[AlertFatigueGuard] = None


def get_alert_guard() -> AlertFatigueGuard:
    """获取全局告警疲劳保护器实例"""
    global _default_guard
    if _default_guard is None:
        _default_guard = AlertFatigueGuard()
    return _default_guard


# 自测
if __name__ == "__main__":
    print("=" * 60)
    print("AlertFatigueGuard 自测")
    print("=" * 60)

    guard = AlertFatigueGuard()

    # 测试1: 前3次应该通过 (max_per_window=3 for default)
    for i in range(3):
        r = guard.check("test_event", "key_01", "info")
        assert r.should_send, f"测试1-{i+1}: 应该通过"
        assert r.action == FatigueAction.PASS
    print("✅ 测试1: 前3次正常放行")

    # 测试2: 第4次应触发合并或静默
    r4 = guard.check("test_event", "key_01", "info")
    assert not r4.should_send or r4.action == FatigueAction.MERGE
    print(f"✅ 测试2: 第4次 → action={r4.action.value}, reason={r4.reason}")

    # 测试3: 静默期内应被丢弃
    r5 = guard.check("test_event", "key_01", "info")
    assert r5.action == FatigueAction.DROP
    assert not r5.should_send
    print(f"✅ 测试3: 静默期内被丢弃: {r5.reason}")

    # 测试4: 不同key不受影响
    r6 = guard.check("test_event", "key_02", "info")
    assert r6.should_send
    print("✅ 测试4: 不同key独立计算")

    # 测试5: 统计正确
    stats = guard.get_stats()
    assert stats["total_checked"] == 6
    assert stats["passed"] >= 3
    print(f"✅ 测试5 统计: {stats}")

    # 测试6: 重置功能
    guard.reset("test_event", "key_01")
    r7 = guard.check("test_event", "key_01", "info")
    assert r7.should_send
    print("✅ 测试6: 重置后恢复正常")

    print("\n🎉 全部自测通过!")
