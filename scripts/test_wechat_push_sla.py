#!/usr/bin/env python3
"""
Inject a synthetic critical event and verify push latency (DEV-415 · BL-03).

SLA: webhook receipt within 30 seconds (F-A04 / F-K04).

Usage:
  export HOTPOT_WECHAT_WEBHOOK=https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=...
  python3 scripts/test_wechat_push_sla.py --store-id store_yuhuan

With local mock (no real WeChat):
  python3 scripts/test_wechat_push_sla.py --mock-webhook
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, Dict, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

SLA_MS = 30_000


class MockWebhook:
    def __init__(self) -> None:
        self.received: List[Dict[str, Any]] = []
        self.received_at: List[float] = []
        self._server: Optional[HTTPServer] = None

    def start(self) -> str:
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(length)
                outer.received.append(json.loads(body.decode()))
                outer.received_at.append(time.time())
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"errcode":0,"errmsg":"ok"}')

            def log_message(self, format: str, *args: Any) -> None:
                return

        self._server = HTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self._server.serve_forever, daemon=True).start()
        port = self._server.server_address[1]
        return f"http://127.0.0.1:{port}/webhook"

    def stop(self) -> None:
        if self._server:
            self._server.shutdown()


def hub_post(hub_url: str, path: str, body: Dict[str, Any]) -> Dict[str, Any]:
    data = json.dumps(body, ensure_ascii=False).encode()
    req = urllib.request.Request(
        f"{hub_url.rstrip('/')}{path}",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode())


def hub_get(hub_url: str, path: str) -> Dict[str, Any]:
    with urllib.request.urlopen(f"{hub_url.rstrip('/')}{path}", timeout=15) as resp:
        return json.loads(resp.read().decode())


def wait_for_push_log(hub_url: str, store_id: str, since_count: int, timeout_sec: float) -> bool:
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        data = hub_get(hub_url, f"/alerts/push-log?store_id={store_id}&limit=5")
        if len(data.get("pushes", [])) > since_count:
            return True
        time.sleep(0.2)
    return False


def main() -> int:
    parser = argparse.ArgumentParser(description="WeChat critical push SLA probe (DEV-415)")
    parser.add_argument("--hub-url", default=os.environ.get("HOTPOT_HUB_URL", "http://127.0.0.1:8088"))
    parser.add_argument("--store-id", default="store_yuhuan")
    parser.add_argument("--sla-ms", type=int, default=SLA_MS)
    parser.add_argument("--mock-webhook", action="store_true", help="Spin local mock webhook server")
    parser.add_argument("--event-type", default="kitchen_smoke")
    args = parser.parse_args()

    mock: Optional[MockWebhook] = None
    if args.mock_webhook:
        mock = MockWebhook()
        url = mock.start()
        env_key = f"HOTPOT_WECHAT_WEBHOOK_{args.store_id.upper()}"
        os.environ[env_key] = url
        print(f"[sla] mock webhook listening at {url} (env {env_key})")
        print("[sla] NOTE: Hub process must read this env — restart hub or use test client mode")

        # In-process path for standalone script without running hub restart:
        print("[sla] using /alerts/test-push against running hub with pre-set env on hub side")

    routes = hub_get(args.hub_url, f"/alerts/routes?store_id={args.store_id}")
    route = (routes.get("routes") or [{}])[0]
    if not route.get("webhook_configured"):
        print(
            f"[sla] WARN: webhook not configured for {args.store_id}. "
            "Set HOTPOT_WECHAT_WEBHOOK or HOTPOT_WECHAT_WEBHOOK_STORE_* on Hub."
        )

    before = hub_get(args.hub_url, f"/alerts/push-log?store_id={args.store_id}&limit=5")
    before_count = len(before.get("pushes", []))

    t0 = time.time()
    event_body = {
        "event_type": args.event_type,
        "source": "system",
        "level": "critical",
        "store_id": args.store_id,
        "message": "【SLA探针】后厨烟雾模拟 — 请确认收到后 ack",
        "zone": "kitchen",
    }
    try:
        result = hub_post(args.hub_url, f"/events?store_id={args.store_id}", event_body)
    except urllib.error.URLError as exc:
        print(f"[sla] FAIL: cannot reach Hub at {args.hub_url}: {exc}")
        if mock:
            mock.stop()
        return 2

    push_meta = result.get("_alert_push", {})
    webhook_sent = push_meta.get("webhook_sent", False)

    mock_elapsed_ms: Optional[float] = None
    if mock:
        deadline = t0 + args.sla_ms / 1000.0
        while time.time() < deadline and not mock.received:
            time.sleep(0.05)
        if mock.received:
            mock_elapsed_ms = (mock.received_at[0] - t0) * 1000

    log_ok = wait_for_push_log(args.hub_url, args.store_id, before_count, timeout_sec=5.0)
    hub_elapsed_ms = (time.time() - t0) * 1000

    report = {
        "store_id": args.store_id,
        "event_id": result.get("event_id"),
        "webhook_configured": route.get("webhook_configured"),
        "webhook_sent": webhook_sent,
        "push_log_updated": log_ok,
        "hub_elapsed_ms": round(hub_elapsed_ms, 1),
        "mock_elapsed_ms": round(mock_elapsed_ms, 1) if mock_elapsed_ms is not None else None,
        "sla_ms": args.sla_ms,
        "pass": webhook_sent and log_ok and hub_elapsed_ms < args.sla_ms,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))

    if mock:
        mock.stop()

    if not route.get("webhook_configured"):
        print("[sla] SKIP: webhook not configured — configure DEV-414 then re-run")
        return 3
    return 0 if report["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
