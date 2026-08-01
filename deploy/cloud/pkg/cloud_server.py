#!/usr/bin/env python3
"""火瞳平台端 — 云端自包含部署服务器

合并 Event Hub API + Dashboard 前端 + Demo 数据
单端口启动，适合 CloudStudio / 任何云服务器

用法:
    python cloud_server.py [--port 8080] [--init-data]

访问:
    前端: http://localhost:<port>/login.html
    API:  http://localhost:<port>/health
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

# ============================================================
# 路径配置
# ============================================================
DEPLOY_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = DEPLOY_DIR.parents[2]  # hotpot_smart_ops/
DASHBOARD_DIR = PROJECT_ROOT / "hotpot_platform" / "dashboard"
DEMO_DATA_DIR = PROJECT_ROOT / "demo" / "data"

# 确保项目根目录在 sys.path
PROJECT_ROOT_STR = str(PROJECT_ROOT)
if PROJECT_ROOT_STR not in sys.path:
    sys.path.insert(0, PROJECT_ROOT_STR)

# 全局状态
_hub_url = ""
_port = 0
_hub_thread = None
_hub_ready = threading.Event()


# ============================================================
# Dashboard 静态文件服务器（主线程）
# ============================================================
class CloudDashboardHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(DASHBOARD_DIR), **kwargs)

    def end_headers(self) -> None:
        # CORS + 安全头
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("X-Content-Type-Options", "nosniff")
        super().end_headers()

    def do_GET(self) -> None:
        # 动态注入 config.js（告诉前端 Hub API 地址）
        if self.path == "/config.js":
            self._serve_config_js()
            return
        # API 代理到 Hub
        if self.path.startswith("/api/") or self.path.startswith("/auth/"):
            self._proxy_to_hub()
            return
        # Hub 健康检查等端点代理
        if self.path in ("/health", "/metrics") or self.path.startswith("/v1/"):
            self._proxy_to_hub()
            return
        super().do_GET()

    def do_POST(self) -> None:
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length) if content_length > 0 else None
        if self.path.startswith("/api/") or self.path.startswith("/auth/") or self.path.startswith("/v1/"):
            self._proxy_to_hub(body=body)
            return
        self.send_error(404, "Not Found")

    def do_PUT(self) -> None:
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length) if content_length > 0 else None
        if self.path.startswith("/v1/"):
            self._proxy_to_hub(body=body, method="PUT")
            return
        self.send_error(404, "Not Found")

    def _serve_config_js(self) -> None:
        config = {
            "hubUrl": f"http://127.0.0.1:{_port}",
            "apiPrefix": "",
        }
        body = f"window.HOTPOT_CONFIG = {json.dumps(config)};\n"
        self.send_response(200)
        self.send_header("Content-Type", "application/javascript; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(body.encode("utf-8"))

    def _proxy_to_hub(self, body=None, method="GET") -> None:
        """将请求转发到本地 Hub API"""
        try:
            import urllib.request
            hub_base = f"http://127.0.0.1:{_port + 1}"  # Hub 运行在 port+1
            url = f"{hub_base}{self.path}"
            query = urlparse(self.path).query
            if query and "?" not in url:
                url = f"{hub_base}{self.path.split('?')[0]}?{query}"

            req_data = body
            req = urllib.request.Request(url, data=req_data, method=method)
            for key in ["Content-Type", "Authorization"]:
                val = self.headers.get(key)
                if val:
                    req.add_header(key, val)

            with urllib.request.urlopen(req, timeout=30) as resp:
                status = resp.status
                resp_body = resp.read()
                content_type = resp.headers.get("Content-Type", "application/json")

            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(resp_body)
        except Exception as e:
            # Hub 未就绪时返回友好错误
            if "refused" in str(e).lower() or "connection" in str(e).lower():
                self.send_response(503)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                error_json = json.dumps({
                    "detail": "Hub API 启动中，请稍后刷新页面",
                    "status": "starting",
                }, ensure_ascii=False)
                self.wfile.write(error_json.encode())
            else:
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                error_json = json.dumps({"detail": str(e)}, ensure_ascii=False)
                self.wfile.write(error_json.encode())

    def log_message(self, format, *args):
        """精简日志"""
        sys.stderr.write(f"[Dashboard] {args[0]}\n")


# ============================================================
# Hub API 启动（子线程）
# ============================================================
def start_hub_api(port: int, seed_data: bool = False) -> None:
    """在子线程中启动 FastAPI Hub"""
    global _hub_url
    _hub_url = f"http://127.0.0.1:{port}"

    # 设置环境变量
    os.environ["HOTPOT_AUTH_MODE"] = "demo"
    os.environ["HOTPOT_DB"] = str(DEMO_DATA_DIR / "hub_cloud.db")
    if seed_data:
        os.environ["HOTPOT_SEED_DIR"] = str(DEMO_DATA_DIR / "stores")

    def _run():
        import uvicorn
        _hub_ready.set()
        uvicorn.run(
            "cloud.event_hub.app:app",
            host="127.0.0.1",
            port=port,
            log_level="warning",
        )

    t = threading.Thread(target=_run, daemon=True)
    t.start()


# ============================================================
# Demo 数据初始化
# ============================================================
def init_demo_data() -> dict:
    """初始化演示数据（门店、用户、基础数据）"""
    stats = {"stores": 0, "users": 0, "products": 0}

    # 确保 demo/data 目录存在
    DEMO_DATA_DIR.mkdir(parents=True, exist_ok=True)

    # 创建种子数据目录
    stores_dir = DEMO_DATA_DIR / "stores"
    stores_dir.mkdir(exist_ok=True)

    # 椒江店（标杆店）
    store_jj = {
        "store_id": "store_jiaojiang",
        "name": "冯校长火锅·椒江店",
        "region": "台州",
        "type": "flagship",
        "tables": 18,
        "address": "浙江省台州市椒江区",
        "manager": "张店长",
        "phone": "0576-88880001",
        "status": "active",
    }
    with open(stores_dir / "store_jiaojiang.json", "w", encoding="utf-8") as f:
        json.dump(store_jj, f, ensure_ascii=False, indent=2)
    stats["stores"] += 1

    # 玉环店（改善店）
    store_yh = {
        "store_id": "store_yuhuan",
        "name": "冯校长火锅·玉环店",
        "region": "台州",
        "type": "standard",
        "tables": 14,
        "address": "浙江省台州市玉环市",
        "manager": "李店长",
        "phone": "0576-88880002",
        "status": "active",
    }
    with open(stores_dir / "store_yuhuan.json", "w", encoding="utf-8") as f:
        json.dump(store_yh, f, ensure_ascii=False, indent=2)
    stats["stores"] += 1

    # Demo 用户
    users = [
        {"username": "zhangdian", "password": "demo", "name": "张店长", "role": "店长", "store_id": "store_jiaojiang"},
        {"username": "lidian", "password": "demo", "name": "李店长", "role": "店长", "store_id": "store_yuhuan"},
        {"username": "chushi", "password": "demo", "name": "王厨师长", "role": "厨师长", "store_id": "store_jiaojiang"},
        {"username": "pangu", "password": "demo", "name": "潘总", "role": "区域督导", "store_id": "store_jiaojiang"},
        {"username": "admin", "password": "admin", "name": "系统管理员", "role": "总部PMO", "store_id": "store_jiaojiang"},
    ]
    with open(stores_dir / "users.json", "w", encoding="utf-8") as f:
        json.dump(users, f, ensure_ascii=False, indent=2)
    stats["users"] = len(users)

    print(f"✅ Demo 数据已初始化: {stats}")
    return stats


# ============================================================
# 主入口
# ============================================================
def main() -> None:
    global _port

    parser = argparse.ArgumentParser(description="火瞳平台端 — 云端部署服务器")
    parser.add_argument("--port", type=int, default=8080, help="Dashboard 端口 (默认 8080)")
    parser.add_argument("--hub-port", type=int, default=0, help="Hub API 端口 (默认 port+1)")
    parser.add_argument("--init-data", action="store_true", help="初始化 Demo 数据")
    parser.add_argument("--hub-only", action="store_true", help="仅启动 Hub API（不启动 Dashboard）")
    args = parser.parse_args()

    _port = args.port
    hub_port = args.hub_port or (_port + 1)

    print("=" * 56)
    print(f"  🔥 火瞳 Hotpot Smart Ops — 云端部署服务器")
    print("=" * 56)
    print(f"  Dashboard: http://0.0.0.0:{_port}")
    print(f"  Hub API:   http://127.0.0.1:{hub_port}")
    print(f"  项目根目录: {PROJECT_ROOT}")
    print(f"  Dashboard:  {DASHBOARD_DIR}")
    print("=" * 56)

    # 验证目录
    if not DASHBOARD_DIR.exists():
        print(f"❌ Dashboard 目录不存在: {DASHBOARD_DIR}")
        sys.exit(1)

    # 初始化 Demo 数据
    if args.init_data:
        init_demo_data()

    # 启动 Hub API（子线程）
    print("\n🚀 启动 Hub API...")
    start_hub_api(hub_port, seed_data=args.init_data)

    # 等待 Hub 就绪
    if not _hub_ready.wait(timeout=10):
        print("⚠️ Hub API 启动超时，部分功能可能不可用")

    time.sleep(1)  # 让 Hub 完全就绪

    if args.hub_only:
        print(f"\n✅ Hub API 运行中 (端口 {hub_port})，按 Ctrl+C 停止")
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            print("\n👋 已停止")
        return

    # 启动 Dashboard 静态服务器（主线程）
    print(f"🚀 启动 Dashboard 静态服务器 (端口 {_port})...")
    print(f"\n{'=' * 56}")
    print(f"  📱 访问地址:")
    print(f"     登录页:  http://localhost:{_port}/login.html")
    print(f"     首页:    http://localhost:{_port}/home.html")
    print(f"     CEO驾驶舱: http://localhost:{_port}/ceo-cockpit.html")
    print(f"     手机版:  http://localhost:{_port}/mobile/index.html")
    print(f"     样式指南: http://localhost:{_port}/styleguide.html")
    print(f"{'=' * 56}\n")

    server = ThreadingHTTPServer(("0.0.0.0", _port), CloudDashboardHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n\n👋 服务器已停止")
        server.shutdown()


if __name__ == "__main__":
    main()
