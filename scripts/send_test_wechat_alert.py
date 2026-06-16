#!/usr/bin/env python3
"""Send a test WeChat Work card via Hub (DEV-414 deployment checklist item 6)."""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request

DEFAULT_HUB = os.environ.get("HOTPOT_HUB_URL", "http://127.0.0.1:8088")


def main() -> int:
    parser = argparse.ArgumentParser(description="Test WeChat webhook via Hub /alerts/test-push")
    parser.add_argument("--hub-url", default=DEFAULT_HUB)
    parser.add_argument("--store-id", default="store_yuhuan")
    args = parser.parse_args()

    routes_url = f"{args.hub_url.rstrip('/')}/alerts/routes?store_id={args.store_id}"
    try:
        with urllib.request.urlopen(routes_url, timeout=10) as resp:
            routes = json.loads(resp.read().decode())
    except urllib.error.URLError as exc:
        print(f"Cannot reach Hub: {exc}", file=sys.stderr)
        return 2

    route = (routes.get("routes") or [{}])[0]
    print("Route status:", json.dumps(route, ensure_ascii=False, indent=2))
    if not route.get("webhook_configured"):
        print(
            "\nWebhook not configured. Set one of:\n"
            "  HOTPOT_WECHAT_WEBHOOK\n"
            f"  HOTPOT_WECHAT_WEBHOOK_{args.store_id.upper()}\n"
            "Then restart Hub and re-run.",
            file=sys.stderr,
        )
        return 3

    req = urllib.request.Request(
        f"{args.hub_url.rstrip('/')}/alerts/test-push?store_id={args.store_id}",
        data=b"{}",
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
    except urllib.error.URLError as exc:
        print(f"test-push failed: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(data, ensure_ascii=False, indent=2))
    return 0 if data.get("webhook_sent") else 1


if __name__ == "__main__":
    raise SystemExit(main())
