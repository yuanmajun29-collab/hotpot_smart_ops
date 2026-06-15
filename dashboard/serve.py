#!/usr/bin/env python3
"""Simple static file server for hotpot dashboard."""

from __future__ import annotations

import argparse
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

DASHBOARD_DIR = Path(__file__).resolve().parent


class DashboardHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(DASHBOARD_DIR), **kwargs)

    def end_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        super().end_headers()


def main() -> None:
    parser = argparse.ArgumentParser(description="Hotpot dashboard server")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=3000)
    args = parser.parse_args()

    server = ThreadingHTTPServer((args.host, args.port), DashboardHandler)
    print(f"[Dashboard] MVP 入口: http://{args.host}:{args.port}/login.html")
    print(f"[Dashboard] 手机 H5:  http://{args.host}:{args.port}/mobile/index.html")
    print(f"[Dashboard] 旧版 PoC: http://{args.host}:{args.port}/poc.html")
    server.serve_forever()


if __name__ == "__main__":
    main()
