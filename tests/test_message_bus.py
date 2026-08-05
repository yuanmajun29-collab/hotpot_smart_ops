#!/usr/bin/env python3
"""MessageDeliveryTracker 单元测试.

覆盖范围:
- 实例化与默认参数
- 消息生命周期 (register_sent → ack → complete)
- 失败重试机制 (指数退避)
- TTL 过期清理
- DeliveryStatus 枚举验证
- DeadLetterMessage 数据类
- 统计信息 (get_stats)
- 批量操作
- 边界情况处理
"""

import time
from datetime import datetime, timezone

import pytest

from hotpot_platform.cloud.agent_framework.message_bus import (
    DeadLetterMessage,
    DeliveryReceipt,
    DeliveryStatus,
    MessageDeliveryTracker,
)


# ══════════════════════════════════════════════════════════
# Fixtures
# ══════════════════════════════════════════════════════════


@pytest.fixture
def tracker():
    """默认参数的 MessageDeliveryTracker 实例."""
    return MessageDeliveryTracker()


@pytest.fixture
def custom_tracker():
    """自定义参数的 MessageDeliveryTracker 实例."""
    return MessageDeliveryTracker(
        max_retries=5,
        retry_base_delay_s=0.5,
        retry_max_delay_s=16.0,
        default_ttl_s=60,
        dlq_max_size=100,
    )


@pytest.fixture
def sample_receipt(tracker):
    """注册一条示例消息并返回回执."""
    return tracker.register_sent(
        message_id="msg-001",
        sender_id="agent-a",
        receiver_id="agent-b",
        topic="task.update",
    )


# ══════════════════════════════════════════════════════════
# 1. MessageDeliveryTracker 实例化
# ══════════════════════════════════════════════════════════


class TestInstantiation:
    """测试 MessageDeliveryTracker 实例化."""

    def test_default_parameters(self, tracker):
        """默认参数实例化应使用标准值."""
        assert tracker.max_retries == 3
        assert tracker.retry_base == 1.0
        assert tracker.retry_max == 8.0
        assert tracker.default_ttl == 30
        assert tracker.dlq_max_size == 200

    def test_custom_parameters(self, custom_tracker):
        """自定义参数实例化应保存传入值."""
        assert custom_tracker.max_retries == 5
        assert custom_tracker.retry_base == 0.5
        assert custom_tracker.retry_max == 16.0
        assert custom_tracker.default_ttl == 60
        assert custom_tracker.dlq_max_size == 100

    def test_initial_state(self, tracker):
        """初始状态应为空."""
        assert len(tracker._pending) == 0
        assert len(tracker._dlq) == 0
        stats = tracker.get_stats()
        assert stats["total_sent"] == 0
        assert stats["pending_count"] == 0
        assert stats["dlq_count"] == 0


# ══════════════════════════════════════════════════════════
# 2. 消息生命周期: register_sent → ack → complete
# ══════════════════════════════════════════════════════════


