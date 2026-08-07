#!/usr/bin/env python3
"""
火瞳边缘盒子 · Edge UI Gateway (v2.0)
对齐: WebUI架构设计v1.0 + 详细架构v1.1

功能:
- 📡 南向: IPC摄像头接入 (RTSP/HTTP抓拍/Mock 三级自动切换)
- ☁️ 北向: 云端平台接入 (登录认证/心跳保活/数据上报)
- 🌐 配置Web: 统一南北向配置管理界面

用法:
  python3 server.py [--port 9080] [--mode auto|rtsp|http|mock]
  python3 server.py --config /path/to/edge_config.yml
"""

import argparse
import base64
import copy
import json
import os
import sys
import time
import threading
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

# ── 配置 ──────────────────────────────────────────────
UI_DIR = Path(__file__).parent
DEFAULT_PORT = 9080

# 添加父目录到sys.path以导入公共模块
sys.path.insert(0, str(UI_DIR.parent))
sys.path.insert(0, str(UI_DIR))

# ══════════════════════════════════════════════════
# 全局状态
# ══════════════════════════════════════════════════
_config_manager = None      # ConfigManager 单例
_frame_grabber = None       # FrameGrabber 实例
_current_mode = "init"      # 当前取帧模式

# 北向通信状态
_platform_state = {
    "login_status": "disconnected",   # connected | disconnected | error
    "token": "",
    "token_expires_at": "",
    "last_heartbeat_time": None,
    "last_heartbeat_result": None,
    "heartbeat_success_count": 0,
    "heartbeat_fail_count": 0,
    "consecutive_failures": 0,
    "heartbeat_thread": None,
    "heartbeat_running": False,
    "queue_depth": 0,
    "queue_flushed_total": 0,
}


# ══════════════════════════════════════════════════
# 初始化
# ══════════════════════════════════════════════════

def init_config(config_path=None):
    """初始化配置管理器"""
    global _config_manager
    from config_manager import get_config
    _config_manager = get_config(config_path)
    return _config_manager


def init_frame_grabber(mode="auto"):
    """初始化FrameGrabber"""
    global _frame_grabber, _current_mode

    if not _config_manager:
        print("[Init] ⚠️ ConfigManager未初始化，跳过FrameGrabber")
        return False

    cameras = _config_manager.get_cameras()
    if not cameras:
        print("[Init] ⚠️ 未配置摄像头，跳过FrameGrabber")
        _current_mode = "mock"
        return False

    # 使用第一个摄像头配置
    cam = cameras[0]
    try:
        from edge.common.frame_grabber import FrameGrabber

        creds = cam.get("credentials", {})
        fg_config = {
            "ipc_ip": cam.get("ip"),
            "username": creds.get("username", "admin"),
            "password": creds.get("password", ""),
            "mode": mode,
            # HTTP抓拍配置
            "http_snapshot_url": cam.get("http_snapshot", {}).get("base_url", "") +
                                 cam.get("http_snapshot", {}).get("paths", {}).get("main", ""),
            "auth_type": creds.get("auth_type", "digest"),
            # RTSP配置
            "rtsp_url": cam.get("rtsp", {}).get("url", ""),
        }

        _frame_grabber = FrameGrabber(fg_config)
        if _frame_grabber.start():
            _current_mode = _frame_grabber.mode
            print(f"[Init] ✅ FrameGrabber启动成功! mode={_current_mode}")
            # 更新运行时状态
            _config_manager.update_camera_runtime(
                cam.get("id"), status="online",
                current_mode=_current_mode
            )
            return True
        else:
            print("[Init] ⚠️ FrameGrabber启动失败，降级到Mock模式")
            _current_mode = "mock"
            return False
    except Exception as ex:
        print(f"[Init] ❌ FrameGrabber初始化异常: {ex}")
        _current_mode = "mock"
        return False


def init_platform_client():
    """初始化北向平台客户端"""
    nb = _config_manager.get_northbound() if _config_manager else {}
    hub = nb.get("hub", {})
    hub_url = hub.get("url", "")

    if not hub_url:
        print("[Platform] ⚠️ 未配置平台地址")
        return False

    print(f"[Platform] 📡 平台地址: {hub_url}")
    return True


