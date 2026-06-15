#!/usr/bin/env python3
"""Optional VLM review API stub for complex scene confirmation."""

from __future__ import annotations

import argparse
import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, Dict


class VLMHandler(BaseHTTPRequestHandler):
    def _json(self, code: int, data: Any) -> None:
        body = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", 0))
        payload = json.loads(self.rfile.read(length).decode() or "{}")
        event_type = payload.get("event_type", "")
        # PoC: rule-based VLM confirmation
        confirmed = event_type in ("kitchen_smoke", "cold_chain_high", "table_need_clean")
        self._json(
            200,
            {
                "confirmed": confirmed,
                "confidence": 0.85 if confirmed else 0.4,
                "review_note": "VLM PoC stub: 基于事件类型的规则复核",
                "payload": payload,
            },
        )

    def log_message(self, fmt: str, *args) -> None:
        print(f"[VLMReview] {fmt % args}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8089)
    args = parser.parse_args()
    server = HTTPServer(("0.0.0.0", args.port), VLMHandler)
    print(f"[VLMReview] http://0.0.0.0:{args.port}/review (POST)")
    server.serve_forever()


if __name__ == "__main__":
    main()
