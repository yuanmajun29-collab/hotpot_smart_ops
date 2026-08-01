#!/usr/bin/env python3
"""
火瞳边缘盒子 · Edge UI 本地测试服务器
支持 Mock / RTSP拉流 / HTTP抓拍 三模式自动切换

用法: python3 server.py [--port 9080] [--mode auto|rtsp|http|mock]
"""

import json
import os
import sys
import time
import argparse
import subprocess
import base64
import hashlib
import re
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

# ── 配置 ──────────────────────────────────────────────
UI_DIR = Path(__file__).parent
DEFAULT_PORT = 9080

# 添加父目录到sys.path以导入frame_grabber
sys.path.insert(0, str(UI_DIR.parent))

# ── IPC摄像头配置（椒江店海康NVR）──
IPC_CONFIG = {
    "ip": "192.168.6.21",
    "vendor": "HIKVISION",
    "name": "Camera 01 (海康NVR)",
    "username": "admin",
    "password": "hy898989",
    # RTSP配置
    "rtsp_url": "rtsp://admin:hy898989@192.168.6.21:554/Streaming/Channels/101",
    # HTTP抓拍配置
    "snapshot_url": "http://192.168.6.21/ISAPI/Streaming/channels/101/picture",
    "auth_type": "digest",
    "avg_latency_ms": 170,
}

# ── 全局FrameGrabber实例 ─────────────────────────────
_frame_grabber = None
_current_mode = "init"  # init | rtsp | http | mock