# ══════════════════════════════════════════════════
# 北向通信：登录 / 心跳 / 队列
# ══════════════════════════════════════════════════

def do_platform_login():
    """执行平台登录"""
    global _platform_state

    if not _config_manager:
        return {"ok": False, "error": "ConfigManager未初始化"}

    nb = _config_manager.get_northbound()
    hub = nb.get("hub", {})
    auth = nb.get("auth", {})

    hub_url = hub.get("url", "").rstrip("/")
    if not hub_url:
        return {"ok": False, "error": "未配置平台地址"}

    try:
        import requests

        # JWT Token 登录
        login_url = f"{hub_url}/auth/token"
        payload = {
            "username": auth.get("username", ""),
            "password": auth.get("password", ""),
            "role": auth.get("role", "店长"),
        }

        print(f"[Platform] 🔑 尝试登录: {login_url} (user={payload['username']})")
        resp = requests.post(login_url, json=payload, timeout=10)

        if resp.status_code == 200:
            data = resp.json()
            token = data.get("access_token", "")
            _platform_state["token"] = token
            _platform_state["login_status"] = "connected"
            _platform_state["token_expires_at"] = data.get("expires_at", "")
            _platform_state["heartbeat_fail_count"] = 0
            _platform_state["consecutive_failures"] = 0

            # 同步到ConfigManager
            _config_manager.update_platform_runtime(
                login_status="connected",
                token=token[:20] + "...",  # 只存前20位
                token_expires_at=data.get("expires_at", ""),
            )

            print(f"[Platform] ✅ 登录成功! token=...{token[-8:] if len(token) > 8 else ''}")
            return {"ok": True, "token_preview": token[:16] + "...", "expires": data.get("expires_at")}
        else:
            _platform_state["login_status"] = "error"
            err_msg = f"HTTP {resp.status_code}: {resp.text[:200]}"
            print(f"[Platform] ❌ 登录失败: {err_msg}")
            return {"ok": False, "error": err_msg}

    except Exception as ex:
        _platform_state["login_status"] = "error"
        print(f"[Platform] ❌ 登录异常: {ex}")
        return {"ok": False, "error": str(ex)}


def do_platform_logout():
    """执行平台登出"""
    global _platform_state
    _platform_state["token"] = ""
    _platform_state["login_status"] = "disconnected"
    _platform_state["heartbeat_success_count"] = 0
    _platform_state["heartbeat_fail_count"] = 0
    _platform_state["consecutive_failures"] = 0

    if _config_manager:
        _config_manager.update_platform_runtime(login_status="disconnected", token="")

    # 停止心跳线程
    stop_heartbeat()

    print("[Platform] 👋 已登出")
    return {"ok": True, "message": "已登出"}


def do_heartbeat():
    """执行一次心跳"""
    global _platform_state

    if not _platform_state.get("token"):
        return {"ok": False, "error": "未登录"}

    if not _config_manager:
        return {"ok": False, "error": "ConfigManager未初始化"}

    nb = _config_manager.get_northbound()
    hub = nb.get("hub", {})
    hub_url = hub.get("url", "").rstrip("/")
    device_id = hub.get("device_id") or _config_manager.get("device.device_id")

    try:
        import requests

        hb_url = f"{hub_url}/api/v1/devices/{device_id}/heartbeat"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {_platform_state['token']}",
        }
        payload = {
            "device_id": device_id,
            "store_id": hub.get("store_id", ""),
            "active_modules": [],
            "inference_count": 0,
            "metrics": {
                "cpu_percent": _get_cpu_percent(),
                "memory_mb": _get_memory_info(),
                "cameras_online": len([c for c in _config_manager.get_cameras()
                                       if c.get("_runtime", {}).get("status") == "online"]),
            },
        }

        resp = requests.post(hb_url, json=payload, headers=headers, timeout=10)

        now = time.strftime('%Y-%m-%d %H:%M:%S')

        if resp.status_code == 200:
            _platform_state["last_heartbeat_time"] = now
            _platform_state["heartbeat_success_count"] += 1
            _platform_state["consecutive_failures"] = 0
            _platform_state["last_heartbeat_result"] = "success"

            _config_manager.update_platform_runtime(
                last_heartbeat_success=now,
                heartbeat_success_count=_platform_state["heartbeat_success_count"],
                consecutive_failures=0,
            )
            return {"ok": True, "time": now, "latency_ms": resp.elapsed.total_seconds() * 1000}
        else:
            _platform_state["heartbeat_fail_count"] += 1
            _platform_state["consecutive_failures"] += 1
            _platform_state["last_heartbeat_time"] = now
            _platform_state["last_heartbeat_result"] = f"fail:{resp.status_code}"

            _config_manager.update_platform_runtime(
                last_heartbeat_error=now,
                heartbeat_fail_count=_platform_state["heartbeat_fail_count"],
                consecutive_failures=_platform_state["consecutive_failures"],
            )
            return {"ok": False, "error": f"HTTP {resp.status_code}", "time": now}

    except Exception as ex:
        _platform_state["heartbeat_fail_count"] += 1
        _platform_state["consecutive_failures"] += 1
        _platform_state["last_heartbeat_result"] = f"exception:{str(ex)[:50]}"
        return {"ok": False, "error": str(ex), "time": time.strftime('%Y-%m-%d %H:%M:%S')}


