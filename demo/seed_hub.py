#!/usr/bin/env python3
"""Seed multi-tenant Event Hub from demo/data/stores/*/seed.json."""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_STORES_DIR = ROOT / "demo" / "data" / "stores"
REGISTRY = ROOT / "demo" / "data" / "stores.json"


def post_json(url: str, payload: dict) -> dict:
    req = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode("utf-8"))


def seed_store(hub_url: str, seed: dict) -> None:
    base = hub_url.rstrip("/")
    sid = seed.get("store_id", "unknown")
    post_json(f"{base}/seed", seed)
    print(f"[OK] seeded {sid}: "
          f"events={len(seed.get('sample_events', []))} "
          f"tables={len(seed.get('table_states', []))}")


def load_seed_files(stores_dir: Path, store_id: str | None = None) -> list[Path]:
    if store_id:
        path = stores_dir / store_id / "seed.json"
        return [path] if path.exists() else []
    return sorted(stores_dir.glob("*/seed.json"))


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed Hotpot Event Hub tenants")
    parser.add_argument("--hub-url", default="http://127.0.0.1:8088")
    parser.add_argument("--stores-dir", default=str(DEFAULT_STORES_DIR))
    parser.add_argument("--store-id", default="", help="Seed single store")
    parser.add_argument("--all", action="store_true", help="Seed all stores in stores-dir")
    parser.add_argument("--build", action="store_true", help="Rebuild seed.json from demo data first")
    args = parser.parse_args()

    if args.build:
        import subprocess

        subprocess.run([sys.executable, str(ROOT / "demo" / "build_store_seeds.py")], check=True)

    store_id = args.store_id or None
    if not args.all and not store_id:
        store_id = None
        args.all = True

    seed_files = load_seed_files(Path(args.stores_dir), store_id if not args.all else None)
    if not seed_files:
        print("[ERROR] No seed.json found. Run: python3 demo/build_store_seeds.py", file=sys.stderr)
        sys.exit(1)

    ok = 0
    for seed_file in seed_files:
        seed = json.loads(seed_file.read_text(encoding="utf-8"))
        try:
            seed_store(args.hub_url, seed)
            ok += 1
        except urllib.error.URLError as exc:
            print(f"[ERROR] failed to seed {seed_file}: {exc}", file=sys.stderr)
            sys.exit(1)

    try:
        stores = json.loads(
            urllib.request.urlopen(f"{args.hub_url.rstrip('/')}/stores", timeout=10).read().decode()
        )
        print(f"[OK] hub stores: {[s.get('store_id') for s in stores.get('stores', [])]}")
    except Exception:
        pass

    print(f"[DONE] seeded {ok} store(s)")


if __name__ == "__main__":
    main()