class EdgeUIHandler(SimpleHTTPRequestHandler):
    """静态文件 + Mock API 混合服务器"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(UI_DIR), **kwargs)

    def log_message(self, fmt, *args):
        """简洁日志"""
        print(f"  [{time.strftime('%H:%M:%S')}] {fmt % args}")

    # ── 模式管理 ──────────────────────────────────────

    def _mock_mode(self):
        """检查是否处于模拟模式"""
        return _current_mode == "mock"

    def _get_mode_display(self):
        """获取当前模式的显示信息"""
        mode_info = {
            "rtsp": {"label": "RTSP拉流", "fps": "~25", "status": "active"},
            "http": {"label": "HTTP抓拍", "fps": "~6", "status": "active"},
            "mock": {"label": "模拟数据", "fps": "N/A", "status": "simulated"},
            "init": {"label": "初始化中", "fps": "N/A", "status": "initializing"},
        }
        return mode_info.get(_current_mode, {"label": "未知", "fps": "N/A", "status": "unknown"})

    # ── 取帧方法（优先RTSP → HTTP降级 → Mock兜底）──

    def _do_http_snapshot(self, timeout=10):
        """通过HTTP Digest认证抓取IPC实时JPEG快照（使用requests库）"""
        try:
            from requests.auth import HTTPDigestAuth
            import requests

            url = IPC_CONFIG["snapshot_url"]
            user = IPC_CONFIG["username"]
            pwd = IPC_CONFIG["password"]

            r = requests.get(url, auth=HTTPDigestAuth(user, pwd), timeout=timeout)
            r.raise_for_status()

            data = r.content
            if data[:2] == b"\xff\xd8":  # JPEG magic bytes
                return {"ok": True, "data": data, "size": len(data)}
            return {"ok": False, "error": f"Not JPEG (Content-Type: {r.headers.get('Content-Type','?')})"}
        except Exception as ex:
            return {"ok": False, "error": str(ex)}

    def _do_frame_grabber_snapshot(self):
        """通过FrameGrabber获取最新帧"""
        global _frame_grabber
        if _frame_grabber is None:
            return None
        result = _frame_grabber.get_frame_base64(timeout_ms=3000)
        if result and result.get("ok"):
            import base64
            img_data = base64.b64decode(result["data"])
            return {"ok": True, "data": img_data, "size": len(img_data),
                    "mode": result.get("mode", "?"), "latency_ms": result.get("latency_ms", 0)}
        return None

    def _send_json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', len(body))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = self.path.split('?')[0]

        # API 路由
        if path.startswith('/api/'):
            return self._handle_api_get(path)
        
        # 静态文件（默认行为）
        return super().do_GET()

    def do_POST(self):
        path = self.path.split('?')[0]
        if path.startswith('/api/'):
            return self._handle_api_post(path)
        self.send_error(405, "Method Not Allowed")

    def _handle_api_get(self, path):
        """处理 GET /api/* 请求"""
        
        # 设备状态
        if path == '/api/device/status':
            return self._send_json({
                "code": 0,
                "data": {
                    "device_id": "edge-jiaojiang-001",
                    "device_name": "椒江店-01号盒",
                    "store_name": "冯校长火锅(椒江店)",
                    "status": "online",
                    "uptime_seconds": 172800,
                    "version": "1.0.0",
                    "ip_address": "172.16.1.60",
                    "mac_address": "AA:BB:CC:DD:EE:FF",
                    "initialized": True,
                }
            })

        # 系统资源
        elif path == '/api/system/resources':
            return self._send_json({
                "code": 0,
                "data": {
                    "cpu_percent": 35.2,
                    "cpu_temp_celsius": 52.3,
                    "memory_mb": {"total": 7891, "used": 4520, "free": 3371},
                    "disk_gb": {"total": 28, "used": 12.4, "free": 15.6},
                    "gpu_percent": 42.0,
                    "gpu_memory_mb": {"total": 4096, "used": 1536, "free": 2560},
                    "network_rx_mbps": 2.3,
                    "network_tx_mbps": 0.8,
                }
            })

        # 引擎状态
        elif path == '/api/engines/status':
            return self._send_json({
                "code": 0,
                "data": [
                    {"id": "food_rec", "name": "菜品识别", "status": "running", "fps": 12.3,
                     "model": "yolov8n-food-v2", "uptime_sec": 172800},
                    {"id": "waste_det", "name": "损耗检测", "status": "running", "fps": 8.7,
                     "model": "yolov8n-waste-v1", "uptime_sec": 172800},
                    {"id": "sop_mon", "name": "SOP监控", "status": "running", "fps": 15.1,
                     "model": "yolov8n-sop-v1", "uptime_sec": 172700},
                    {"id": "people_cnt", "name": "客流计数", "status": "running", "fps": 18.5,
                     "model": "yolov8n-person-v1", "uptime_sec": 172750},
                    {"id": "hygiene", "name": "卫生巡检", "status": "idle", "fps": 0,
                     "model": "yolov8n-hygiene-v1", "uptime_sec": 0},
                ]
            })

        # 摄像头列表（椒江店A方案 - 海康IPC HTTP抓拍 ✅）
        elif path == '/api/cameras/list':
            return self._send_json({
                "code": 0,
                "data": [
                    {"id": "cam_a1_main", "name": IPC_CONFIG["name"], "zone": "前厅核心点位(俯拍全厅)",
                     "snapshot_url": IPC_CONFIG["snapshot_url"],
                     "resolution": "1920x1080", "fps": "~6 (HTTP抓拍)", "codec": "JPEG",
                     "status": "online" if not self._mock_mode() else "simulated",
                     "ip": IPC_CONFIG["ip"], "vendor": IPC_CONFIG["vendor"],
                     "model": "海康NVR (HTTP Digest Auth)",
                     "priority": "critical",
                     "auth_type": IPC_CONFIG["auth_type"],
                     "avg_latency_ms": IPC_CONFIG["avg_latency_ms"],
                     "scenes": ["S1_食材损耗识别", "S2_来料验收", "S3_SOP合规检查",
                                "S4_出菜统计", "S5_服务效率", "客流统计"]},
                ],
                "meta": {
                    "total": 1, "online": 1 if not self._mock_mode() else 0,
                    "nvr_ip": "N/A (直连)", "nvr_vendor": "HIKVISION",
                    "rtsp_status": "unavailable (using HTTP snapshot)",
                    "plan": "A方案_HTTP抓拍"
                }
            })

        # 实时抓拍API（RTSP/HTTP/Mock三模式）
        elif path == '/api/cameras/snapshot':
            # 优先使用FrameGrabber
            if _frame_grabber and _current_mode in ("rtsp", "http"):
                result = self._do_frame_grabber_snapshot()
            else:
                result = None

            if result and result["ok"]:
                img_b64 = base64.b64encode(result["data"]).decode()
                return self._send_json({
                    "code": 0,
                    "data": {
                        "image_base64": img_b64,
                        "size_bytes": result["size"],
                        "format": "jpeg",
                        "timestamp": time.strftime('%Y-%m-%d %H:%M:%S'),
                        "camera_id": "cam_a1_main",
                        "source_mode": result.get("mode", _current_mode),
                        "latency_ms": result.get("latency_ms", IPC_CONFIG["avg_latency_ms"]),
                    }
                })
            elif not self._mock_mode():
                # FrameGrabber不可用，尝试直接HTTP
                result = self._do_http_snapshot()
                if result["ok"]:
                    img_b64 = base64.b64encode(result["data"]).decode()
                    return self._send_json({
                        "code": 0, "data": {
                            "image_base64": img_b64, "size_bytes": result["size"],
                            "format": "jpeg", "timestamp": time.strftime('%Y-%m-%d %H:%M:%S'),
                            "camera_id": "cam_a1_main", "source_mode": "http_direct",
                        }
                    })
                return self._send_json({"code": -1, "error": result.get("error", "Snapshot failed")}, 500)
            else:
                # Mock模式：返回之前保存的实机截图或模拟数据
                mock_img_path = UI_DIR / "mock_snapshot.jpg"
                if mock_img_path.exists():
                    with open(mock_img_path, 'rb') as f:
                        mock_data = f.read()
                    img_b64 = base64.b64encode(mock_data).decode()
                    return self._send_json({
                        "code": 0, "data": {
                            "image_base64": img_b64, "size_bytes": len(mock_data),
                            "format": "jpeg", "timestamp": time.strftime('%Y-%m-%d %H:%M:%S'),
                            "camera_id": "cam_a1_main", "source_mode": "mock_cached",
                        }
                    })
                return self._send_json({"code": -1, "error": "No camera available (mock mode)"}, 503)

        # IoT传感器列表
        elif path == '/api/iot/sensors':
            return self._send_json({
                "code": 0,
                "data": [
                    {"id": "temp_001", "name": "冷库温度#1", "type": "temperature", "unit": "°C",
                     "value": -18.5, "threshold_low": -25, "threshold_high": -15, "status": "normal"},
                    {"id": "temp_002", "name": "冷库温度#2", "type": "temperature", "unit": "°C",
                     "value": -16.8, "threshold_low": -25, "threshold_high": -15, "status": "warning"},
                    {"id": "humid_001", "name": "干仓湿度", "type": "humidity", "unit": "%RH",
                     "value": 62.3, "threshold_low": 40, "threshold_high": 70, "status": "normal"},
                    {"id": "power_001", "name": "总功耗", "type": "power", "unit": "W",
                     "value": 1850, "threshold_low": 0, "threshold_high": 3000, "status": "normal"},
                ]
            })

        # 网络配置
        elif path == '/api/network/config':
            return self._send_json({
                "code": 0,
                "data": {
                    "hostname": "hotpot-edge-jj",
                    "mode": "dhcp",
                    "ipv4_address": "172.16.1.60",
                    "netmask": "255.255.255.0",
                    "gateway": "172.16.1.1",
                    "dns_servers": ["223.5.5.5", "114.114.114.114"],
                    "proxy_enabled": False,
                    "proxy_url": "",
                }
            })

        # 日志列表
        elif path == '/api/system/logs':
            params = self._parse_query()
            limit = int(params.get('limit', 50))
            level = params.get('level', '')
            
            logs = []
            levels = ['ERROR', 'WARN', 'INFO', 'DEBUG']
            for i in range(min(limit, 100)):
                lv = levels[i % 4] if not level else level.upper()
                ts = time.strftime('%Y-%m-%d %H:%M:%S', time.time() - i * 60)
                messages = [
                    "[food_rec] 推理帧处理完成: 1920x1080, 耗时 82ms (cam_a1_main)",
                    "[waste_det] S1检测到异常: 食材损耗约1.2kg (海康192.168.6.21)",
                    "[system] CPU温度警告: 当前 58.2°C > 阈值 55°C",
                    "[network] 心跳发送成功: latency=23ms → 平台端",
                    "[ota] 检查更新: 当前 v1.0.0, 最新 v1.0.1",
                    "[sop_mon] S3违规告警: 检测到未佩戴口罩 (置信度0.96)",
                    "[agent] 收到平台配置下发: sop_config_v3",
                    "[camera][HIKVISION] cam_a1_main HTTP抓拍成功 (170ms, 64KB JPEG)",
                ]
                logs.append({"timestamp": ts, "level": lv, "source": "edge-core",
                             "message": messages[i % len(messages)]})
            
            return self._send_json({"code": 0, "data": logs})

        # OTA状态
        elif path == '/api/system/ota/status':
            return self._send_json({
                "code": 0,
                "data": {
                    "current_version": "1.0.0",
                    "latest_version": "1.0.1",
                    "update_available": True,
                    "update_size_mb": 45.2,
                    "release_notes": "- 修复摄像头RTSP断线重连问题\n- 优化内存占用(减少约200MB)\n- 新增IoT传感器阈值告警",
                    "last_check": time.strftime('%Y-%m-%d %H:%M:%S'),
                }
            })

        # 推理结果（椒江店A方案 - 海康IPC实机模式）
        elif path == '/api/inference/results':
            import random
            scenes = [
                {"scene": "S1_食材损耗识别", "camera": "cam_a1_main", "zone": "前厅核心点位(海康)",
                 "result": {"waste_type": random.choice(["蔬菜叶","肉类边角","过期食材","火锅底料"]),
                           "weight_kg": round(random.uniform(0.3, 2.5), 1),
                           "confidence": round(random.uniform(0.85, 0.98), 2)},
                 "timestamp": time.strftime('%Y-%m-%d %H:%M:%S'), "status": "alert"},
                {"scene": "S2_来料验收", "camera": "cam_a1_main", "zone": "前厅核心点位(海康)",
                 "result": {"item": random.choice(["牛肉卷","羊肉卷","蔬菜拼盘","豆制品"]),
                           "quantity": random.randint(5, 20), "quality": random.choice(["合格","合格","合格","异常"])},
                 "timestamp": time.strftime('%Y-%m-%d %H:%M:%S'), "status": "normal"},
                {"scene": "S3_SOP合规检查", "camera": "cam_a1_main", "zone": "前厅核心点位(海康)",
                 "result": {"check_item": random.choice(["厨师帽","口罩","手套","制服"]),
                           "status": random.choice(["合规","合规","合规","违规"]),
                           "confidence": round(random.uniform(0.9, 0.99), 2)},
                 "timestamp": time.strftime('%Y-%m-%d %H:%M:%S'),
                 "status": "warning" if random.random() > 0.7 else "normal"},
                {"scene": "S4_出菜统计", "camera": "cam_a1_main", "zone": "前厅核心点位(海康)",
                 "result": {"dish_count_1h": random.randint(30, 80),
                           "avg_prep_time_s": random.randint(120, 300),
                           "peak_orders": random.randint(10, 25)},
                 "timestamp": time.strftime('%Y-%m-%d %H:%M:%S'), "status": "normal"},
                {"scene": "S5_服务效率", "camera": "cam_a1_main", "zone": "前厅核心点位(海康)",
                 "result": {"table_turnover": round(random.uniform(1.2, 2.8), 1),
                           "avg_dine_time_min": random.randint(45, 90),
                           "customer_count": random.randint(15, 40)},
                 "timestamp": time.strftime('%Y-%m-%d %H:%M:%S'), "status": "normal"},
            ]
            return self._send_json({"code": 0, "data": scenes, "mock_mode": self._mock_mode(),
                                    "plan": "A方案_HTTP抓拍", "camera_ip": IPC_CONFIG["ip"],
                                    "snapshot_available": True})

        else:
            self.send_error(404, f"API not found: {path}")

    def _handle_api_post(self, path):
        """处理 POST /api/* 请求"""
        content_len = int(self.headers.get('Content-Length', 0))
        body = json.loads(self.rfile.read(content_len)) if content_len > 0 else {}

        # 初始化设备
        if path == '/api/device/init':
            return self._send_json({
                "code": 0,
                "message": f"设备初始化成功: {body.get('store_name', '')}",
                "data": {"device_id": f"edge-{body.get('store_id', 'unknown')}-001"}
            })

        # 保存网络配置
        elif path == '/api/network/config':
            return self._send_json({"code": 0, "message": "网络配置已保存，将在重启后生效"})

        # 添加摄像头
        elif path == '/api/cameras/add':
            return self._send_json({
                "code": 0, "message": f"摄像头添加成功: {body.get('name', '')}",
                "data": {"camera_id": f"cam_{int(time.time())}"}
            })

        # 测试摄像头连接
        elif path == '/api/cameras/test':
            return self._send_json({"code": 0, "data": {"connected": True, "latency_ms": 45,
                                        "resolution": "1920x1080", "codec": "H264"}})

        # 更新传感器阈值
        elif path == '/api/iot/threshold':
            return self._send_json({"code": 0, "message": "传感器阈值已更新"})

        # 执行OTA升级
        elif path == '/api/system/ota/upgrade':
            return self._send_json({"code": 0, "message": "OTA升级已开始，请勿断电...",
                                    "data": {"task_id": f"ota-{int(time.time())}"}})

        # 重启系统
        elif path == '/api/system/reboot':
            return self._send_json({"code": 0, "message": "系统将在5秒后重启"})

        # 清除日志
        elif path == '/api/system/logs/clear':
            return self._send_json({"code": 0, "message": "日志已清除"})

        else:
            self.send_error(404, f"API not found: {path}")

    def _parse_query(self):
        """解析查询参数"""
        q = self.path.split('?', 1)
        if len(q) < 2:
            return {}
        params = {}
        for pair in q[1].split('&'):
            if '=' in pair:
                k, v = pair.split('=', 1)
                params[k] = v
        return params


def main():
    global _frame_grabber, _current_mode

    parser = argparse.ArgumentParser(description='火瞳Edge UI 本地测试服务器')
    parser.add_argument('--port', type=int, default=DEFAULT_PORT, help=f'端口号 (默认 {DEFAULT_PORT})')
    parser.add_argument('--mode', choices=['auto', 'rtsp', 'http', 'mock'], default='auto',
                        help='取帧模式: auto(自动) | rtsp | http | mock (默认 auto)')
    args = parser.parse_args()

    # 初始化FrameGrabber（非mock模式）
    if args.mode != 'mock':
        print("📡 初始化FrameGrabber (mode=%s)..." % args.mode)
        try:
            from edge.common.frame_grabber import FrameGrabber
            fg_config = {
                "ipc_ip": IPC_CONFIG["ip"],
                "username": IPC_CONFIG["username"],
                "password": IPC_CONFIG["password"],
                "mode": args.mode,
            }
            _frame_grabber = FrameGrabber(fg_config)
            if _frame_grabber.start():
                _current_mode = _frame_grabber.mode
                print("  ✅ FrameGrabber启动成功! mode=%s" % _current_mode)
            else:
                print("  ⚠️  FrameGrabber启动失败，降级到Mock模式")
                _current_mode = "mock"
        except Exception as ex:
            print("  ❌ FrameGrabber初始化异常: %s" % ex)
            print("  → 降级到Mock模式")
            _current_mode = "mock"
    else:
        _current_mode = "mock"

    server = HTTPServer(('0.0.0.0', args.port), EdgeUIHandler)

    mode_display = EdgeUIHandler._get_mode_display(None) if hasattr(EdgeUIHandler, '_get_mode_display') else {"label": args.mode}
    
    print(f"""
╔══════════════════════════════════════════════╗
║     🔥 火瞳边缘盒子 · Edge UI 测试服务器      ║
╠══════════════════════════════════════════════╣
║  地址: http://localhost:{args.port:<27} ║
║  首页: http://localhost:{args.port}/index.html{'':>13} ║
║  向导: http://localhost:{args.port}/setup.html{'':>13} ║
╠══════════════════════════════════════════════╣
║  取帧模式: {_current_mode:<33} ║
╚══════════════════════════════════════════════╝
    """)
    print(f"  📁 静态文件目录: {UI_DIR}")
    print(f"  ⏰ 启动时间: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  按 Ctrl+C 停止\n")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n\n✅ 服务器已停止")
        if _frame_grabber:
            _frame_grabber.stop()
        server.server_close()


if __name__ == '__main__':
    main()