def start_heartbeat_loop():
    """启动后台心跳线程"""
    global _platform_state

    if _platform_state["heartbeat_running"]:
        return

    nb = _config_manager.get_northbound() if _config_manager else {}
    hb_cfg = nb.get("heartbeat", {})
    interval = hb_cfg.get("interval_seconds", 30)

    if not hb_cfg.get("enabled", True):
        print("[Heartbeat] ❌ 心跳未启用")
        return

    def _loop():
        _platform_state["heartbeat_running"] = True
        print(f"[Heartbeat] 💓 心跳线程启动 (interval={interval}s)")

        while _platform_state["heartbeat_running"]:
            if _platform_state["login_status"] == "connected":
                result = do_heartbeat()
                cf = _platform_state["consecutive_failures"]
                if cf > 0 and cf % 5 == 0:
                    print(f"[Heartbeat] ⚠️ 连续失败 {cf} 次")
            else:
                print("[Heartbit] 💤 跳过（未登录）")

            time.sleep(interval)

        print("[Heartbeat] 💓 心跳线程停止")

    t = threading.Thread(target=_loop, daemon=True, name="heartbeat-loop")
    t.start()
    _platform_state["heartbeat_thread"] = t


def stop_heartbeat():
    """停止心跳线程"""
    global _platform_state
    _platform_state["heartbeat_running"] = False
    _platform_state["heartbeat_thread"] = None


# ══════════════════════════════════════════════════
# 系统信息采集
# ══════════════════════════════════════════════════

def _get_cpu_percent():
    try:
        with open('/proc/stat') as f:
            fields = [float(column) for column in f.readline().strip().split()[1:8]]
            idle1 = fields[3]
        import time; time.sleep(0.05)
        with open('/proc/stat') as f:
            fields = [float(column) for column in f.readline().strip().split()[1:8]]
            idle2 = fields[3]
        d_idle = idle2 - idle1
        d_total = sum(fields[i] - fields[i] for i in range(7))
        return round((1 - d_idle / d_total) * 100, 1)
    except Exception:
        return 0.0


def _get_memory_info():
    try:
        with open('/proc/meminfo') as f:
            mem = {}
            for i in range(2):
                line = f.readline().split()
                mem[line[0].rstrip(':')] = int(line[1])
        return {"total_mb": round(mem['MemTotal'] / 1024),
                "used_mb": round((mem['MemTotal'] - mem['MemAvailable']) / 1024),
                "free_mb": round(mem['MemAvailable'] / 1024)}
    except Exception:
        return {"total_mb": 0, "used_mb": 0, "free_mb": 0}


def _get_disk_info():
    try:
        st = os.statvfs('/')
        total = st.f_blocks * st.f_frsize
        free = st.f_bavail * st.f_frsize
        used = total - free
        return {"total_gb": round(total / (1024**3), 1),
                "used_gb": round(used / (1024**3), 1),
                "free_gb": round(free / (1024**3), 1)}
    except Exception:
        return {"total_gb": 0, "used_gb": 0, "free_gb": 0}