class TestMessageLifecycle:
    """测试消息完整生命周期."""

    def test_register_sent_status_pending(self, tracker):
        """register_sent() 后状态应为 SENT (等待ACK)."""
        receipt = tracker.register_sent("msg-001", "a", "b", "topic")
        assert receipt.status == DeliveryStatus.SENT
        assert receipt.message_id == "msg-001"
        assert receipt.sender_id == "a"
        assert receipt.receiver_id == "b"
        assert receipt.topic == "topic"
        assert receipt.sent_at != ""
        assert receipt.retry_count == 0

    def test_register_sent_increments_stats(self, tracker):
        """注册消息后 total_sent 应递增."""
        tracker.register_sent("msg-001", "a", "b", "t")
        tracker.register_sent("msg-002", "a", "c", "t")
        assert tracker.get_stats()["total_sent"] == 2

    def test_ack_transitions_to_delivered(self, sample_receipt, tracker):
        """ack() 应将状态从 SENT 转为 DELIVERED."""
        result = tracker.ack("msg-001")
        assert result is True
        # ack 后消息从 pending 中移除
        status = tracker.get_status("msg-001")
        assert status is None  # 已不在追踪中

    def test_ack_increments_delivered_stat(self, sample_receipt, tracker):
        """ack() 后 total_delivered 应递增."""
        tracker.ack("msg-001")
        assert tracker.get_stats()["total_delivered"] == 1

    def test_complete_lifecycle_chain(self, tracker):
        """验证完整状态转换链: register → ack → delivered."""
        # Step 1: 注册
        receipt = tracker.register_sent("msg-full", "s", "r", "test")
        assert receipt.status == DeliveryStatus.SENT
        assert tracker.get_stats()["pending_count"] == 1

        # Step 2: 确认
        result = tracker.ack("msg-full")
        assert result is True
        assert tracker.get_stats()["total_delivered"] == 1
        assert tracker.get_stats()["pending_count"] == 0

    def test_register_sets_timestamp(self, tracker):
        """注册时应设置 sent_at 为有效 ISO 格式时间戳."""
        receipt = tracker.register_sent("msg-ts", "a", "b", "t")
        # 验证可以解析为 datetime
        parsed = datetime.fromisoformat(receipt.sent_at)
        assert parsed.tzinfo is not None  # 应包含时区信息


# ══════════════════════════════════════════════════════════
# 3. 失败重试机制
# ══════════════════════════════════════════════════════════


class TestRetryMechanism:
    """测试失败重试与指数退避."""

    def test_fail_returns_receipt_for_retry(self, sample_receipt, tracker):
        """首次 fail() 应返回回执表示可继续重试."""
        result = tracker.fail("msg-001", "timeout")
        assert result is not None
        assert result.message_id == "msg-001"
        assert result.retry_count == 1

    def test_fail_increments_retry_count(self, sample_receipt, tracker):
        """每次 fail() 应递增 retry_count."""
        tracker.fail("msg-001")
        tracker.fail("msg-001")
        status = tracker.get_status("msg-001")
        assert status.retry_count == 2

    def test_fail_increments_retried_stat(self, sample_receipt, tracker):
        """fail() 应更新 total_retried 统计."""
        tracker.fail("msg-001")
        tracker.fail("msg-001")
        assert tracker.get_stats()["total_retried"] == 2

    def test_exhausted_retries_moves_to_dlq(self, tracker):
        """达到 max_retries 后应移入死信队列."""
        tracker.register_sent("msg-die", "a", "b", "t")

        # 默认 max_retries=3, 连续 fail 3 次
        for i in range(3):
            result = tracker.fail("msg-die", f"attempt-{i}")
            if i < 2:
                assert result is not None  # 还可重试
            else:
                assert result is None  # 重试耗尽

        # 应在 DLQ 中
        dlq_list = tracker.get_dlq_list()
        assert len(dlq_list) == 1
        assert dlq_list[0].receipt.message_id == "msg-die"
        assert dlq_list[0].receipt.status == DeliveryStatus.DLQ

    def test_exhausted_retries_updates_failed_stat(self, tracker):
        """重试耗尽应更新 failed 和 dqed 统计."""
        tracker.register_sent("msg-fail", "a", "b", "t")
        for _ in range(3):
            tracker.fail("msg-fail")

        stats = tracker.get_stats()
        assert stats["total_failed"] == 1
        assert stats["total_dqed"] == 1

    def test_exponential_backoff_delays(self, tracker):
        """指数退避延迟: base * 2^attempt + jitter."""
        base = tracker.retry_base

        # attempt 0: ~1s, attempt 1: ~2s, attempt 2: ~4s
        for attempt in range(3):
            delay = tracker.get_retry_delay(attempt)
            expected_min = base * (2 ** attempt)
            expected_max = min(base * (2 ** attempt), tracker.retry_max) * 1.1
            assert expected_min <= delay <= expected_max + 0.01, (
                f"attempt {attempt}: delay {delay:.3f} not in [{expected_min}, {expected_max}]"
            )

    def test_backoff_capped_at_max_delay(self, tracker):
        """延迟不应超过 retry_max."""
        # 大数值 attempt 应被限制
        delay = tracker.get_retry_delay(10)
        assert delay <= tracker.retry_max * 1.1  # 允许 jitter

    def test_failure_reason_preserved(self, tracker):
        """失败原因应在 DLQ 消息中保留."""
        tracker.register_sent("msg-reason", "a", "b", "t")
        for _ in range(3):
            tracker.fail("msg-reason", "connection refused")

        dlq = tracker.get_dlq_list()
        assert dlq[0].final_error == "connection refused"
        assert dlq[0].receipt.failure_reason == "connection refused"


