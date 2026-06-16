#!/usr/bin/env python3
"""Manually trigger daily report generation (DEV-423 stub)."""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def main() -> None:
    parser = argparse.ArgumentParser(description="Trigger daily report via Hub API")
    parser.add_argument("--hub-url", default="http://127.0.0.1:8088")
    parser.add_argument("--store-id", default="store_yuhuan")
    parser.add_argument("--push", action="store_true", help="Also push WeChat card")
    args = parser.parse_args()

    body = json.dumps({"store_id": args.store_id, "push": args.push}).encode()
    req = urllib.request.Request(
        f"{args.hub_url.rstrip('/')}/v1/reports/daily/generate",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read().decode())
    print(json.dumps(data, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
