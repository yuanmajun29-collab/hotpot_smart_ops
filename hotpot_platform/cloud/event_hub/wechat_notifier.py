"""Production-grade WeChat Work webhook notifier (DEV-5xx).

Features:
  - Text, Markdown, and Image message types
  - Exponential backoff retry (3 attempts)
  - Per-target rate limiting (max 5 per minute)
  - Config from environment variables (no hardcoded secrets)
  - Thread-safe statistics tracking
  - Pending queue for batched/non-critical delivery

Env vars:
  WECHAT_WEBHOOK_URL  – default webhook URL (fallback)
  WECHAT_ENABLED      – "1" / "true" to enable (default: enabled)
"""

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
from typing import Any, Callable, Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_MAX_RETRIES = 3
DEFAULT_BACKOFF_BASE = 1.0  # seconds; actual: base * (2 ** (attempt-1))
DEFAULT_RATE_LIMIT = 5       # max messages per window
DEFAULT_RATE_WINDOW = 60     # seconds
DEFAULT_TIMEOUT = 10         # HTTP connect/read timeout in seconds

# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class NotifyStats:
    """Thread-safe notification statistics."""

    sent: int = 0
    failed: int = 0
    rate_limited: int = 0
    retried: int = 0
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

    def record_rate_limited(self) -> None:
        with self._lock:
            self.rate_limited += 1

    def record_retry(self) -> None:
        with self._lock:
            self.retried += 1

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "sent": self.sent,
                "failed": self.failed,
                "rate_limited": self.rate_limited,
                "retried": self.retried,
                "last_sent_at": (
                    datetime.fromtimestamp(self.last_sent_at, tz=timezone.utc).isoformat()
                    if self.last_sent_at
                    else None
                ),
                "last_error": self.last_error,
            }


# ---------------------------------------------------------------------------
# WechatNotifier
# ---------------------------------------------------------------------------