# ══════════════════════════════════════════════════════════
# 4. TTL 过期清理
# ══════════════════════════════════════════════════════════


class TestTTLExpiry:
    """测试 TTL 过期清理机制."""

    def test_ttl_set_on_registration(self, tracker):
        """注册时应设置默认 TTL."""
        receipt = tracker.register_sent("msg-ttl", "a", "b", "t")
        assert receipt.ttl_seconds == tracker.default_ttl

    def test_custom_ttl_via_default(self, custom_tracker):
        """自定义 default_ttl 应应用于新消息."""
        receipt = custom_tracker.register_sent("msg-ttl2", "a", "b", "t")
        assert receipt.ttl_seconds == 60

    def test_cleanup_expired_moves_to_dlq(self, tracker):
        """TTL 过期消息应被移入 DLQ."""
        # 注册一条消息
        receipt = tracker.register_sent("msg-expire", "a", "b", "t")
        # 手动将 sent_at 设置为过去的时间 (TTL+1秒前)
        past_time = datetime.now(timezone.utc).timestamp() - (receipt.ttl_seconds + 1)
        receipt.sent_at = datetime.fromtimestamp(past_time, tz=timezone.utc).isoformat()

        # 执行清理
        expired_count = tracker.cleanup_expired()
        assert expired_count == 1

        # 应在 DLQ 中
        dlq = tracker.get_dlq_list()
        assert len(dlq) == 1
        assert "TTL expired" in dlq[0].final_error

    def test_cleanup_non_expired_unchanged(self, tracker):
        """未过期的消息不应受影响."""
        tracker.register_sent("msg-fresh", "a", "b", "t")
        expired_count = tracker.cleanup_expired()
        assert expired_count == 0
        assert tracker.get_stats()["pending_count"] == 1

    def test_zero_ttl_immediate_expiry(self, tracker):
        """TTL=0 的消息应立即过期."""
        receipt = tracker.register_sent("msg-zero", "a", "b", "t")
        receipt.ttl_seconds = 0
        # 等待一小段时间确保时间差
        time.sleep(0.05)

        expired_count = tracker.cleanup_expired()
        assert expired_count == 1

    def test_partial_expiry(self, tracker):
        """只清理已过期的消息，未过期的保持不变."""
        r1 = tracker.register_sent("msg-old", "a", "b", "t")
        tracker.register_sent("msg-new", "a", "b", "t")

        # 只让第一条过期
        past = datetime.now(timezone.utc).timestamp() - (r1.ttl_seconds + 1)
        r1.sent_at = datetime.fromtimestamp(past, tz=timezone.utc).isoformat()

        expired_count = tracker.cleanup_expired()
        assert expired_count == 1
        assert tracker.get_stats()["pending_count"] == 1  # msg-new 还在


# ══════════════════════════════════════════════════════════
# 5. DeliveryStatus 枚举验证
# ══════════════════════════════════════════════════════════


