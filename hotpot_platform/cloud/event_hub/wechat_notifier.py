"""Production WeChat Work webhook notifier."""

from __future__ import annotations

import json
import os
import threading
import time
import urllib.error
import urllib.request
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Deque, Dict, Optional, Tuple

DEFAULT_MAX_RETRIES = 3
DEFAULT_BACKOFF_BASE = 1.0
DEFAULT_RATE_LIMIT = 5
DEFAULT_RATE_WINDOW = 60.0
DEFAULT_TIMEOUT = 10.0


@dataclass
class NotifyStats:
    """Thread-safe counters for notification delivery."""

    sent: int = 0
    failed: int = 0
    retried: int = 0
    rate_limited: int = 0
    last_sent_at: Optional[float] = None
    last_error: Optional[str] = None
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def record_sent(self) -> None:
        with self._lock:
            self.sent += 1
            self.last_sent_at = time.time()

    def record_failed(self, error: str) -> None:
        with self._lock:
            self.failed += 1
            self.last_error = error

    def record_retry(self) -> None:
        with self._lock:
            self.retried += 1

    def record_rate_limited(self) -> None:
        with self._lock:
            self.rate_limited += 1

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "sent": self.sent,
                "failed": self.failed,
                "retried": self.retried,
                "rate_limited": self.rate_limited,
                "last_sent_at": (
                    datetime.fromtimestamp(self.last_sent_at, tz=timezone.utc).isoformat()
                    if self.last_sent_at
                    else None
                ),
                "last_error": self.last_error,
            }


class WechatNotifier:
    """WeChat Work webhook client with retry, rate limiting, and batching."""

    def __init__(
        self,
        webhook_url: Optional[str] = None,
        *,
        enabled: Optional[bool] = None,
        max_retries: int = DEFAULT_MAX_RETRIES,
        backoff_base: float = DEFAULT_BACKOFF_BASE,
        rate_limit: int = DEFAULT_RATE_LIMIT,
        rate_window: float = DEFAULT_RATE_WINDOW,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        self.webhook_url = webhook_url if webhook_url is not None else os.environ.get("WECHAT_WEBHOOK_URL", "")
        if enabled is None:
            raw = os.environ.get("WECHAT_ENABLED", "1").strip().lower()
            enabled = raw in {"1", "true", "yes", "on"}
        self.enabled = bool(enabled)
        self.max_retries = max(1, int(max_retries))
        self.backoff_base = float(backoff_base)
        self.rate_limit = int(rate_limit)
        self.rate_window = float(rate_window)
        self.timeout = float(timeout)

        self.stats = NotifyStats()
        self._rate_state: Dict[str, Deque[float]] = defaultdict(deque)
        self._rate_lock = threading.Lock()
        self._pending: Deque[Dict[str, Any]] = deque()
        self._pending_lock = threading.Lock()

    def send_text(
        self,
        content: str,
        *,
        target_key: str = "default",
        webhook_url: Optional[str] = None,
    ) -> bool:
        return self._send(
            {"msgtype": "text", "text": {"content": content}},
            target_key=target_key,
            webhook_url=webhook_url,
        )

    def send_markdown(
        self,
        content: str,
        *,
        target_key: str = "default",
        webhook_url: Optional[str] = None,
    ) -> bool:
        return self._send(
            {"msgtype": "markdown", "markdown": {"content": content}},
            target_key=target_key,
            webhook_url=webhook_url,
        )

    def enqueue(
        self,
        payload: Dict[str, Any],
        *,
        target_key: str = "default",
        webhook_url: Optional[str] = None,
    ) -> None:
        with self._pending_lock:
            self._pending.append(
                {
                    "payload": payload,
                    "target_key": target_key,
                    "webhook_url": webhook_url,
                    "enqueued_at": time.time(),
                }
            )

    def flush_queue(self, *, max_batch: int = 50) -> int:
        with self._pending_lock:
            batch = [self._pending.popleft() for _ in range(min(max_batch, len(self._pending)))]

        delivered = 0
        failed = []
        for item in batch:
            if self._send(
                item["payload"],
                target_key=item["target_key"],
                webhook_url=item.get("webhook_url"),
            ):
                delivered += 1
            else:
                failed.append(item)

        if failed:
            with self._pending_lock:
                for item in reversed(failed):
                    self._pending.appendleft(item)
        return delivered

    @property
    def pending_count(self) -> int:
        with self._pending_lock:
            return len(self._pending)

    def get_status(self) -> Dict[str, Any]:
        return {
            "enabled": self.enabled,
            "webhook_configured": bool(self.webhook_url),
            "webhook_url_masked": _mask_url(self.webhook_url),
            "pending_count": self.pending_count,
            "rate_limit": {
                "max_per_window": self.rate_limit,
                "window_seconds": self.rate_window,
            },
            "retry_config": {
                "max_retries": self.max_retries,
                "backoff_base_sec": self.backoff_base,
            },
            "stats": self.stats.snapshot(),
        }

    def _send(
        self,
        payload: Dict[str, Any],
        *,
        target_key: str,
        webhook_url: Optional[str] = None,
    ) -> bool:
        if not self.enabled:
            self.stats.record_failed("wechat notifier disabled")
            return False

        url = webhook_url or self.webhook_url
        if not url:
            self.stats.record_failed("webhook_url not configured")
            return False

        if not self._allow_send(target_key):
            self.stats.record_rate_limited()
            self.stats.record_failed("rate limited")
            return False

        last_error = ""
        for attempt in range(1, self.max_retries + 1):
            ok, error = self._post_once(url, payload)
            if ok:
                self.stats.record_sent()
                return True

            last_error = error
            if attempt < self.max_retries:
                self.stats.record_retry()
                time.sleep(self.backoff_base * (2 ** (attempt - 1)))

        self.stats.record_failed(last_error or "webhook post failed")
        return False

    def _post_once(self, url: str, payload: Dict[str, Any]) -> Tuple[bool, str]:
        req = urllib.request.Request(
            url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read().decode("utf-8")
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            return False, str(exc)

        if not raw:
            return True, ""
        try:
            body = json.loads(raw)
            errcode = int(body.get("errcode", 0))
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            return False, str(exc)
        if errcode == 0:
            return True, ""
        return False, f"errcode={errcode}, errmsg={body.get('errmsg', '')}"

    def _allow_send(self, target_key: str) -> bool:
        now = time.time()
        with self._rate_lock:
            window = self._rate_state[target_key]
            while window and now - window[0] >= self.rate_window:
                window.popleft()
            if len(window) >= self.rate_limit:
                return False
            window.append(now)
            return True


def _mask_url(url: str) -> str:
    if not url:
        return ""
    if len(url) <= 24:
        return url[:8] + "..."
    return url[:20] + "..." + url[-6:]


_notifier: Optional[WechatNotifier] = None
_notifier_lock = threading.Lock()


def get_notifier() -> WechatNotifier:
    global _notifier
    if _notifier is None:
        with _notifier_lock:
            if _notifier is None:
                _notifier = WechatNotifier()
    return _notifier


def reset_notifier() -> None:
    global _notifier
    with _notifier_lock:
        _notifier = None
