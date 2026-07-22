"""Production WeChat notifier tests."""

from __future__ import annotations

import json
import os
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, Dict, List

import pytest
from fastapi.testclient import TestClient


class MockWebhook:
    def __init__(self, *, fail_count: int = 0) -> None:
        self.received: List[Dict[str, Any]] = []
        self.statuses: List[int] = []
        self._fail_count = fail_count
        self._calls = 0
        self._server: HTTPServer | None = None

    def start(self) -> "MockWebhook":
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                length = int(self.headers.get("Content-Length", "0"))
                raw = self.rfile.read(length)
                outer._calls += 1
                outer.received.append(json.loads(raw.decode("utf-8")))

                if outer._calls <= outer._fail_count:
                    outer.statuses.append(500)
                    self.send_response(500)
                    self.end_headers()
                    return

                outer.statuses.append(200)
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"errcode":0,"errmsg":"ok"}')

            def log_message(self, format: str, *args: Any) -> None:
                return

        self._server = HTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self._server.serve_forever, daemon=True).start()
        return self

    @property
    def url(self) -> str:
        assert self._server is not None
        return f"http://127.0.0.1:{self._server.server_address[1]}/webhook"

    def stop(self) -> None:
        if self._server is not None:
            self._server.shutdown()


@pytest.fixture(autouse=True)
def clean_env() -> None:
    from hotpot_platform.cloud.event_hub.wechat_notifier import reset_notifier

    keys = [
        "WECHAT_WEBHOOK_URL",
        "WECHAT_ENABLED",
        "HOTPOT_WECHAT_WEBHOOK",
        "HOTPOT_WECHAT_WEBHOOK_STORE_YUHUAN",
        "HOTPOT_PUSH_WARN",
    ]
    reset_notifier()
    for key in keys:
        os.environ.pop(key, None)
    yield
    reset_notifier()
    for key in keys:
        os.environ.pop(key, None)


@pytest.fixture()
def webhook() -> MockWebhook:
    server = MockWebhook().start()
    yield server
    server.stop()


def make_client(db_path: Path) -> TestClient:
    os.environ["HOTPOT_DB"] = str(db_path)
    os.environ["HOTPOT_AUTH_MODE"] = "demo"
    os.environ["HOTPOT_DAILY_REPORT_SCHEDULER"] = "0"
    os.environ.pop("HOTPOT_SEED_DIR", None)
    os.environ.pop("HOTPOT_DATABASE_URL", None)

    from hotpot_platform.cloud.event_hub import app as app_module
    from hotpot_platform.cloud.event_hub import runtime
    from hotpot_platform.cloud.event_hub.db import create_hub_database

    db = create_hub_database(db_path)
    runtime.init(
        app_module.MultiTenantHub(on_persist=db.on_persist),
        db,
        app_module.AlertGateway(db_path),
    )
    return TestClient(app_module.app)


def test_webhook_send_text_and_markdown(webhook: MockWebhook) -> None:
    from hotpot_platform.cloud.event_hub.wechat_notifier import WechatNotifier

    notifier = WechatNotifier(webhook_url=webhook.url, enabled=True, backoff_base=0.01)

    assert notifier.send_text("plain text", target_key="send")
    assert notifier.send_markdown("**markdown**", target_key="send")

    assert webhook.received[0] == {"msgtype": "text", "text": {"content": "plain text"}}
    assert webhook.received[1] == {"msgtype": "markdown", "markdown": {"content": "**markdown**"}}
    assert notifier.stats.snapshot()["sent"] == 2


def test_rate_limit_same_target_five_per_sixty_seconds(webhook: MockWebhook) -> None:
    from hotpot_platform.cloud.event_hub.wechat_notifier import WechatNotifier

    notifier = WechatNotifier(webhook_url=webhook.url, enabled=True, rate_limit=5, rate_window=60)

    for i in range(5):
        assert notifier.send_text(f"msg {i}", target_key="store:a")

    assert notifier.send_text("blocked", target_key="store:a") is False
    assert len(webhook.received) == 5
    stats = notifier.stats.snapshot()
    assert stats["sent"] == 5
    assert stats["failed"] == 1
    assert stats["rate_limited"] == 1