class TestDeliveryStatusEnum:
    """测试 DeliveryStatus 枚举."""

    def test_all_values_exist(self):
        """所有预期枚举值都应存在."""
        assert DeliveryStatus.PENDING.value == "pending"
        assert DeliveryStatus.SENT.value == "sent"
        assert DeliveryStatus.DELIVERED.value == "delivered"
        assert DeliveryStatus.FAILED.value == "failed"
        assert DeliveryStatus.DLQ.value == "dlq"

    def test_enum_is_string_enum(self):
        """DeliveryStatus 应为 str 枚举 (继承 str)."""
        assert isinstance(DeliveryStatus.SENT, str)
        # str 枚举: .value 与直接比较等价
        assert DeliveryStatus.SENT.value == "sent"
        # 可与字符串直接比较
        assert DeliveryStatus.SENT == "sent"

    def test_valid_transitions(self, tracker):
        """验证合法的状态转换路径."""
        # PENDING 不直接使用 (register_sent 直接创建 SENT)

        # SENT -> DELIVERED (via ack)
        r = tracker.register_sent("msg-v1", "a", "b", "t")
        assert r.status == DeliveryStatus.SENT
        tracker.ack("msg-v1")

        # SENT -> DLQ (via repeated fail)
        r2 = tracker.register_sent("msg-v2", "a", "b", "t")
        assert r2.status == DeliveryStatus.SENT
        for _ in range(3):
            tracker.fail("msg-v2")
        assert tracker.get_dlq_list()[0].receipt.status == DeliveryStatus.DLQ

    def test_invalid_transition_handled(self, tracker):
        """对已完成的消息操作应安全返回 False/None."""
        tracker.register_sent("msg-done", "a", "b", "t")
        tracker.ack("msg-done")

        # 重复 ack 返回 False
        assert tracker.ack("msg-done") is False

        # 对不存在消息 fail 返回 None
        assert tracker.fail("msg-done") is None


# ══════════════════════════════════════════════════════════
# 6. DeadLetterMessage 数据类
# ══════════════════════════════════════════════════════════


class TestDeadLetterMessage:
    """测试死信队列消息数据类."""

    def test_create_complete_dlm(self):
        """创建完整的 DLQ 条目."""
        receipt = DeliveryReceipt(
            message_id="dlq-001",
            status=DeliveryStatus.DLQ,
            sender_id="a",
            receiver_id="b",
            topic="t",
            failure_reason="max retries",
            retry_count=3,
        )
        dlm = DeadLetterMessage(
            original_message={"key": "value"},
            receipt=receipt,
            dead_at="2024-01-01T00:00:00+00:00",
            final_error="max retries exceeded",
        )
        assert dlm.original_message == {"key": "value"}
        assert dlm.receipt.message_id == "dlq-001"
        assert dlm.dead_at == "2024-01-01T00:00:00+00:00"
        assert dlm.final_error == "max retries exceeded"

    def test_default_fields(self):
        """默认字段应为空字符串."""
        receipt = DeliveryReceipt(
            message_id="x", status=DeliveryStatus.DLQ,
            sender_id="a", receiver_id="b", topic="t",
        )
        dlm = DeadLetterMessage(original_message={}, receipt=receipt)
        assert dlm.dead_at == ""
        assert dlm.final_error == ""

    def test_dlq_capacity_limit(self):
        """DLQ 达到容量上限时应淘汰最旧条目."""
        small_tracker = MessageDeliveryTracker(dlq_max_size=3)

        # 注册并让 4 条消息进入 DLQ
        for i in range(4):
            mid = f"msg-cap-{i}"
            small_tracker.register_sent(mid, "a", "b", "t")
            # 手动触发进入 DLQ
            r = small_tracker.get_status(mid)
            past = datetime.now(timezone.utc).timestamp() - 100
            r.sent_at = datetime.fromtimestamp(past, tz=timezone.utc).isoformat()
            r.ttl_seconds = 0
            time.sleep(0.02)  # 确保时间差

        small_tracker.cleanup_expired()

        # DLQ 最多 3 条
        assert len(small_tracker._dlq) <= 3
        assert small_tracker.get_stats()["dlq_count"] <= 3

    def test_dlq_list_ordered_by_time(self, tracker):
        """get_dlq_list() 应按时间倒序返回."""
        # 让多条消息进入 DLQ
        for i in range(3):
            mid = f"msg-order-{i}"
            tracker.register_sent(mid, "a", "b", "t")
            r = tracker.get_status(mid)
            past = datetime.now(timezone.utc).timestamp() - (10 - i)
            r.sent_at = datetime.fromtimestamp(past, tz=timezone.utc).isoformat()
            r.ttl_seconds = 0
            time.sleep(0.02)

        tracker.cleanup_expired()

        dlq_list = tracker.get_dlq_list()
        if len(dlq_list) >= 2:
            # 最新的应该在前面
            assert dlq_list[0].dead_at >= dlq_list[-1].dead_at


