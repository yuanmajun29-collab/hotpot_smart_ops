#!/usr/bin/env python3
"""Event hub launcher — FastAPI (default) or legacy http.server."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def main() -> None:
    parser = argparse.ArgumentParser(description="Hotpot multi-tenant event hub")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8088)
    parser.add_argument("--seed-dir", default="", help="Seed stores on startup if DB empty")
    parser.add_argument("--db", default="", help="SQLite path (default demo/data/hub.db)")
    parser.add_argument("--legacy", action="store_true", help="Use legacy http.server")
    parser.add_argument(
        "--auth-mode",
        choices=("demo", "strict"),
        default=os.environ.get("HOTPOT_AUTH_MODE", "demo"),
    )
    args = parser.parse_args()

    if args.db:
        os.environ["HOTPOT_DB"] = args.db
    if args.seed_dir:
        os.environ["HOTPOT_SEED_DIR"] = args.seed_dir
    os.environ["HOTPOT_AUTH_MODE"] = args.auth_mode

    if args.legacy:
        from platform.cloud.event_hub import legacy_server

        legacy_server.run(args.host, args.port, args.seed_dir)
        return

    import uvicorn

    uvicorn.run(
        "cloud.event_hub.app:app",
        host=args.host,
        port=args.port,
        log_level="info",
    )


if __name__ == "__main__":
    main()
