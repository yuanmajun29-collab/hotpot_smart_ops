#!/usr/bin/env python3
"""消息送达回执机制 (P1-06).

模块:
- DeliveryStatus: 消息送达状态枚举
- DeliveryReceipt: 送达回执数据类
- DeadLetterMessage: 死信队列消息
- MessageDeliveryTracker: 消息送达追踪器 (ACK/重试/DLQ/统计)

功能:
1. 消息发送后等待 ACK 回执
2. 超时重试 (指数退避: 1s → 2s → 4s → 8s, 最多3次)
3. 死信队列 (DLQ) 投递 — 超过最大重试次数的消息
4. 送达状态追踪 (delivered / failed / pending)
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════
# P1-06: 消息送达回执机制
# ══════════════════════════════════════════════════════════


class DeliveryStatus(str, Enum):
    """消息送达状态"""
    PENDING = "pending"       # 待发送
    SENT = "sent"             # 已发送，等待ACK
    DELIVERED = "delivered"   # 已送达 (收到ACK)
    FAILED = "failed"         # 最终失败 (重试耗尽)
    DLQ = "dlq"               # 死信队列


@dataclass
class DeliveryReceipt:
    """送达回执"""
    message_id: str
    status: DeliveryStatus
    sender_id: str
    receiver_id: str
    topic: str
    sent_at: str = ""
    delivered_at: str = ""
    failed_at: str = ""
    failure_reason: str = ""
    retry_count: int = 0
    ttl_seconds: int = 30  # 消息生存时间

    def to_dict(self) -> Dict[str, Any]:
        return {
            "message_id": self.message_id,
            "status": self.status.value,
            "sender_id": self.sender_id,
            "receiver_id": self.receiver_id,
            "topic": self.topic,
            "sent_at": self.sent_at,
            "delivered_at": self.delivered_at,
            "failed_at": self.failed_at,
            "failure_reason": self.failure_reason,
            "retry_count": self.retry_count,
        }


@dataclass
class DeadLetterMessage:
    """死信队列中的消息"""
    original_message: Dict[str, Any]
    receipt: DeliveryReceipt
    dead_at: str = ""
    final_error: str = ""


class MessageDeliveryTracker:
    """消息送达追踪器

    功能:
    - 发送时注册待确认消息
    - 收到 ACK 时标记为 delivered
    - 超时未 ACK 触发重试
    - 重试耗尽转入死信队列 (DLQ)
    """

    def __init__(
        self,
        max_retries: int = 3,
        retry_base_delay_s: float = 1.0,
        retry_max_delay_s: float = 8.0,
        default_ttl_s: int = 30,
        dlq_max_size: int = 200,
    ):
        self.max_retries = max_retries
        self.retry_base = retry_base_delay_s
        self.retry_max = retry_max_delay_s
        self.default_ttl = default_ttl_s
        self.dlq_max_size = dlq_max_size

        # { message_id -> DeliveryReceipt }
        self._pending: Dict[str, DeliveryReceipt] = {}

        # { message_id -> DeadLetterMessage }
        self._dlq: Dict[str, DeadLetterMessage] = {}

        # 统计
        self._stats = {
            "total_sent": 0,
            "total_delivered": 0,
            "total_failed": 0,
            "total_dqed": 0,
            "total_retried": 0,
        }

    def register_sent(self, message_id: str, sender_id: str, receiver_id: str, topic: str) -> DeliveryReceipt:
        """注册已发送的消息 (等待ACK)"""
        now = datetime.now(timezone.utc).isoformat()
        receipt = DeliveryReceipt(
            message_id=message_id,
            status=DeliveryStatus.SENT,
            sender_id=sender_id,
            receiver_id=receiver_id,
            topic=topic,
            sent_at=now,
            ttl_seconds=self.default_ttl,
        )
        self._pending[message_id] = receipt
        self._stats["total_sent"] += 1
        return receipt

    def ack(self, message_id: str) -> bool:
        """确认消息送达"""
        if message_id not in self._pending:
            return False

        receipt = self._pending.pop(message_id)
        receipt.status = DeliveryStatus.DELIVERED
        receipt.delivered_at = datetime.now(timezone.utc).isoformat()
        self._stats["total_delivered"] += 1
        return True

    def fail(self, message_id: str, reason: str = "") -> Optional[DeliveryReceipt]:
        """标记单次失败 (返回是否应继续重试)"""
        if message_id not in self._pending:
            return None

        receipt = self._pending[message_id]
        receipt.retry_count += 1
        self._stats["total_retried"] += 1

        if receipt.retry_count >= self.max_retries:
            # 重试耗尽 → 死信队列
            self._move_to_dlq(receipt, reason or "Max retries exceeded")
            return None  # 不再重试

        return receipt  # 还可以重试

    def _move_to_dlq(self, receipt: DeliveryReceipt, reason: str):
        """将消息移入死信队列"""
        receipt.status = DeliveryStatus.DLQ
        receipt.failed_at = datetime.now(timezone.utc).isoformat()
        receipt.failure_reason = reason

        dlm = DeadLetterMessage(
            original_message={},  # 可由调用方填充
            receipt=receipt,
            dead_at=receipt.failed_at,
            final_error=reason,
        )

        # DLQ 容量限制
        if len(self._dlq) >= self.dlq_max_size:
            # 移除最旧的死信
            oldest_key = min(self._dlq.keys(), key=lambda k: self._dlq[k].dead_at)
            del self._dlq[oldest_key]

        self._dlq[receipt.message_id] = dlm
        self._pending.pop(receipt.message_id, None)
        self._stats["total_dqed"] += 1
        self._stats["total_failed"] += 1

        logger.warning(
            "[DLQ] 消息进入死信队列: id=%s %s→%s topic=%s (重试%d次): %s",
            receipt.message_id, receipt.sender_id, receipt.receiver_id,
            receipt.topic, receipt.retry_count, reason,
        )

    def get_retry_delay(self, retry_count: int) -> float:
        """计算重试延迟 (指数退避 + 抖动)"""
        import random
        delay = min(self.retry_base * (2 ** retry_count), self.retry_max)
        jitter = random.uniform(0, delay * 0.1)  # ±10% 抖动
        return delay + jitter

    def get_status(self, message_id: str) -> Optional[DeliveryReceipt]:
        """查询单条消息状态"""
        if message_id in self._pending:
            return self._pending[message_id]
        if message_id in self._dlq:
            return self._dlq[message_id].receipt
        return None

    def get_pending_list(self) -> List[DeliveryReceipt]:
        """获取所有待确认消息"""
        return list(self._pending.values())

    def get_dlq_list(self, limit: int = 50) -> List[DeadLetterMessage]:
        """获取死信队列 (最近N条)"""
        items = sorted(self._dlq.values(), key=lambda x: x.dead_at, reverse=True)
        return items[:limit]

    def cleanup_expired(self) -> int:
        """清理超时的 pending 消息 (移入DLQ)"""
        now = time.time()
        expired = [
            (mid, r) for mid, r in self._pending.items()
            if (datetime.fromisoformat(r.sent_at).timestamp() + r.ttl_seconds) < now
        ]

        for mid, receipt in expired:
            self._move_to_dlq(receipt, f"TTL expired ({receipt.ttl_seconds}s)")

        return len(expired)

    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        return {
            **self._stats,
            "pending_count": len(self._pending),
            "dlq_count": len(self._dlq),
            "delivery_rate": round(
                self._stats["total_delivered"] / max(self._stats["total_sent"], 1) * 100, 1
            ),
        }

    def reset_stats(self):
        """重置统计"""
        self._stats = {k: 0 for k in self._stats}


# 全局默认实例
_tracker: Optional[MessageDeliveryTracker] = None


def get_delivery_tracker() -> MessageDeliveryTracker:
    """获取全局送达追踪器实例"""
    global _tracker
    if _tracker is None:
        _tracker = MessageDeliveryTracker()
    return _tracker