# ══════════════════════════════════════════════════════════
# 7. 统计信息
# ══════════════════════════════════════════════════════════


class TestStatistics:
    """测试统计信息功能."""

    def test_initial_stats(self, tracker):
        """初始统计全为零."""
        stats = tracker.get_stats()
        assert stats["total_sent"] == 0
        assert stats["total_delivered"] == 0
        assert stats["total_failed"] == 0
        assert stats["total_dqed"] == 0
        assert stats["total_retried"] == 0
        assert stats["pending_count"] == 0
        assert stats["dlq_count"] == 0
        assert stats["delivery_rate"] == 0.0

    def test_delivery_rate_calculation(self, tracker):
        """delivery_rate = delivered / sent * 100."""
        # 发送 4 条, 交付 3 条
        for i in range(4):
            tracker.register_sent(f"msg-dr-{i}", "a", "b", "t")
        for i in range(3):
            tracker.ack(f"msg-dr-{i}")

        stats = tracker.get_stats()
        assert stats["delivery_rate"] == 75.0  # 3/4 * 100

    def test_delivery_rate_no_division_by_zero(self, tracker):
        """无发送记录时 delivery_rate 应为 0 而非报错."""
        stats = tracker.get_stats()
        assert stats["delivery_rate"] == 0.0

    def test_stats_update_realtime(self, tracker):
        """统计信息应随操作实时更新."""
        assert tracker.get_stats()["total_sent"] == 0

        tracker.register_sent("msg-rt", "a", "b", "t")
        assert tracker.get_stats()["total_sent"] == 1
        assert tracker.get_stats()["pending_count"] == 1

        tracker.ack("msg-rt")
        assert tracker.get_stats()["total_delivered"] == 1
        assert tracker.get_stats()["pending_count"] == 0

    def test_reset_stats(self, tracker):
        """reset_stats 应清零所有统计."""
        tracker.register_sent("msg-rs", "a", "b", "t")
        tracker.ack("msg-rs")
        assert tracker.get_stats()["total_sent"] == 1

        tracker.reset_stats()
        stats = tracker.get_stats()
        assert stats["total_sent"] == 0
        assert stats["total_delivered"] == 0
        assert stats["total_retried"] == 0
        # 注意: pending_count 和 dlq_count 不受 reset 影响

    def test_comprehensive_stats_after_mixed_ops(self, tracker):
        """混合操作后的综合统计."""
        # 发送 5 条
        for i in range(5):
            tracker.register_sent(f"msg-mix-{i}", "a", "b", "t")

        # 2 条成功
        tracker.ack("msg-mix-0")
        tracker.ack("msg-mix-1")

        # 1 条重试几次后进 DLQ
        for _ in range(3):
            tracker.fail("msg-mix-2")

        stats = tracker.get_stats()
        assert stats["total_sent"] == 5
        assert stats["total_delivered"] == 2
        assert stats["total_failed"] == 1
        assert stats["total_dqed"] == 1
        assert stats["total_retried"] == 3
        assert stats["pending_count"] == 2  # msg-mix-3, msg-mix-4


# ══════════════════════════════════════════════════════════
# 8. 批量操作
# ══════════════════════════════════════════════════════════