def test_retry_with_exponential_backoff() -> None:
    from hotpot_platform.cloud.event_hub.wechat_notifier import WechatNotifier

    webhook = MockWebhook(fail_count=2).start()
    try:
        notifier = WechatNotifier(
            webhook_url=webhook.url,
            enabled=True,
            max_retries=3,
            backoff_base=0.01,
        )

        assert notifier.send_text("retry me", target_key="retry")
        assert webhook.statuses == [500, 500, 200]
        stats = notifier.stats.snapshot()
        assert stats["sent"] == 1
        assert stats["failed"] == 0
        assert stats["retried"] == 2
    finally:
        webhook.stop()


def test_queue_flush_reenqueues_failed_items(webhook: MockWebhook) -> None:
    from hotpot_platform.cloud.event_hub.wechat_notifier import WechatNotifier

    failing = MockWebhook(fail_count=10).start()
    try:
        notifier = WechatNotifier(
            webhook_url=webhook.url,
            enabled=True,
            max_retries=1,
            backoff_base=0.01,
            timeout=0.2,
        )
        notifier.enqueue({"msgtype": "text", "text": {"content": "ok"}}, target_key="q1")
        notifier.enqueue(
            {"msgtype": "markdown", "markdown": {"content": "fail"}},
            target_key="q2",
            webhook_url=failing.url,
        )

        assert notifier.pending_count == 2
        assert notifier.flush_queue() == 1
        assert notifier.pending_count == 1
        assert webhook.received[0]["text"]["content"] == "ok"
        assert notifier.stats.snapshot()["failed"] == 1
    finally:
        failing.stop()


def test_status_and_env_switch(webhook: MockWebhook) -> None:
    from hotpot_platform.cloud.event_hub.wechat_notifier import WechatNotifier

    os.environ["WECHAT_WEBHOOK_URL"] = webhook.url
    os.environ["WECHAT_ENABLED"] = "0"
    disabled = WechatNotifier()
    assert disabled.enabled is False
    assert disabled.send_text("nope") is False
    assert webhook.received == []

    status = disabled.get_status()
    assert status["enabled"] is False
    assert status["webhook_configured"] is True
    assert status["stats"]["failed"] == 1


def test_gateway_critical_immediate_and_warn_queue(webhook: MockWebhook) -> None:
    from hotpot_platform.cloud.alert_gateway.gateway import AlertGateway
    from hotpot_platform.cloud.event_hub.wechat_notifier import WechatNotifier

    db_path = Path(tempfile.mkdtemp()) / "alerts.db"
    notifier = WechatNotifier(webhook_url=webhook.url, enabled=True, backoff_base=0.01)
    gateway = AlertGateway(db_path, notifier=notifier)
    os.environ["WECHAT_WEBHOOK_URL"] = webhook.url
    os.environ["HOTPOT_PUSH_WARN"] = "1"

    critical = gateway.handle_event(
        {
            "event_id": "crit-1",
            "event_type": "kitchen_smoke",
            "level": "critical",
            "message": "smoke",
        },
        "store_yuhuan",
    )
    assert critical is not None
    assert critical["delivery"] == "immediate"
    assert critical["webhook_sent"] is True
    assert len(webhook.received) == 1

    warn = gateway.handle_event(
        {
            "event_id": "warn-1",
            "event_type": "table_need_clean",
            "level": "warn",
            "message": "clean table",
        },
        "store_yuhuan",
    )
    assert warn is not None
    assert warn["delivery"] == "queued"
    assert len(webhook.received) == 1
    assert gateway.pending_count == 1

    assert gateway.flush_pending_queue() == 1
    assert gateway.pending_count == 0
    assert len(webhook.received) == 2


def test_notify_endpoints(webhook: MockWebhook) -> None:
    os.environ["WECHAT_WEBHOOK_URL"] = webhook.url
    os.environ["WECHAT_ENABLED"] = "1"

    with make_client(Path(tempfile.mkdtemp()) / "hub.db") as client:
        response = client.post(
            "/v1/system/notify/test",
            json={"msgtype": "markdown", "message": "endpoint probe"},
        )
        assert response.status_code == 200
        assert response.json()["ok"] is True
        assert webhook.received[-1]["markdown"]["content"] == "endpoint probe"

        status = client.get("/v1/system/notify/status")
        assert status.status_code == 200
        body = status.json()
        assert body["available"] is True
        assert body["enabled"] is True
        assert "stats" in body
