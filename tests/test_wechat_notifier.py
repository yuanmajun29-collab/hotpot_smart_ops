"""WeChat notifier unit + integration tests (DEV-5xx).

Coverage:
  - WechatNotifier: send_text, send_markdown, send_image, send_news
  - Retry with exponential backoff (3 attempts)
  - Rate limiting (5 per minute per target)
  - Pending queue (enqueue + flush)
  - Statistics tracking
  - Disabled / unconfigured paths
  - AlertGateway integration (critical immediate, warn queued)
  - API endpoints: POST /v1/system/notify/test, GET /v1/system/notify/status
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Mock webhook server
# ---------------------------------------------------------------------------


class MockWebhookCollector:
    """Collects received webhook payloads and can simulate failures."""

    def __init__(self, *, fail_count: int = 0) -> None:
        self.received: List[Dict[str, Any]] = []
        self.received_at: List[float] = []
        self._fail_count = fail_count
        self._call_count = 0

    def start(self) -> HTTPServer:
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(length)
                outer.received.append(json.loads(body.decode()) if body else {})
                outer.received_at.append(time.time())
                outer._call_count += 1

                if outer._fail_count > 0 and outer._call_count <= outer._fail_count:
                    self.send_response(500)
                    self.end_headers()
                    return

                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"errcode":0,"errmsg":"ok"}')

            def log_message(self, format: str, *args: Any) -> None:
                return

        self._server = HTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self._server.serve_forever, daemon=True).start()
        return self._server

    @property
    def url(self) -> str:
        port = self._server.server_address[1]
        return f"http://127.0.0.1:{port}/webhook"

    def stop(self) -> None:
        self._server.shutdown()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_notifier_singleton() -> None:
    """Ensure each test starts with a fresh notifier singleton."""
    from hotpot_platform.cloud.event_hub.wechat_notifier import reset_notifier
    reset_notifier()
    # Clear env to avoid cross-test pollution
    for key in ("WECHAT_WEBHOOK_URL", "WECHAT_ENABLED"):
        os.environ.pop(key, None)
    yield
    reset_notifier()
    for key in ("WECHAT_WEBHOOK_URL", "WECHAT_ENABLED"):
        os.environ.pop(key, None)


@pytest.fixture()
def mock_webhook() -> MockWebhookCollector:
    collector = MockWebhookCollector()
    collector.start()
    yield collector
    collector.stop()


@pytest.fixture()
def notifier(mock_webhook: MockWebhookCollector) -> Any:
    """Create a WechatNotifier pointed at the mock webhook."""
    from hotpot_platform.cloud.event_hub.wechat_notifier import WechatNotifier
    return WechatNotifier(webhook_url=mock_webhook.url, enabled=True)


@pytest.fixture()
def hub_client() -> Any:
    """FastAPI TestClient with AlertGateway wired to a temp DB."""
    tmp = tempfile.mkdtemp()
    db_path = Path(tmp) / "test_hub.db"
    os.environ["HOTPOT_DB"] = str(db_path)
    os.environ["HOTPOT_AUTH_MODE"] = "demo"
    os.environ["HOTPOT_DAILY_REPORT_SCHEDULER"] = "0"
    os.environ.pop("HOTPOT_SEED_DIR", None)
    os.environ.pop("HOTPOT_DATABASE_URL", None)

    from hotpot_platform.cloud.event_hub import app as hub_app_module
    from hotpot_platform.cloud.event_hub import runtime
    from hotpot_platform.cloud.event_hub.db import create_hub_database

    db = create_hub_database(db_path)
    runtime.init(
        hub_app_module.MultiTenantHub(on_persist=db.on_persist),
        db,
        hub_app_module.AlertGateway(db_path),
    )

    with TestClient(hub_app_module.app) as c:
        yield c


# ---------------------------------------------------------------------------
# Unit tests: WechatNotifier
# ---------------------------------------------------------------------------


class TestWechatNotifierBasics:
    """Basic send functionality."""

    def test_send_text(self, notifier, mock_webhook: MockWebhookCollector) -> None:
        ok = notifier.send_text("Hello 微信", target_key="test")
        assert ok is True
        assert len(mock_webhook.received) == 1
        assert mock_webhook.received[0]["msgtype"] == "text"
        assert mock_webhook.received[0]["text"]["content"] == "Hello 微信"

    def test_send_markdown(self, notifier, mock_webhook: MockWebhookCollector) -> None:
        md = "**Bold** _italic_ [link](https://example.com)"
        ok = notifier.send_markdown(md, target_key="test")
        assert ok is True
        assert len(mock_webhook.received) == 1
        assert mock_webhook.received[0]["msgtype"] == "markdown"
        assert mock_webhook.received[0]["markdown"]["content"] == md

    def test_send_with_mentioned(self, notifier, mock_webhook: MockWebhookCollector) -> None:
        ok = notifier.send_text(
            "Alert @all",
            mentioned_list=["@all"],
            mentioned_mobile_list=["13800138000"],
            target_key="test",
        )
        assert ok is True
        payload = mock_webhook.received[0]
        assert payload["text"]["mentioned_list"] == ["@all"]
        assert payload["text"]["mentioned_mobile_list"] == ["13800138000"]

    def test_send_news(self, notifier, mock_webhook: MockWebhookCollector) -> None:
        ok = notifier.send_news(
            [{"title": "News", "description": "Desc", "url": "https://x.com"}],
            target_key="test",
        )
        assert ok is True
        assert mock_webhook.received[0]["msgtype"] == "news"

    def test_send_image(self, notifier, mock_webhook: MockWebhookCollector) -> None:
        ok = notifier.send_image(
            base64_data="aW1hZ2U=", md5_hash="abc123", target_key="test"
        )
        assert ok is True
        assert mock_webhook.received[0]["msgtype"] == "image"


class TestWechatNotifierDisabled:
    """Behaviour when disabled or unconfigured."""

    def test_disabled_returns_false(self, mock_webhook: MockWebhookCollector) -> None:
        from hotpot_platform.cloud.event_hub.wechat_notifier import WechatNotifier
        n = WechatNotifier(webhook_url=mock_webhook.url, enabled=False)
        ok = n.send_text("should fail", target_key="test")
        assert ok is False
        assert len(mock_webhook.received) == 0

    def test_no_webhook_url_returns_false(self) -> None:
        from hotpot_platform.cloud.event_hub.wechat_notifier import WechatNotifier
        n = WechatNotifier(webhook_url="", enabled=True)
        ok = n.send_text("no url", target_key="test")
        assert ok is False

    def test_env_var_disabled(self, mock_webhook: MockWebhookCollector) -> None:
        os.environ["WECHAT_ENABLED"] = "0"
        from hotpot_platform.cloud.event_hub.wechat_notifier import WechatNotifier
        n = WechatNotifier(webhook_url=mock_webhook.url)
        assert n.enabled is False


class TestWechatNotifierRetry:
    """Exponential backoff retry behaviour."""

    def test_retry_on_server_error(self, mock_webhook: MockWebhookCollector) -> None:
        """First attempt fails (500), retries succeed."""
        from hotpot_platform.cloud.event_hub.wechat_notifier import WechatNotifier
        # Create a new collector that fails once
        collector2 = MockWebhookCollector(fail_count=1)
        collector2.start()
        try:
            n = WechatNotifier(
                webhook_url=collector2.url,
                enabled=True,
                max_retries=2,
                backoff_base=0.01,  # fast for test
            )
            ok = n.send_text("retry test", target_key="retry")
            assert ok is True
            # Should have been called twice (1 fail + 1 success)
            assert len(collector2.received) == 2
        finally:
            collector2.stop()

    def test_retry_exhausted(self) -> None:
        """All retries fail → returns False."""
        from hotpot_platform.cloud.event_hub.wechat_notifier import WechatNotifier
        collector = MockWebhookCollector(fail_count=10)  # always fail
        collector.start()
        try:
            n = WechatNotifier(
                webhook_url=collector.url,
                enabled=True,
                max_retries=3,
                backoff_base=0.01,
            )
            ok = n.send_text("exhausted", target_key="retry")
            assert ok is False
            assert len(collector.received) == 3  # 3 attempts
        finally:
            collector.stop()


class TestWechatNotifierRateLimit:
    """Per-target rate limiting."""

    def test_rate_limit_blocks_excess(self, mock_webhook: MockWebhookCollector) -> None:
        from hotpot_platform.cloud.event_hub.wechat_notifier import WechatNotifier
        n = WechatNotifier(
            webhook_url=mock_webhook.url,
            enabled=True,
            rate_limit=5,
            rate_window=60.0,  # long window so no expiry
        )
        # Send exactly 5 — should all succeed
        for i in range(5):
            ok = n.send_text(f"msg {i}", target_key="limit-test")
            assert ok is True
        assert len(mock_webhook.received) == 5

        # 6th should be rate-limited
        ok = n.send_text("excess", target_key="limit-test")
        assert ok is False
        assert len(mock_webhook.received) == 5  # no new message
        assert n.stats.rate_limited >= 1

    def test_different_targets_independent(self, mock_webhook: MockWebhookCollector) -> None:
        from hotpot_platform.cloud.event_hub.wechat_notifier import WechatNotifier
        n = WechatNotifier(
            webhook_url=mock_webhook.url,
            enabled=True,
            rate_limit=1,
            rate_window=60.0,
        )
        assert n.send_text("target A", target_key="a")
        assert n.send_text("target B", target_key="b")
        assert len(mock_webhook.received) == 2


class TestWechatNotifierQueue:
    """Pending queue for non-critical / batched delivery."""

    def test_enqueue_and_flush(self, mock_webhook: MockWebhookCollector) -> None:
        from hotpot_platform.cloud.event_hub.wechat_notifier import WechatNotifier
        n = WechatNotifier(webhook_url=mock_webhook.url, enabled=True)

        n.enqueue(
            {"msgtype": "text", "text": {"content": "queued 1"}},
            target_key="batch",
        )
        n.enqueue(
            {"msgtype": "text", "text": {"content": "queued 2"}},
            target_key="batch",
        )
        assert n.pending_count == 2

        delivered = n.flush_queue()
        assert delivered == 2
        assert n.pending_count == 0
        assert len(mock_webhook.received) == 2

    def test_flush_partial_failure(self, mock_webhook: MockWebhookCollector) -> None:
        """Failed items should be re-enqueued."""
        from hotpot_platform.cloud.event_hub.wechat_notifier import WechatNotifier
        # Create a collector where the first call succeeds, second fails
        # We'll use a bad URL for the second
        n = WechatNotifier(webhook_url=mock_webhook.url, enabled=True)

        n.enqueue(
            {"msgtype": "text", "text": {"content": "ok"}},
            target_key="batch",
            webhook_url=mock_webhook.url,
        )
        n.enqueue(
            {"msgtype": "text", "text": {"content": "fail"}},
            target_key="batch",
            webhook_url="http://127.0.0.1:19999/nowhere",  # bad URL
        )
        delivered = n.flush_queue()
        assert delivered == 1
        # The failed one should be re-enqueued
        assert n.pending_count >= 1


class TestWechatNotifierStats:
    """Statistics tracking."""

    def test_stats_increment(self, mock_webhook: MockWebhookCollector) -> None:
        from hotpot_platform.cloud.event_hub.wechat_notifier import WechatNotifier
        n = WechatNotifier(webhook_url=mock_webhook.url, enabled=True)

        n.send_text("msg 1", target_key="stats")
        n.send_text("msg 2", target_key="stats")

        snapshot = n.stats.snapshot()
        assert snapshot["sent"] == 2
        assert snapshot["failed"] == 0
        assert snapshot["last_sent_at"] is not None

    def test_get_status(self, mock_webhook: MockWebhookCollector) -> None:
        from hotpot_platform.cloud.event_hub.wechat_notifier import WechatNotifier
        n = WechatNotifier(webhook_url=mock_webhook.url, enabled=True)
        status = n.get_status()
        assert status["enabled"] is True
        assert status["webhook_configured"] is True
        assert "webhook_url_masked" in status
        assert "stats" in status


# ---------------------------------------------------------------------------
# Integration: AlertGateway + WechatNotifier
# ---------------------------------------------------------------------------


class TestAlertGatewayIntegration:
    """AlertGateway uses WechatNotifier for delivery."""

    def test_critical_immediate_push(self, hub_client, mock_webhook: MockWebhookCollector) -> None:
        """Critical events go through wechat_notifier immediately."""
        # AlertGateway uses HOTPOT_WECHAT_WEBHOOK_STORE_* for per-store webhooks
        os.environ["HOTPOT_WECHAT_WEBHOOK_STORE_YUHAN"] = mock_webhook.url
        os.environ["WECHAT_ENABLED"] = "1"

        from hotpot_platform.cloud.event_hub import app as hub_app_module
        from hotpot_platform.cloud.event_hub import runtime
        from hotpot_platform.cloud.event_hub.wechat_notifier import get_notifier, reset_notifier
        reset_notifier()

        # Re-init AlertGateway with notifier wired
        notifier = get_notifier()
        runtime.alert_gateway = hub_app_module.AlertGateway(
            Path(os.environ["HOTPOT_DB"]),
            notifier=notifier,
        )

        r = hub_client.post(
            "/events?store_id=store_yuhuan",
            json={
                "event_type": "kitchen_smoke",
                "source": "vision",
                "level": "critical",
                "store_id": "store_yuhuan",
                "message": "Critical smoke alert",
                "zone": "kitchen",
            },
        )
        assert r.status_code == 200
        push = r.json().get("_alert_push", {})
        assert push.get("delivery") == "immediate"
        # async delivery: wait then verify mock collector received the payload
        import time; time.sleep(0.5)
        assert len(mock_webhook.received) >= 1, f"Expected webhook calls, got {len(mock_webhook.received)}"

    def test_warn_queued_not_immediate(self, hub_client, mock_webhook: MockWebhookCollector) -> None:
        """Warn-level alerts go to pending queue, not immediate push."""
        # Use a store NOT in alert_routes.json so push_warn can be set via env
        os.environ["HOTPOT_PUSH_WARN"] = "1"
        os.environ["HOTPOT_WECHAT_WEBHOOK"] = mock_webhook.url  # global fallback
        os.environ["WECHAT_ENABLED"] = "1"

        from hotpot_platform.cloud.event_hub import app as hub_app_module
        from hotpot_platform.cloud.event_hub import runtime
        from hotpot_platform.cloud.event_hub.wechat_notifier import get_notifier, reset_notifier
        reset_notifier()

        notifier = get_notifier()
        runtime.alert_gateway = hub_app_module.AlertGateway(
            Path(os.environ["HOTPOT_DB"]),
            notifier=notifier,
        )

        recv_before = len(mock_webhook.received)
        r = hub_client.post(
            "/events?store_id=store_test_warn",
            json={
                "event_type": "table_need_clean",
                "source": "vision",
                "level": "warn",
                "store_id": "store_test_warn",
                "message": "Table needs cleaning",
            },
        )
        assert r.status_code == 200
        push = r.json().get("_alert_push", {})
        assert push.get("delivery") == "queued"

        # Should NOT have been immediately pushed
        time.sleep(0.2)
        assert len(mock_webhook.received) == recv_before

        # But should be in pending queue
        assert runtime.alert_gateway.pending_count >= 1

        # Flush → should deliver
        delivered = runtime.alert_gateway.flush_pending_queue()
        assert delivered >= 1
        assert len(mock_webhook.received) >= recv_before + 1


# ---------------------------------------------------------------------------
# API endpoint tests
# ---------------------------------------------------------------------------


class TestNotifyEndpoints:
    """POST /v1/system/notify/test and GET /v1/system/notify/status."""

    def test_notify_test_success(self, hub_client, mock_webhook: MockWebhookCollector) -> None:
        os.environ["WECHAT_WEBHOOK_URL"] = mock_webhook.url
        os.environ["WECHAT_ENABLED"] = "1"

        from hotpot_platform.cloud.event_hub.wechat_notifier import reset_notifier
        reset_notifier()

        r = hub_client.post(
            "/v1/system/notify/test",
            json={"message": "API test probe", "msgtype": "markdown"},
        )
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True
        assert data["msgtype"] == "markdown"
        assert len(mock_webhook.received) >= 1

    def test_notify_test_text_type(self, hub_client, mock_webhook: MockWebhookCollector) -> None:
        os.environ["WECHAT_WEBHOOK_URL"] = mock_webhook.url
        os.environ["WECHAT_ENABLED"] = "1"

        from hotpot_platform.cloud.event_hub.wechat_notifier import reset_notifier
        reset_notifier()

        r = hub_client.post(
            "/v1/system/notify/test",
            json={"message": "Plain text alert", "msgtype": "text"},
        )
        assert r.status_code == 200
        assert r.json()["ok"] is True
        assert mock_webhook.received[0]["msgtype"] == "text"

    def test_notify_test_no_webhook(self, hub_client) -> None:
        """Without webhook URL, should return ok=False with error."""
        os.environ.pop("WECHAT_WEBHOOK_URL", None)
        from hotpot_platform.cloud.event_hub.wechat_notifier import reset_notifier
        reset_notifier()

        r = hub_client.post(
            "/v1/system/notify/test",
            json={"message": "test", "msgtype": "text"},
        )
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is False
        assert "webhook_url not configured" in data["error"]

    def test_notify_test_custom_url(self, hub_client, mock_webhook: MockWebhookCollector) -> None:
        os.environ.pop("WECHAT_WEBHOOK_URL", None)
        from hotpot_platform.cloud.event_hub.wechat_notifier import reset_notifier
        reset_notifier()

        r = hub_client.post(
            "/v1/system/notify/test",
            json={
                "message": "Custom webhook",
                "msgtype": "text",
                "webhook_url": mock_webhook.url,
            },
        )
        assert r.status_code == 200
        assert r.json()["ok"] is True

    def test_notify_status(self, hub_client) -> None:
        os.environ["WECHAT_WEBHOOK_URL"] = "https://qyapi.weixin.qq.com/example"
        os.environ["WECHAT_ENABLED"] = "1"
        from hotpot_platform.cloud.event_hub.wechat_notifier import reset_notifier
        reset_notifier()

        r = hub_client.get("/v1/system/notify/status")
        assert r.status_code == 200
        data = r.json()
        assert data["enabled"] is True
        assert data["webhook_configured"] is True
        assert "stats" in data


class TestSingletonPattern:
    """Module-level get_notifier() singleton."""

    def test_singleton_same_instance(self) -> None:
        from hotpot_platform.cloud.event_hub.wechat_notifier import get_notifier
        n1 = get_notifier()
        n2 = get_notifier()
        assert n1 is n2

    def test_env_var_config(self, mock_webhook: MockWebhookCollector) -> None:
        os.environ["WECHAT_WEBHOOK_URL"] = mock_webhook.url
        os.environ["WECHAT_ENABLED"] = "1"
        from hotpot_platform.cloud.event_hub.wechat_notifier import get_notifier, reset_notifier
        reset_notifier()
        n = get_notifier()
        assert n.webhook_url == mock_webhook.url
        assert n.enabled is True