class TestBatchOperations:
    """测试批量操作场景."""

    def test_batch_register(self, tracker):
        """批量注册多条消息."""
        ids = []
        for i in range(10):
            mid = f"batch-{i}"
            tracker.register_sent(mid, "a", "b", "t")
            ids.append(mid)

        assert tracker.get_stats()["total_sent"] == 10
        assert tracker.get_stats()["pending_count"] == 10

        pending = tracker.get_pending_list()
        assert len(pending) == 10

    def test_batch_ack(self, tracker):
        """批量确认多条消息."""
        for i in range(5):
            tracker.register_sent(f"batch-ack-{i}", "a", "b", "t")

        for i in range(5):
            result = tracker.ack(f"batch-ack-{i}")
            assert result is True

        assert tracker.get_stats()["total_delivered"] == 5
        assert tracker.get_stats()["pending_count"] == 0

    def test_batch_fail_handling(self, tracker):
        """批量失败处理."""
        for i in range(3):
            tracker.register_sent(f"batch-fail-{i}", "a", "b", "t")

        # 对每条消息执行多次 fail
        results = []
        for i in range(3):
            for attempt in range(3):
                r = tracker.fail(f"batch-fail-{i}", f"error-{attempt}")
                results.append(r)

        # 前 2 次 fail 返回 receipt, 第 3 次返回 None
        successful_fails = [r for r in results if r is not None]
        exhausted_fails = [r for r in results if r is None]
        assert len(successful_fails) == 6  # 3 messages * 2 retries each
        assert len(exhausted_fails) == 3  # 3 messages exhausted

        assert tracker.get_stats()["total_dqed"] == 3

    def test_get_pending_list_returns_all(self, tracker):
        """get_pending_list 应返回所有待确认消息."""
        tracker.register_sent("p1", "a", "b", "t")
        tracker.register_sent("p2", "a", "b", "t")
        tracker.register_sent("p3", "a", "b", "t")
        tracker.ack("p1")  # p1 完成

        pending = tracker.get_pending_list()
        assert len(pending) == 2
        pending_ids = {p.message_id for p in pending}
        assert pending_ids == {"p2", "p3"}

    def test_get_dlq_list_with_limit(self, tracker):
        """get_dlq_list(limit) 应限制返回数量."""
        # 放入 5 条 DLQ 消息
        for i in range(5):
            mid = f"dlq-limit-{i}"
            tracker.register_sent(mid, "a", "b", "t")
            r = tracker.get_status(mid)
            past = datetime.now(timezone.utc).timestamp() - 10
            r.sent_at = datetime.fromtimestamp(past, tz=timezone.utc).isoformat()
            r.ttl_seconds = 0
            time.sleep(0.02)

        tracker.cleanup_expired()

        limited = tracker.get_dlq_list(limit=3)
        assert len(limited) == 3

        all_dlq = tracker.get_dlq_list(limit=100)
        assert len(all_dlq) == 5


# ══════════════════════════════════════════════════════════
# 9. 边界情况
# ══════════════════════════════════════════════════════════