class WechatNotifier:
    """Production WeChat Work webhook client with retry, rate-limiting, and queue."""

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
        # Config from env (constructor args take precedence)
        self.webhook_url: str = (
            webhook_url
            or os.environ.get("WECHAT_WEBHOOK_URL", "")
        )
        if enabled is None:
            enabled_str = os.environ.get("WECHAT_ENABLED", "1").strip().lower()
            enabled = enabled_str in ("1", "true", "yes", "on")
        self.enabled: bool = bool(enabled)

        self.max_retries = max_retries
        self.backoff_base = backoff_base
        self.rate_limit = rate_limit
        self.rate_window = rate_window
        self.timeout = timeout

        # Rate-limit state: target_key -> deque of event timestamps
        self._rate_state: Dict[str, deque] = defaultdict(deque)
        self._rate_lock = threading.Lock()

        # Pending queue for deferred delivery (non-critical alerts)
        self._pending: deque = deque()
        self._pending_lock = threading.Lock()

        # Stats
        self.stats = NotifyStats()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def send_text(
        self,
        content: str,
        *,
        mentioned_list: Optional[List[str]] = None,
        mentioned_mobile_list: Optional[List[str]] = None,
        target_key: str = "default",
        webhook_url: Optional[str] = None,
    ) -> bool:
        """Send a plain-text message."""
        payload: Dict[str, Any] = {
            "msgtype": "text",
            "text": {
                "content": content,
            },
        }
        if mentioned_list:
            payload["text"]["mentioned_list"] = mentioned_list
        if mentioned_mobile_list:
            payload["text"]["mentioned_mobile_list"] = mentioned_mobile_list
        return self._send(payload, target_key=target_key, webhook_url=webhook_url)

    def send_markdown(
        self,
        content: str,
        *,
        target_key: str = "default",
        webhook_url: Optional[str] = None,
    ) -> bool:
        """Send a Markdown-formatted message."""
        payload: Dict[str, Any] = {
            "msgtype": "markdown",
            "markdown": {
                "content": content,
            },
        }
        return self._send(payload, target_key=target_key, webhook_url=webhook_url)

    def send_image(
        self,
        base64_data: str,
        md5_hash: str,
        *,
        target_key: str = "default",
        webhook_url: Optional[str] = None,
    ) -> bool:
        """Send an image message (base64-encoded, with md5)."""
        payload: Dict[str, Any] = {
            "msgtype": "image",
            "image": {
                "base64": base64_data,
                "md5": md5_hash,
            },
        }
        return self._send(payload, target_key=target_key, webhook_url=webhook_url)

    def send_news(
        self,
        articles: List[Dict[str, str]],
        *,
        target_key: str = "default",
        webhook_url: Optional[str] = None,
    ) -> bool:
        """Send a news (rich-link) message. Each article: {title, description, url, picurl}."""
        payload: Dict[str, Any] = {
            "msgtype": "news",
            "news": {
                "articles": articles,
            },
        }
        return self._send(payload, target_key=target_key, webhook_url=webhook_url)

    # ------------------------------------------------------------------
    # Queue (deferred / non-critical delivery)
    # ------------------------------------------------------------------

    def enqueue(
        self,
        payload: Dict[str, Any],
        *,
        target_key: str = "default",
        webhook_url: Optional[str] = None,
    ) -> None:
        """Add a message to the pending queue for later batch delivery."""
        with self._pending_lock:
            self._pending.append({
                "payload": payload,
                "target_key": target_key,
                "webhook_url": webhook_url or self.webhook_url,
                "enqueued_at": time.time(),
            })

    def flush_queue(self, *, max_batch: int = 50) -> int:
        """Deliver all pending messages. Returns count of successful deliveries."""
        delivered = 0
        with self._pending_lock:
            batch = list(self._pending)[:max_batch]
            remaining = deque(list(self._pending)[max_batch:])
            self._pending = remaining

        for item in batch:
            ok = self._send(
                item["payload"],
                target_key=item["target_key"],
                webhook_url=item["webhook_url"],
            )
            if ok:
                delivered += 1
            else:
                # Re-enqueue failed items at the front
                with self._pending_lock:
                    self._pending.appendleft(item)

        return delivered

    @property
    def pending_count(self) -> int:
        with self._pending_lock:
            return len(self._pending)

    # ------------------------------------------------------------------
    # Statistics
    # ------------------------------------------------------------------

    def get_status(self) -> Dict[str, Any]:
        """Return a snapshot of notifier status and statistics."""
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

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _send(
        self,
        payload: Dict[str, Any],
        *,
        target_key: str = "default",
        webhook_url: Optional[str] = None,
    ) -> bool:
        """Core send with rate-limit + retry logic."""
        if not self.enabled:
            self.stats.record_failed("wechat notifier disabled")
            return False

        url = webhook_url or self.webhook_url
        if not url:
            self.stats.record_failed("webhook_url not configured")
            return False

        if not self._check_rate(target_key):
            self.stats.record_rate_limited()
            return False

        last_error = ""
        for attempt in range(1, self.max_retries + 1):
            try:
                ok, err = self._post_once(url, payload)
                if ok:
                    self.stats.record_sent()
                    return True
                last_error = err or "unknown"
            except Exception as exc:
                last_error = str(exc)

            if attempt < self.max_retries:
                delay = self.backoff_base * (2 ** (attempt - 1))
                self.stats.record_retry()
                time.sleep(delay)

        self.stats.record_failed(last_error)
        return False

    def _post_once(self, url: str, payload: Dict[str, Any]) -> Tuple[bool, str]:
        """Single HTTP POST to the webhook. Returns (ok, error_string)."""
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read().decode("utf-8")
                if not raw:
                    return True, ""
                body = json.loads(raw)
                errcode = int(body.get("errcode", 0))
                if errcode == 0:
                    return True, ""
                return False, f"errcode={errcode}, errmsg={body.get('errmsg', '')}"
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, ValueError) as exc:
            return False, str(exc)

    def _check_rate(self, target_key: str) -> bool:
        """Rate-limit check: at most `rate_limit` calls per `rate_window` seconds."""
        now = time.time()
        with self._rate_lock:
            window = self._rate_state[target_key]
            # Purge expired timestamps
            while window and now - window[0] > self.rate_window:
                window.popleft()
            if len(window) >= self.rate_limit:
                return False
            window.append(now)
            return True


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mask_url(url: str) -> str:
    if not url:
        return ""
    if len(url) <= 24:
        return url[:8] + "…"
    return url[:20] + "…" + url[-6:]


# ---------------------------------------------------------------------------
# Module-level convenience factory
# ---------------------------------------------------------------------------


# Singleton instance for easy import
_notifier: Optional[WechatNotifier] = None
_notifier_lock = threading.Lock()


def get_notifier() -> WechatNotifier:
    """Get or create the module-level WechatNotifier singleton."""
    global _notifier
    if _notifier is None:
        with _notifier_lock:
            if _notifier is None:
                _notifier = WechatNotifier()
    return _notifier


def reset_notifier() -> None:
    """Reset the module-level singleton (useful for tests)."""
    global _notifier
    with _notifier_lock:
        _notifier = None
