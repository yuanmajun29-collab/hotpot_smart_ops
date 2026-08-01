"""
火瞳展会 Web API 服务器
=======================
基于 ExpoDemoRunner 的 HTTP API，为前端提供 JSON 数据接口。

启动方式:
    cd demo/web
    python server.py          # 默认端口 8080
    python server.py --port 9000  # 自定义端口

API 接口:
    GET /api/health           - 健康检查
    GET /api/scenes           - 场景列表
    POST /api/init            - 初始化数据
    POST /api/run/<scene_key> - 运行单个场景
    POST /api/run-all         - 运行全部场景
    GET /api/status           - 获取运行状态
"""

import argparse
import json
import logging
import os
import sys
import threading
import time
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import urlparse

# 确保项目根目录在路径中
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# 全局运行器实例
_runner = None
_runner_lock = threading.Lock()
_run_status: Dict[str, Any] = {
    "initialized": False,
    "current_scene": None,
    "completed_scenes": [],
    "results": {},
    "total_elapsed": 0,
}


class APIHandler(SimpleHTTPRequestHandler):
    """API请求处理器"""

    def __init__(self, *args, **kwargs):
        self.directory = str(Path(__file__).resolve().parent)
        super().__init__(*args, **kwargs)

    def _send_json(self, data: Any, status: int = 200):
        """发送JSON响应"""
        body = json.dumps(data, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", len(body))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _send_error(self, message: str, status: int = 400):
        """发送错误响应"""
        self._send_json({"error": message, "success": False}, status)

    def _read_body(self) -> bytes:
        """读取请求体"""
        content_length = int(self.headers.get("Content-Length", 0))
        return self.rfile.read(content_length) if content_length > 0 else b"{}"

    def do_GET(self):
        """处理GET请求"""
        parsed = urlparse(self.path)

        # API路由
        if parsed.path == "/api/health":
            self._handle_health()
        elif parsed.path == "/api/scenes":
            self._handle_scenes()
        elif parsed.path == "/api/status":
            self._handle_status()
        else:
            # 静态文件服务（index.html等）
            super().do_GET()

    def do_POST(self):
        """处理POST请求"""
        parsed = urlparse(self.path)

        if parsed.path == "/api/init":
            self._handle_init()
        elif parsed.path.startswith("/api/run/"):
            scene_key = parsed.path.split("/api/run/")[-1]
            self._handle_run_scene(scene_key)
        elif parsed.path == "/api/run-all":
            self._handle_run_all()
        else:
            self._send_error(f"未知API路径: {parsed.path}", 404)

    def do_OPTIONS(self):
        """CORS预检请求"""
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def _get_runner(self):
        """获取或创建Runner实例"""
        global _runner
        with _runner_lock:
            if _runner is None:
                from demo.demo_runner import ExpoDemoRunner
                db_path = str(PROJECT_ROOT / "demo" / "data" / "expo_demo.db")
                _runner = ExpoDemoRunner(db_path=db_path, store_id="store_jiaojiang")
            return _runner

    def _handle_health(self):
        """健康检查"""
        self._send_json({
            "success": True,
            "status": "ok",
            "service": "火瞳展会 Demo Web API",
            "version": "1.0.0",
            "initialized": _run_status["initialized"],
        })

    def _handle_scenes(self):
        """返回场景列表"""
        runner = self._get_runner()
        scenes = []
        for key, info in runner.SCENARIOS.items():
            scenes.append({
                "key": key,
                "id": info["id"],
                "name": info["name"],
                "duration_min": info["duration_min"],
                "description": info["description"],
            })
        self._send_json({"success": True, "scenes": scenes})

    def _handle_status(self):
        """获取运行状态"""
        self._send_json({
            "success": True,
            **_run_status,
        })

    def _handle_init(self):
        """初始化演示数据"""
        try:
            body = json.loads(self._read_body())
            days = body.get("days", 30)
        except Exception:
            days = 30

        try:
            runner = self._get_runner()
            logger.info(f"🚀 初始化演示数据 ({days}天)")
            stats = runner.init_data(days=days)

            _run_status["initialized"] = True
            _run_status["completed_scenes"] = []
            _run_status["results"] = {}

            self._send_json({
                "success": True,
                "message": f"演示数据初始化完成 ({days}天)",
                "stats": stats,
            })
        except Exception as e:
            logger.error(f"初始化失败: {e}", exc_info=True)
            self._send_error(f"初始化失败: {str(e)}", 500)

    def _handle_run_scene(self, scene_key: str):
        """运行单个场景"""
        try:
            runner = self._get_runner()

            if not _run_status["initialized"]:
                # 自动初始化
                runner.init_data(days=30)
                _run_status["initialized"] = True

            _run_status["current_scene"] = scene_key
            logger.info(f"▶ 运行场景: {scene_key}")

            start = time.time()
            result = runner.run_scene(scene_key)
            elapsed = round(time.time() - start, 2)
            result["_elapsed_seconds"] = elapsed

            # 更新状态
            if scene_key not in _run_status["completed_scenes"]:
                _run_status["completed_scenes"].append(scene_key)
            _run_status["results"][scene_key] = result
            _run_status["current_scene"] = None

            # 添加场景元信息
            scene_info = runner.SCENARIOS.get(scene_key, {})
            response = {
                "success": True,
                "scenario_id": scene_info.get("id", scene_key),
                "scenario_name": scene_info.get("name", scene_key),
                "elapsed_seconds": elapsed,
                **result,
            }

            self._send_json(response)
            logger.info(f"✅ 场景 {scene_key} 完成 ({elapsed}s)")

        except ValueError as e:
            self._send_error(str(e))
        except Exception as e:
            logger.error(f"场景执行失败: {e}", exc_info=True)
            _run_status["current_scene"] = None
            self._send_error(f"场景执行失败: {str(e)}", 500)

    def _handle_run_all(self):
        """运行全部场景"""
        try:
            runner = self._get_runner()

            if not _run_status["initialized"]:
                runner.init_data(days=30)
                _run_status["initialized"] = True

            logger.info("▶ 运行全部场景")

            results = runner.run_all()

            _run_status["results"] = results
            _run_status["current_scene"] = None
            _run_status["completed_scenes"] = [
                k for k in runner.SCENARIOS.keys() if k in results and "error" not in results[k]
            ]
            _run_status["total_elapsed"] = results.get("_total_elapsed", 0)

            self._send_json({
                "success": True,
                "message": "全部场景执行完成",
                "total_elapsed": results.get("_total_elapsed", 0),
                "run_time": results.get("_run_time"),
                "scenes": results,
            })

        except Exception as e:
            logger.error(f"全量执行失败: {e}", exc_info=True)
            _run_status["current_scene"] = None
            self._send_error(f"执行失败: {str(e)}", 500)

    def log_message(self, format, *args):
        """自定义日志格式"""
        logger.debug(f"{self.address_string()} - {format % args}")


def main():
    parser = argparse.ArgumentParser(description="火瞳展会 Web API 服务器")
    parser.add_argument("--port", type=int, default=8080, help="监听端口 (默认8080)")
    parser.add_argument("--host", type=str, default="0.0.0.0", help="监听地址 (默认0.0.0.0)")
    args = parser.parse_args()

    server = HTTPServer((args.host, args.port), APIHandler)
    logger.info(f"🌐 火瞳展会 Web API 启动成功")
    logger.info(f"   地址: http://{args.host}:{args.port}")
    logger.info(f"   按 Ctrl+C 停止服务")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("\n👋 服务已停止")
        server.server_close()


if __name__ == "__main__":
    main()
