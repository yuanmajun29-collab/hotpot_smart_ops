#!/usr/bin/env python3
"""Edge health check — vision worker + hub connectivity (DEV-104)."""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from pathlib import Path
from typing import Any, Dict

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def check_hub(hub_url: str, store_id: str) -> Dict[str, Any]:
    base = hub_url.rstrip("/")
    health = json.loads(urllib.request.urlopen(f"{base}/health", timeout=5).read().decode())
    summary = json.loads(
        urllib.request.urlopen(f"{base}/summary?store_id={store_id}", timeout=5).read().decode()
    )
    return {"health": health, "summary_ok": bool(summary.get("store_id"))}


def check_vision_log(store_id: str, max_age_sec: int = 120) -> Dict[str, Any]:
    log_path = PROJECT_ROOT / "demo" / "data" / "stores" / store_id / "live" / "vision_worker.log"
    if not log_path.exists():
        return {"vision_log": "missing", "ok": False}
    import time

    age = time.time() - log_path.stat().st_mtime
    return {"vision_log": str(log_path), "age_sec": round(age, 1), "ok": age <= max_age_sec}


def main() -> None:
    parser = argparse.ArgumentParser(description="Edge health check")
    parser.add_argument("--store-id", default="store_yuhuan")
    parser.add_argument("--hub-url", default="http://127.0.0.1:8088")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    result: Dict[str, Any] = {"store_id": args.store_id, "checks": {}}
    try:
        result["checks"]["hub"] = check_hub(args.hub_url, args.store_id)
        result["checks"]["hub"]["ok"] = result["checks"]["hub"]["health"].get("status") == "ok"
    except Exception as exc:
        result["checks"]["hub"] = {"ok": False, "error": str(exc)}

    result["checks"]["vision"] = check_vision_log(args.store_id)
    result["ok"] = all(c.get("ok") for c in result["checks"].values())

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        status = "OK" if result["ok"] else "DEGRADED"
        print(f"[edge_health] {status} store={args.store_id}")
        for name, chk in result["checks"].items():
            print(f"  {name}: {'ok' if chk.get('ok') else 'FAIL'}")

    sys.exit(0 if result["ok"] else 1)


if __name__ == "__main__":
    main()
