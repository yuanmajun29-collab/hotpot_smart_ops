#!/usr/bin/env python3
"""Simple static file server for hotpot dashboard.

新增功能:
  --hub-url   指定 Hub 地址 (默认 http://127.0.0.1:8098)
  /config.js  自动注入 window.HOTPOT_CONFIG = {hubUrl, apiPrefix}
"""

from __future__ import annotations

import argparse
import json
import os
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

DASHBOARD_DIR = Path(__file__).resolve().parent
DEFAULT_HUB_URL = os.environ.get("HOTPOT_DASHBOARD_HUB_URL", "http://127.0.0.1:8098")
DEFAULT_API_PREFIX = "/api/v1"

_HUB_URL = DEFAULT_HUB_URL


class DashboardHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(DASHBOARD_DIR), **kwargs)

    def end_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        super().end_headers()

    def do_GET(self) -> None:
        if self.path == "/config.js":
            self._serve_config_js()
            return
        super().do_GET()

    def _serve_config_js(self) -> None:
        config = {
            "hubUrl": _HUB_URL,
            "apiPrefix": DEFAULT_API_PREFIX,
        }
        body = f"window.HOTPOT_CONFIG = {json.dumps(config)};\n"
        self.send_response(200)
        self.send_header("Content-Type", "application/javascript")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(body.encode("utf-8"))


def main() -> None:
    global _HUB_URL
    parser = argparse.ArgumentParser(description="Hotpot dashboard server")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=3000)
    parser.add_argument("--hub-url", default=DEFAULT_HUB_URL,
                       help=f"Hub API base URL (default: {DEFAULT_HUB_URL})")
    args = parser.parse_args()
    _HUB_URL = args.hub_url.rstrip("/")

    server = ThreadingHTTPServer((args.host, args.port), DashboardHandler)
    print(f"[Dashboard] Hub URL: {_HUB_URL}")
    print(f"[Dashboard] API Prefix: {DEFAULT_API_PREFIX}")
    print(f"[Dashboard] MVP 入口: http://{args.host}:{args.port}/login.html")
    print(f"[Dashboard] 手机 H5:  http://{args.host}:{args.port}/mobile/index.html")
    print(f"[Dashboard] 配置注入: http://{args.host}:{args.port}/config.js")
    server.serve_forever()


if __name__ == "__main__":
    main()