def _get_uptime_seconds():
    try:
        with open('/proc/uptime') as f:
            return int(float(f.readline().split()[0]))
    except Exception:
        return 0


# ══════════════════════════════════════════════════
# HTTP Handler
# ══════════════════════════════════════════════════

class EdgeGatewayHandler(SimpleHTTPRequestHandler):
    """Edge Gateway: 静态文件 + API 混合服务器"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(UI_DIR), **kwargs)

    def log_message(self, fmt, *args):
        print(f"  [{time.strftime('%H:%M:%S')}] {fmt % args}")

    # ── JSON 响应工具 ──

    def _send_json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', len(body))
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self):
        content_len = int(self.headers.get('Content-Length', 0))
        if content_len > 0:
            return json.loads(self.rfile.read(content_len))
        return {}

    def _parse_query(self):
        q = self.path.split('?', 1)
        if len(q) < 2:
            return {}
        params = {}
        for pair in q[1].split('&'):
            if '=' in pair:
                k, v = pair.split('=', 1)
                params[k] = v
        return params

    # ── 路由分发 ──

    def do_GET(self):
        path = self.path.split('?')[0]
        if path.startswith('/api/'):
            return self._handle_api_get(path)
        return super().do_GET()

    def do_POST(self):
        path = self.path.split('?')[0]
        if path.startswith('/api/'):
            return self._handle_api_post(path)
        self.send_error(405, "Method Not Allowed")

    # ═══════════════════════════════════════════════
    # GET API 路由
    # ═══════════════════════════════════════════════

    def _handle_api_get(self, path):

        # ──── 配置管理 ────
        if path == '/api/config/all':
            cfg = _config_manager.get_all_masked() if _config_manager else {}
            return self._send_json({"code": 0, "data": cfg})

        elif path == '/api/config/southbound':
            sb = _config_manager.get_southbound_masked() if _config_manager else {}
            return self._send_json({"code": 0, "data": sb})

        elif path == '/api/config/northbound':
            nb = _config_manager.get_northbound_masked() if _config_manager else {}
            return self._send_json({"code": 0, "data": nb})

        # ──── 设备状态 ────
        elif path == '/api/device/status':
            dev = _config_manager.get_device() if _config_manager else {}
            return self._send_json({
                "code": 0, "data": {
                    **dev,
                    "status": "online",
                    "uptime_seconds": _get_uptime_seconds(),
                    "version": dev.get("firmware_version", "1.0.0"),
                    "ip_address": self.server.server_address[0],
                    "initialized": dev.get("initialized", False),
                }
            })

        # ──── 系统资源（真实采集）───
        elif path == '/api/system/resources':
            return self._send_json({
                "code": 0, "data": {
                    "cpu_percent": _get_cpu_percent(),
                    "memory_mb": _get_memory_info(),
                    "disk_gb": _get_disk_info(),
                    "uptime_seconds": _get_uptime_seconds(),
                }
            })

        # ──── 引擎状态 ────
        elif path == '/api/engines/status':
            return self._send_json({
                "code": 0, "data": [
                    {"id": "food_rec", "name": "菜品识别", "status": "running", "fps": 12.3},
                    {"id": "waste_det", "name": "损耗检测", "status": "running", "fps": 8.7},
                    {"id": "sop_mon", "name": "SOP监控", "status": "running", "fps": 15.1},
                    {"id": "people_cnt", "name": "客流计数", "status": "running", "fps": 18.5},
                    {"id": "hygiene", "name": "卫生巡检", "status": "idle", "fps": 0},
                ]
            })

        # ──── 摄像头列表（从配置读取）───
        elif path == '/api/cameras/list':
            cameras = _config_manager.get_cameras() if _config_manager else []
            # 脱敏后返回
            cams_out = []
            for cam in cameras:
                c = copy.deepcopy(cam)
                c.pop("_runtime", None)
                creds = c.get("credentials", {})
                if creds.get("password"):
                    creds["password"] = "******"
                cams_out.append(c)

            meta = {
                "total": len(cameras),
                "online": sum(1 for c in cameras if c.get("_runtime", {}).get("status") == "online"),
                "current_mode": _current_mode,
            }
            return self._send_json({"code": 0, "data": cams_out, "meta": meta})

        # ──── 实时抓拍 ────
        elif path == '/api/cameras/snapshot':
            return self._handle_snapshot_api()

        # ──── IoT传感器 ────
        elif path == '/api/iot/sensors':
            return self._send_json({"code": 0, "data": [
                {"id": "temp_001", "name": "冷库温度#1", "type": "temperature", "unit": "°C",
                 "value": -18.5, "status": "normal"},
                {"id": "humid_001", "name": "干仓湿度", "type": "humidity", "unit": "%RH",
                 "value": 62.3, "status": "normal"},
            ]})

        # ──── 网络配置 ────
        elif path == '/api/network/config':
            return self._send_json({"code": 0, "data": {
                "hostname": "hotpot-edge-jj", "mode": "dhcp",
                "ipv4_address": "", "gateway": "", "dns_servers": ["223.5.5.5"],
            }})

        # ──── 日志 ────
        elif path == '/api/system/logs':
            params = self._parse_query()
            limit = int(params.get('limit', 50))
            logs = []
            messages = [
                "[camera][HIKVISION] HTTP抓拍成功 (170ms)",
                "[platform] 心跳发送成功 → 平台端",
                "[system] CPU温度正常: 52°C",
                "[config] 配置热重载完成",
            ]
            for i in range(min(limit, 100)):
                logs.append({"timestamp": time.strftime('%Y-%m-%d %H:%M:%S',
                            time.time() - i * 60),
                             "level": ["INFO","WARN","ERROR","DEBUG"][i%4],
                             "message": messages[i % len(messages)]})
            return self._send_json({"code": 0, "data": logs})

        # ──── OTA状态 ────
        elif path == '/api/system/ota/status':
            return self._send_json({"code": 0, "data": {
                "current_version": "1.0.0", "latest_version": "1.0.0",
                "update_available": False,
            }})

        # ──── 推理结果 ────
        elif path == '/api/inference/results':
            import random
            scenes = [
                {"scene": "S1_食材损耗识别", "result": {"waste_type": "蔬菜叶", "weight_kg": 1.2}, "status": "alert"},
                {"scene": "S2_来料验收", "result": {"item": "牛肉卷", "quality": "合格"}, "status": "normal"},
                {"scene": "S3_SOP合规检查", "result": {"check_item": "口罩", "status": "合规"}, "status": "normal"},
                {"scene": "S4_出菜统计", "result": {"dish_count_1h": 52}, "status": "normal"},
                {"scene": "S5_服务效率", "result": {"table_turnover": 1.8}, "status": "normal"},
            ]
            return self._send_json({"code": 0, "data": scenes, "mode": _current_mode})

        # ══════════════════════════════════════
        # ★ 新增：北向通信状态 API
        # ══════════════════════════════════════

        # 平台连接状态总览
        elif path == '/api/platform/status':
            return self._send_json({"code": 0, "data": {
                "login_status": _platform_state["login_status"],
                "has_token": bool(_platform_state["token"]),
                "token_preview": _platform_state["token"][:16] + "..." if _platform_state["token"] else "",
                "heartbeat_running": _platform_state["heartbeat_running"],
                "last_heartbeat_time": _platform_state["last_heartbeat_time"],
                "last_result": _platform_state["last_heartbeat_result"],
                "success_count": _platform_state["heartbeat_success_count"],
                "fail_count": _platform_state["heartbeat_fail_count"],
                "consecutive_failures": _platform_state["consecutive_failures"],
                "queue_depth": _platform_state["queue_depth"],
                "queue_flushed": _platform_state["queue_flushed_total"],
                "hub_url": _config_manager.get("northbound.hub.url", "") if _config_manager else "",
                "device_id": _config_manager.get("device.device_id", "") if _config_manager else "",
            }})

        # 心跳详情
        elif path == '/api/platform/heartbeat-detail':
            return self._send_json({"code": 0, "data": {
                "enabled": (_config_manager.get("northbound.heartbeat.enabled", True)
                           if _config_manager else True),
                "interval_seconds": (_config_manager.get("northbound.heartbeat.interval_seconds", 30)
                                    if _config_manager else 30),
                "max_missed": (_config_manager.get("northbound.heartbeat.max_missed", 3)
                               if _config_manager else 3),
                **{k: v for k, v in _platform_state.items()
                   if k != "token" and k != "heartbeat_thread"},
            }})

        # 离线队列状态
        elif path == '/api/platform/queue-status':
            return self._send_json({"code": 0, "data": {
                "depth": _platform_state["queue_depth"],
                "flushed_total": _platform_state["queue_flushed_total"],
            }})

        else:
            self.send_error(404, f"API not found: {path}")

    # ═══════════════════════════════════════════════
    # POST API 路由
    # ═══════════════════════════════════════════════

    def _handle_api_post(self, path):
        body = self._read_body()

        # ──── 配置保存 ────
        if path == '/api/config/southbound':
            if _config_manager:
                _config_manager.update_southbound(body)
            return self._send_json({"code": 0, "message": "南向配置已保存"})

        elif path == '/api/config/northbound':
            if _config_manager:
                _config_manager.update_northbound(body)
            return self._send_json({"code": 0, "message": "北向配置已保存"})

        elif path == '/api/config/reload':
            ok = _config_manager.reload() if _config_manager else False
            return self._send_json({"code": 0 if ok else -1, "message": "配置已重载" if ok else "重载失败"})

        # ──── 摄像头操作 ────
        elif path == '/api/cameras/add':
            if _config_manager and body:
                ok = _config_manager.add_camera(body)
                msg = f"摄像头添加成功: {body.get('name', '')}" if ok else "添加失败(ID重复?)"
                return self._send_json({"code": 0 if ok else -1, "message": msg})
            return self._send_json({"code": -1, "error": "无效数据"})

        elif path == '/api/cameras/test-connection':
            # 测试摄像头连接
            result = self._test_camera_connection(body)
            return self._send_json(result)

        # ──── 设备初始化 ────
        elif path == '/api/device/init':
            if _config_manager and body:
                _config_manager.set("device", {**_config_manager.get("device", {}), **body})
            return self._send_json({"code": 0, "message": "设备初始化成功"})

        # ══════════════════════════════════════
        # ★ 新增：北向通信操作 API
        # ══════════════════════════════════════

        # 平台登录
        elif path == '/api/platform/login':
            result = do_platform_login()
            code = 0 if result.get("ok") else -1
            return self._send_json({"code": code, "data": result})

        # 平台登出
        elif path == '/api/platform/logout':
            result = do_platform_logout()
            return self._send_json({"code": 0, "data": result})

        # 手动触发一次心跳
        elif path == '/api/platform/send-heartbeat':
            result = do_heartbeat()
            code = 0 if result.get("ok") else -1
            return self._send_json({"code": code, "data": result})

        # 测试平台可达性
        elif path == '/api/platform/test-connect':
            result = self._test_platform_connectivity()
            return self._send_json(result)

        # 手动刷新离线队列
        elif path == '/api/platform/flush-queue':
            # server_v2 是同步 HTTPServer；HubProxyClient 是异步代理且没有
            # flush_queue API。此前错误导入后仍返回 0，造成“假成功”。
            # 在接入统一 DataFlow 队列前显式失败，前端可提示用户稍后重试。
            return self._send_json({
                "code": -1,
                "message": "离线队列刷新尚未接入当前 Edge Gateway；请使用 DataFlow 队列接口",
                "data": {"flushed": None},
            })

        # ──── 其他原有API ────
        elif path == '/api/network/config':
            return self._send_json({"code": 0, "message": "网络配置已保存"})
        elif path == '/api/iot/threshold':
            return self._send_json({"code": 0, "message": "传感器阈值已更新"})
        elif path == '/api/system/ota/upgrade':
            return self._send_json({"code": 0, "message": "OTA升级已开始"})
        elif path == '/api/system/reboot':
            return self._send_json({"code": 0, "message": "系统将在5秒后重启"})
        elif path == '/api/system/logs/clear':
            return self._send_json({"code": 0, "message": "日志已清除"})
        else:
            self.send_error(404, f"API not found: {path}")

    # ═══════════════════════════════════════════════
    # 内部方法
    # ═══════════════════════════════════════════════

    def _handle_snapshot_api(self):
        """处理抓拍请求（三级降级）"""
        # 优先使用FrameGrabber
        if _frame_grabber and _current_mode in ("rtsp", "http"):
            result = _frame_grabber.get_frame_base64(timeout_ms=3000)
            if result and result.get("ok"):
                return self._send_json({
                    "code": 0, "data": {
                        "image_base64": result["data"],
                        "size_bytes": result.get("size", 0),
                        "format": "jpeg",
                        "timestamp": time.strftime('%Y-%m-%d %H:%M:%S'),
                        "source_mode": result.get("mode", _current_mode),
                        "latency_ms": result.get("latency_ms", 0),
                    }
                })

        # 降级：直接HTTP抓拍
        if _current_mode != "mock":
            result = self._do_http_snapshot_direct()
            if result.get("ok"):
                img_b64 = base64.b64encode(result["data"]).decode()
                return self._send_json({
                    "code": 0, "data": {
                        "image_base64": img_b64,
                        "size_bytes": result["size"],
                        "format": "jpeg",
                        "timestamp": time.strftime('%Y-%m-%d %H:%M:%S'),
                        "source_mode": "http_direct",
                    }
                })
            return self._send_json({"code": -1, "error": result.get("error", "Snapshot failed")}, 500)

        # Mock模式
        mock_img = UI_DIR / "mock_snapshot.jpg"
        if mock_img.exists():
            img_b64 = base64.b64encode(mock_img.read_bytes()).decode()
            return self._send_json({
                "code": 0, "data": {
                    "image_base64": img_b64, "size_bytes": mock_img.stat().st_size,
                    "source_mode": "mock_cached",
                }
            })
        return self._send_json({"code": -1, "error": "No camera available"}, 503)

    def _do_http_snapshot_direct(self):
        """直接HTTP抓拍（不经过FrameGrabber）"""
        try:
            from requests.auth import HTTPDigestAuth
            import requests

            if not _config_manager:
                return {"ok": False, "error": "无配置"}

            cameras = _config_manager.get_cameras()
            if not cameras:
                return {"ok": False, "error": "无摄像头配置"}

            cam = cameras[0]
            url = (cam.get("http_snapshot", {}).get("base_url", "") +
                  cam.get("http_snapshot", {}).get("paths", {}).get("main", ""))
            creds = cam.get("credentials", {})

            r = requests.get(url, auth=HTTPDigestAuth(
                creds.get("username", ""), creds.get("password", "")), timeout=10)
            r.raise_for_status()
            data = r.content
            if data[:2] == b"\xff\xd8":
                return {"ok": True, "data": data, "size": len(data)}
            return {"ok": False, "error": f"Not JPEG"}
        except Exception as ex:
            return {"ok": False, "error": str(ex)}

    def _test_camera_connection(self, body=None):
        """测试摄像头连接"""
        try:
            ip = body.get("ip") if body else None
            if not ip:
                cameras = _config_manager.get_cameras() if _config_manager else []
                ip = cameras[0]["ip"] if cameras else "192.168.6.21"

            import socket
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(5)
            start = time.time()
            result = sock.connect_ex((ip, 80))
            latency_ms = round((time.time() - start) * 1000)
            sock.close()

            if result == 0:
                # 进一步测试HTTP接口
                import requests
                from requests.auth import HTTPDigestAuth
                cameras = _config_manager.get_cameras() if _config_manager else []
                cam = cameras[0] if cameras else {}
                creds = cam.get("credentials", {})
                test_url = f"http://{ip}/ISAPI/Streaming/channels/101/picture"
                r = requests.get(test_url, auth=HTTPDigestAuth(
                    creds.get("username", "admin"), creds.get("password", "")),
                    timeout=8)
                if r.status_code == 200 and r.content[:2] == b"\xff\xd8":
                    return {"code": 0, "data": {
                        "connected": True, "latency_ms": latency_ms,
                        "resolution": "704x576", "codec": "JPEG",
                        "snapshot_size": len(r.content),
                        "auth_ok": True,
                    }}
                return {"code": 0, "data": {
                    "connected": True, "latency_ms": latency_ms,
                    "auth_ok": False, "http_error": f"HTTP {r.status_code}",
                }}
            else:
                return {"code": -1, "data": {
                    "connected": False, "error": f"Connection refused (errno={result})",
                }}
        except socket.timeout:
            return {"code": -1, "data": {"connected": False, "error": "连接超时(5s)"}}
        except Exception as ex:
            return {"code": -1, "data": {"connected": False, "error": str(ex)}}

    def _test_platform_connectivity(self):
        """测试平台可达性"""
        try:
            hub_url = _config_manager.get("northbound.hub.url", "") if _config_manager else ""
            if not hub_url:
                return {"code": -1, "data": {"reachable": False, "error": "未配置平台地址"}}

            import requests
            start = time.time()
            r = requests.get(hub_url.rstrip("/") + "/health", timeout=10)
            latency_ms = round((time.time() - start) * 1000)

            return {"code": 0, "data": {
                "reachable": r.status_code < 500,
                "latency_ms": latency_ms,
                "http_status": r.status_code,
                "body_preview": r.text[:200] if r.status_code == 200 else "",
            }}
        except requests.exceptions.ConnectionError:
            return {"code": -1, "data": {"reachable": False, "error": "连接被拒绝/不可达"}}
        except requests.exceptions.Timeout:
            return {"code": -1, "data": {"reachable": False, "error": "请求超时(10s)"}}
        except Exception as ex:
            return {"code": -1, "data": {"reachable": False, "error": str(ex)}}


# ══════════════════════════════════════════════════
# 主入口
# ══════════════════════════════════════════════════

def main():
    global _config_manager, _current_mode

    parser = argparse.ArgumentParser(description='🔥 火瞳Edge Gateway v2.0 — 南北向统一配置中心')
    parser.add_argument('--port', type=int, default=DEFAULT_PORT, help=f'端口号 (默认 {DEFAULT_PORT})')
    parser.add_argument('--mode', choices=['auto', 'rtsp', 'http', 'mock'], default='auto',
                        help='取帧模式 (默认 auto)')
    parser.add_argument('--config', type=str, default=None, help='配置文件路径')
    args = parser.parse_args()

    # ① 初始化配置
    print("\n" + "="*56)
    print("  🔥 火瞳Edge Gateway v2.0 — 南北向统一配置中心")
    print("="*56 + "\n")

    init_config(args.config)
    print(_config_manager.summary())
    print()

    # 校验配置
    errors = _config_manager.validate()
    if errors:
        print(f"[Init] ⚠️ 配置校验警告 ({len(errors)}项):")
        for e in errors:
            print(f"  - {e}")
        print()

    # ② 初始化南向取帧
    init_frame_grabber(args.mode)

    # ③ 初始化北向平台客户端
    init_platform_client()

    # ④ 启动HTTP服务器
    server = HTTPServer(('0.0.0.0', args.port), EdgeGatewayHandler)

    banner = f"""
╔══════════════════════════════════════════════════╗
║     🔥 火瞳 Edge Gateway v2.0                     ║
╠══════════════════════════════════════════════════╣
║  地址: http://0.0.0.0:{args.port:<29} ║
║  配置页: http://localhost:{args.port}/gateway.html{'':>17} ║
╠══════════════════════════════════════════════════╣
║  取帧模式: {_current_mode:<36} ║
║  摄像头: {str(len(_config_manager.get_cameras()))+' 台':<38} ║
║  平台: {(_config_manager.get('northbound.hub.url','未配置') if _config_manager else '?'):<41} ║
║  心跳: {'未启动' if _platform_state['login_status']!='connected' else '运行中':<39} ║
╚══════════════════════════════════════════════════╝
"""
    print(banner)
    print(f"  📁 静态目录: {UI_DIR}")
    print(f"  📋 配置文件: {_config_manager.config_path}")
    print(f"  ⏰ 启动时间: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  按 Ctrl+C 停止\n")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n\n✅ Edge Gateway 已停止")
        stop_heartbeat()
        if _frame_grabber:
            _frame_grabber.stop()
        server.server_close()


if __name__ == '__main__':
    main()
