#!/usr/bin/env python3
"""VLM review service launcher (FastAPI default)."""

from __future__ import annotations

import argparse
import json
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


class LegacyVLMHandler(BaseHTTPRequestHandler):
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
        confirmed = event_type in ("kitchen_smoke", "cold_chain_high", "table_need_clean")
        self._json(
            200,
            {
                "confirmed": confirmed,
                "confidence": 0.85 if confirmed else 0.4,
                "review_note": "legacy rule stub",
                "payload": payload,
            },
        )

    def log_message(self, fmt: str, *args) -> None:
        print(f"[VLMReview] {fmt % args}")


def run_legacy(host: str, port: int) -> None:
    server = HTTPServer((host, port), LegacyVLMHandler)
    print(f"[VLMReview] legacy http://{host}:{port}")
    server.serve_forever()


def main() -> None:
    parser = argparse.ArgumentParser(description="Hotpot VLM review API")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8089)
    parser.add_argument("--legacy", action="store_true", help="Use stdlib stub server")
    args = parser.parse_args()

    if args.legacy:
        run_legacy(args.host, args.port)
        return

    import uvicorn

    uvicorn.run("cloud.vlm_review.app:app", host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