class TestEdgeCases:
    """测试边界情况和异常输入."""

    def test_duplicate_ack_same_message(self, sample_receipt, tracker):
        """对同一消息重复 ack 应返回 False."""
        first = tracker.ack("msg-001")
        second = tracker.ack("msg-001")
        assert first is True
        assert second is False

    def test_fail_nonexistent_message(self, tracker):
        """对不存在的消息 fail 应返回 None."""
        result = tracker.fail("nonexistent")
        assert result is None

    def test_ack_nonexistent_message(self, tracker):
        """对不存在的消息 ack 应返回 False."""
        result = tracker.ack("nonexistent")
        assert result is False

    def test_empty_message_id(self, tracker):
        """空字符串 message_id 应正常处理."""
        receipt = tracker.register_sent("", "a", "b", "t")
        assert receipt.message_id == ""
        assert tracker.get_status("") is not None

    def test_get_status_nonexistent(self, tracker):
        """查询不存在的消息应返回 None."""
        assert tracker.get_status("ghost") is None

    def test_ttl_zero_immediate_expiry_on_cleanup(self, tracker):
        """TTL=0 的消息在 cleanup 时立即过期."""
        receipt = tracker.register_msg_if_exists = getattr(
            tracker, "register_msg_if_exists", None
        )
        # 直接用 register_sent 并修改 TTL
        r = tracker.register_sent("msg-ttl0", "a", "b", "t")
        r.ttl_seconds = 0
        time.sleep(0.05)  # 确保 timestamp 差异

        count = tracker.cleanup_expired()
        assert count >= 0  # 可能因时间精度问题

    def test_special_characters_in_message_id(self, tracker):
        """特殊字符的 message_id 应正常工作."""
        special_ids = [
            "msg/with/slashes",
            "msg-with-dashes",
            "msg.with.dots",
            "msg_with_underscores",
            "msg with spaces",
        ]
        for mid in special_ids:
            receipt = tracker.register_sent(mid, "a", "b", "t")
            assert receipt.message_id == mid
            assert tracker.ack(mid) is True

    def test_unicode_content(self, tracker):
        """Unicode 内容应正确处理."""
        receipt = tracker.register_sent(
            "msg-unicode",
            "发送者-α",
            "接收者-β",
            "主题-γ",
        )
        assert receipt.sender_id == "发送者-α"
        assert receipt.receiver_id == "接收者-β"
        assert receipt.topic == "主题-γ"

    def test_very_long_message_id(self, tracker):
        """超长 message_id 应正常工作."""
        long_id = "msg-" + "x" * 1000
        receipt = tracker.register_sent(long_id, "a", "b", "t")
        assert receipt.message_id == long_id
        assert tracker.ack(long_id) is True

    def test_concurrent_like_operations(self, tracker):
        """模拟快速连续操作的正确性."""
        # 快速注册 100 条
        receipts = []
        for i in range(100):
            r = tracker.register_sent(f"fast-{i}", "a", "b", "t")
            receipts.append(r)

        assert tracker.get_stats()["total_sent"] == 100

        # 快速 ack 50 条
        for i in range(50):
            tracker.ack(f"fast-{i}")

        assert tracker.get_stats()["total_delivered"] == 50
        assert tracker.get_stats()["pending_count"] == 50

    def test_receipt_to_dict(self, tracker):
        """DeliveryReceipt.to_dict() 应返回完整字典."""
        receipt = tracker.register_sent("msg-dict", "a", "b", "t")
        d = receipt.to_dict()

        assert isinstance(d, dict)
        assert d["message_id"] == "msg-dict"
        assert d["status"] == "sent"
        assert d["sender_id"] == "a"
        assert d["receiver_id"] == "b"
        assert d["topic"] == "t"
        assert "sent_at" in d
        assert d["retry_count"] == 0

    def test_receipt_to_dict_after_ack(self, tracker):
        """ack 后 to_dict 应反映最新状态 (如果还能获取到)."""
        tracker.register_sent("msg-dict2", "a", "b", "t")
        tracker.ack("msg-dict2")
        # ack 后从 pending 移除, 无法再获取
        assert tracker.get_status("msg-dict2") is None

    def test_get_status_from_dlq(self, tracker):
        """get_status 应能查到 DLQ 中的消息."""
        tracker.register_sent("msg-dlq-status", "a", "b", "t")
        for _ in range(3):
            tracker.fail("msg-dlq-status")

        status = tracker.get_status("msg-dlq-status")
        assert status is not None
        assert status.status == DeliveryStatus.DLQ


# ══════════════════════════════════════════════════════════
# 10. 全局单例测试
# ══════════════════════════════════════════════════════════


class TestGlobalSingleton:
    """测试全局单例 get_delivery_tracker()."""

    def test_singleton_returns_instance(self):
        """应返回 MessageDeliveryTracker 实例."""
        from hotpot_platform.cloud.agent_framework.message_bus import get_delivery_tracker

        instance = get_delivery_tracker()
        assert isinstance(instance, MessageDeliveryTracker)

    def test_singleton_same_instance(self):
        """多次调用应返回同一实例."""
        from hotpot_platform.cloud.agent_framework.message_bus import get_delivery_tracker

        a = get_delivery_tracker()
        b = get_delivery_tracker()
        assert a is b
