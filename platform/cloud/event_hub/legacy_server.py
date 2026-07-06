"""Legacy stdlib HTTP server (fallback)."""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from platform.cloud.event_hub.hub_core import DEFAULT_STORE_ID, MultiTenantHub, seed_from_directory

HUB = MultiTenantHub()


def resolve_store_id(qs, data=None) -> str:
    sid = qs.get("store_id", [None])[0]
    if not sid and isinstance(data, dict):
        sid = data.get("store_id")
    if not sid and isinstance(data, list) and data and isinstance(data[0], dict):
        sid = data[0].get("store_id")
    return sid or DEFAULT_STORE_ID


class HubHandler(BaseHTTPRequestHandler):
    def _json_response(self, code: int, data: Any) -> None:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Store-Id, Authorization, X-Api-Key")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> Any:
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length else b"{}"
        return json.loads(raw.decode("utf-8") or "{}")

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Store-Id, Authorization, X-Api-Key")
        self.end_headers()

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        qs = parse_qs(parsed.query)
        if parsed.path == "/health":
            self._json_response(200, {"status": "ok", "multi_tenant": True, "engine": "legacy"})
        elif parsed.path == "/stores":
            self._json_response(200, {"stores": HUB.list_stores()})
        elif parsed.path == "/benchmark":
            self._json_response(200, HUB.get_benchmark())
        elif parsed.path == "/summary":
            self._json_response(200, HUB.get_store(resolve_store_id(qs)).get_summary())
        elif parsed.path == "/events":
            store = HUB.get_store(resolve_store_id(qs))
            level = qs.get("level", [None])[0]
            limit = int(qs.get("limit", ["50"])[0])
            self._json_response(200, store.get_events(level, limit))
        elif parsed.path in ("/tables", "/sop", "/cost", "/iot"):
            store = HUB.get_store(resolve_store_id(qs))
            payload = {
                "/tables": list(store.table_states.values()),
                "/sop": store.sop_stats or {"store_id": store.store_id, "results": []},
                "/cost": store.cost_stats or {"store_id": store.store_id, "items": []},
                "/iot": store.iot_stats or {"store_id": store.store_id, "stage_readings": {}},
            }[parsed.path]
            self._json_response(200, payload)
        else:
            self._json_response(404, {"error": "not found"})

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        qs = parse_qs(parsed.query)
        data = self._read_json()
        store = HUB.get_store(resolve_store_id(qs, data))
        if parsed.path == "/events":
            self._json_response(201, store.add_event(data if isinstance(data, dict) else {}))
        elif parsed.path == "/tables":
            tables = data if isinstance(data, list) else data.get("tables", [])
            store.set_table_states(tables)
            self._json_response(200, {"ok": True, "store_id": store.store_id, "count": len(store.table_states)})
        elif parsed.path == "/seed":
            HUB.apply_seed(data if isinstance(data, dict) else {})
            self._json_response(200, {"ok": True})
        elif parsed.path in ("/pos", "/sop", "/cost", "/iot"):
            fn = {
                "/pos": store.set_pos_stats,
                "/sop": store.set_sop_stats,
                "/cost": store.set_cost_stats,
                "/iot": store.set_iot_stats,
            }[parsed.path]
            fn(data if isinstance(data, dict) else {})
            self._json_response(200, {"ok": True, "store_id": store.store_id})
        else:
            self._json_response(404, {"error": "not found"})

    def log_message(self, format: str, *args) -> None:
        print(f"[EventHub:legacy] {self.address_string()} - {format % args}")


def run(host: str, port: int, seed_dir: str) -> None:
    if seed_dir:
        n = seed_from_directory(HUB, Path(seed_dir))
        print(f"[EventHub:legacy] Seeded {n} store(s)")
    server = HTTPServer((host, port), HubHandler)
    print(f"[EventHub:legacy] http://{host}:{port}")
    server.serve_forever()
