# 火瞳边缘盒子 · 本地 Web UI 架构设计

> **文档版本**: v1.1 (更新)
> **创建日期**: 2026-07-31 → **更新: 2026-08-01**
> **关联产品**: 火瞳_边缘盒子WebUI产品设计_v1.0.md
> **关联代码**: `edge/edge-ui/` (重构中)
>
> ## v1.0→v1.1 变更记录
>
> | 变更项 | v1.0 (原设计) | v1.1 (更新后) | 变因 |
> |--------|:------------:|:------------:|------|
> | 摄像头接入 | 仅 RTSP URL | **RTSP + HTTP抓拍 双模式** | 海康NVR的RTSP端口554不可用，HTTP ISAPI抓拍已验证可行(~170ms/帧) |
> | 取帧引擎 | 未定义 | **FrameGrabber 三级自动切换** | 需要RTSP→HTTP→Mock降级链保证可用性 |
> | 摄像头配置字段 | rtsp_url, resolution, fps, codec | **+http_snapshot, auth_type, credentials, channels** | 实测海康需要Digest Auth + 多通道(Ch101-103, Ch201-202) |
> | 北向通信边界 | 未明确定义 | **Edge UI 只读展示, Agent 负责心跳/上报** | 避免双进程职责重叠 |
> | 配置管理API | 未定义 | **新增 /api/v1/config/*** | 南北向配置需要统一CRUD界面 |
> | 平台状态API | 未定义 | **新增 /api/v1/platform/status (只读)** | Edge UI需展示平台连接状态 |

---

## 1. 技术选型

### 1.1 选型原则

| 原则 | 决策 | 理由 |
|------|------|------|
| 轻量级 | ✅ 纯静态HTML+JS，无构建步骤 | Jetson资源有限，避免Node.js打包链 |
| 零依赖 | ✅ 不引入Vue/React框架 | 减少下载体积、降低复杂度 |
| 复用现有 | ✅ 复用平台端Design Tokens | 视觉一致性 |
| 渐进增强 | ✅ 核心功能无需JS也能工作 | 兼容性保障 |
| **框架对齐** | ✅ **FastAPI (非 http.server)** | 与agent/server.py统一技术栈，复用中间件 |

### 1.2 技术栈

```
┌─────────────────────────────────────────────────────┐
│                    前端技术栈                         │
│                                                     │
│  HTML5 + CSS3 + Vanilla JavaScript (ES6+)           │
│  ├── 无框架（原生DOM操作）                           │
│  ├── CSS变量系统（Design Tokens）                    │
│  ├── Fetch API（HTTP请求）                           │
│  └── SVG图标（内联，无图标库依赖）                    │
│                                                     │
│  第三方库（CDN或本地内嵌，仅2个）：                    │
│  ├── Chart.js (~60KB) — 轻量图表（趋势图/仪表盘）    │
│  └── highlight.js (~40KB) — 日志语法高亮             │
│                                                     │
│  总前端体积目标: < 200KB (gzip后 < 50KB)              │
└─────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────┐
│                    后端技术栈                         │
│                                                     │
│  Python FastAPI（独立进程或集成到 agent/server.py）   │
│  ├── 复用 FastAPI 实例和中间件                       │
│  ├── 新增路由组: /api/v1/ 前缀                      │
│  ├── 静态文件服务: StaticFiles 挂载                  │
│  ├── CORS: 仅允许局域网段                            │
│  └── Session中间件: PIN认证                          │
│                                                     │
│  数据存储:                                          │
│  ├── 设备配置 → JSON文件 (/opt/hotpot-smart-ops/conf/)│
│  ├── 运行状态 → 内存 + 定时采样                      │
│  └── 操作日志 → 文件追加 (/var/log/hotpot/ui.log)   │
│                                                     │
│  不使用数据库（边缘场景，零运维）                      │
└─────────────────────────────────────────────────────┘
```

### 1.3 对比备选方案

| 方案 | 优点 | 缺点 | 决策 |
|------|------|------|------|
| **A: FastAPI + 多页面** ✅ | 统一技术栈、可扩展、自动OpenAPI文档 | 需要拆分模块 | **选中 (v1.1确认)** |
| B: Vue3+Vite构建 | 组件化、开发效率高 | 需要构建步骤、增加复杂度 | 备选 |
| C: Flask+Jinja2模板 | 服务端渲染、SEO友好 | 需要模板引擎、实时性差 | 排除 |
| D: http.server (v1实现) | 最简单、零依赖 | 无中间件、无认证、难扩展 | ❌ **废弃(已验证不满足需求)** |

---

## 2. 目录结构

### 2.1 完整目录树

```
hotpot_smart_ops/
├── edge/
│   ├── agent/
│   │   ├── server.py              # [修改] 新增 /ui/ 路由挂载 (FastAPI :9100)
│   │   └── modules/
│   │
│   └── edge-ui/                   # 边缘盒子 Web UI (FastAPI版)
│       ├── __init__.py            # [新增] FastAPI应用实例 + 路由注册
│       ├── main.py                # [新增] 入口: uvicorn 启动 (:9080)
│       │
│       ├── index.html             # 首页仪表盘
│       ├── setup.html             # 初始化向导
│       ├── cameras.html           # 摄像头管理
│       ├── iot-sensors.html       # IoT传感器管理
│       ├── diagnostics.html       # 诊断工具
│       ├── logs.html              # 日志查看(P1)
│       │
│       ├── system/                # [目录] 系统设置子页面
│       │   ├── network.html       # 网络配置
│       │   ├── hub-settings.html  # Hub连接设置(北向)
│       │   ├── models.html        # 模型管理
│       │   └── ota.html           # OTA升级
│       │
│       ├── assets/                # [目录] 前端资源分离
│       │   ├── edge-ui.css        # 主样式表
│       │   ├── edge-ui.js         # 主逻辑模块
│       │   ├── components.js      # UI组件库(Modal/Toast/Table/Card)
│       │   ├── setup-wizard.js    # 初始化向导逻辑
│       │   ├── api-client.js      # API封装层(错误处理/重试/认证Token)
│       │   └── icons.svg          # SVG精灵图
│       │
│       ├── api/                   # [目录] FastAPI路由模块
│       │   ├── __init__.py        # 路由注册汇总
│       │   ├── system_api.py      # 系统/资源接口
│       │   ├── camera_api.py      # 摄像头CRUD + 快照 + 测试连接
│       │   ├── iot_api.py         # IoT传感器接口
│       │   ├── engine_api.py      # 引擎状态接口
│       │   ├── diagnostics_api.py  # 诊断接口
│       │   ├── config_api.py      # [v1.1新增] 配置管理接口
│       │   └── platform_api.py    # [v1.1新增] 平台状态只读接口
│       │
│       └── conf/                  # [目录] 配置文件(JSON格式)
│           ├── device.json        # 设备基本信息
│           ├── cameras.json       # 摄像头配置(含RTSP+HTTP双模式)
│           ├── iot_sensors.json   # IoT传感器配置
│           ├── hub_connection.json # Hub连接配置(北向)
│           └── ui_settings.json   # UI自身设置
│
├── hotpot_platform/
│   └── dashboard/
│       └── assets/
│           └── theme.css          # [复用] Design Tokens
│
└── conf/                          # [复用] 全局配置(如有)
```

### 2.2 文件职责说明

| 文件/目录 | 行数估计 | 职责 |
|-----------|----------|------|
| `main.py` | ~80 | FastAPI应用工厂 + uvicorn启动 + 路由挂载 |
| `__init__.py` | ~30 | 路由注册 + 共享依赖(Session/ConfigManager) |
| `index.html` | ~300 | 首页仪表盘：设备卡片、引擎状态、南北向连接摘要 |
| `setup.html` | ~250 | 4步初始化向导：门店绑定→摄像头检测→Hub配置→完成 |
| `cameras.html` | ~280 | 摄像头列表、添加/编辑弹窗、实时快照预览 |
| `iot-sensors.html` | ~260 | 传感器表格、阈值编辑、简易图表 |
| `diagnostics.html` | ~220 | 一键诊断、逐项检测展示 |
| `system/*.html` | ~200 each | 各设置页面的表单UI |
| `assets/edge-ui.css` | ~400 | 全局样式、组件样式、响应式 |
| `assets/edge-ui.js` | ~350 | 导航、状态轮询、通用工具函数 |
| `assets/components.js` | ~250 | 可复用UI组件（Modal/Toast/Table/Card） |
| `assets/api-client.js` | ~200 | API请求封装、错误处理、重试逻辑、Session管理 |
| `api/*.py` | ~150 each | FastAPI路由处理器 |

**总代码量预估**: ~4,500 行（前端~2,800 + 后端~1,700）

---

## 3. API 设计

### 3.1 API 总览

所有API以 `/api/v1/` 为前缀，由 FastAPI 应用提供服务。

```
# === 系统 (system_api.py) ===
GET    /api/v1/system/info          设备基本信息
GET    /api/v1/system/resources     系统资源(CPU/内存/GPU/磁盘)
GET    /api/v1/system/uptime        运行时间
GET    /api/v1/system/version       版本信息
PUT    /api/v1/system/network       更新网络配置
POST   /api/v1/system/restart       重启网络服务

# === 摄像头 (camera_api.py) ===
GET    /api/v1/cameras              摄像头列表
POST   /api/v1/cameras              添加摄像头
GET    /api/v1/cameras/{id}         摄像头详情
PUT    /api/v1/cameras/{id}         更新摄像头配置
DELETE /api/v1/cameras/{id}         删除摄像头
POST   /api/v1/cameras/{id}/reconnect 重连摄像头
GET    /api/v1/cameras/{id}/snapshot 摄像头快照(JPEG base64)
POST   /api/v1/cameras/{id}/test    # [v1.1] 测试摄像头连接(IP+端口+Auth)

# === IoT传感器 (iot_api.py) ===
GET    /api/v1/iot/sensors          传感器列表
POST   /api/v1/iot/sensors          添加传感器
GET    /api/v1/iot/sensors/{id}     传感器详情(含当前读数)
PUT    /api/v1/iot/sensors/{id}     更新传感器配置(阈值等)
DELETE /api/v1/iot/sensors/{id}     删除传感器
GET    /api/v1/iot/sensors/{id}/history 传感器历史数据

# === 引擎 (engine_api.py) ===
GET    /api/v1/engines/status       五大引擎状态汇总
GET    /api/v1/engines/{name}/status 单个引擎详情
POST   /api/v1/engines/{name}/restart 重启单个引擎
GET    /api/v1/engines/{name}/logs  引擎日志(最后100行)

# === 诊断 (diagnostics_api.py) ===
POST   /api/v1/diagnostics/run      执行完整诊断(异步)
GET    /api/v1/diagnostics/tasks/{task_id}  轮询诊断结果

# === 配置管理 (config_api.py) [v1.1新增] ===
GET    /api/v1/config              获取全部配置(脱敏)
PUT    /api/v1/config/device        更新设备配置
PUT    /api/v1/config/cameras      更新摄像头配置(批量)
PUT    /api/v1/config/hub          更新Hub连接配置
POST   /api/v1/config/reload        热重载配置(从磁盘)

# === 平台状态 (platform_api.py) [v1.1新增, 只读] ===
GET    /api/v1/platform/status      平台连接状态总览(登录/心跳/队列)
GET    /api/v1/platform/heartbeat-detail 心跳详情(计时器/连续失败)
GET    /api/v1/platform/queue-status 离线队列状态

# === 初始化 (setup) ===
POST   /api/v1/setup/initialize     执行初始化(绑定门店+配置Hub)
GET    /api/v1/setup/status         初始化状态查询

# === OTA ===
POST   /api/v1/ota/check            检查新版本
POST   /api/v1/ota/upgrade          执行OTA升级
GET    /api/v1/ota/status           升级进度查询

# === 模型管理 ===
GET    /api/v1/models               已安装模型列表
POST   /api/v1/models/download      从Hub下载模型
DELETE /api/v1/models/{name}        删除本地模型
POST   /api/v1/models/{name}/activate 激活指定模型

# === 日志 ===
GET    /api/v1/logs                 系统日志(支持分页/过滤)
GET    /api/v1/logs/tail            实时日志流(SSE)
```

### 3.2 核心 API 详细设计

#### 3.2.1 摄像头 API (v1.1 更新: 支持双模式)

```yaml
# 列表
GET /api/v1/cameras
Response 200:
  cameras:
    - id: "cam_kitchen_1"
      name: "后厨主摄像头"
      ip: "192.168.6.21"                    # [v1.1新增]
      vendor: "HIKVISION"                   # [v1.1新增]
      # RTSP配置(可选)
      rtsp_url: "rtsp://192.168.6.21:554/Streaming/Channels/101"
      resolution: "1920x1080"
      fps: 15
      codec: "h264"
      # HTTP抓拍配置(v1.1核心新增)
      http_snapshot:
        base_url: "http://192.168.6.21"
        path: "/ISAPI/Streaming/channels/101/picture"
        auth_type: "digest"                  # digest / basic / none
        avg_latency_ms: 170                   # [v1.1] 实测延迟
      # 认证凭证(存储时加密, API返回时脱敏)
      credentials:
        username: "admin"
        password: "******"                    # 脱敏显示
      # 可用通道列表(v1.1新增, 海康NVR多通道)
      available_channels: [101, 102, 103, 201, 202]
      active_channel: 101                     # 当前使用通道
      # 取帧模式(v1.1新增)
      grabber_mode: "auto"                    # auto / rtsp / http / mock
      purpose: "kitchen_sop"
      enabled: true
      status: "online"                        # online / offline / error
      last_frame_time: "2026-07-31T11:30:05+08:00"
      created_at: "2026-07-15T10:00:00+08:00"

# 添加
POST /api/v1/cameras
Body:
  name: string (required)
  ip: string (required)                       # [v1.1] 必填
  vendor: string (default: "unknown")         # [v1.1]
  rtsp_url: string (optional)                 # RTSP模式时必填
  http_snapshot:                              # [v1.1] HTTP抓拍模式时必填
    base_url: string (required)
    path: string (required)
    auth_type: string (default: "none")
  credentials:                                # [v1.1]
    username: string (required)
    password: string (required)
  active_channel: integer (default: 101)      # [v1.1]
  resolution: string (required)
  fps: integer (required)
  codec: string (required)
  purpose: string (required)
  enabled: boolean (default: true)

Response 201:
  id: "cam_new_1"
  ... (同上，含生成字段)

# 快照 (v1.1: 支持base64返回 + 直接JPEG二进制)
GET /api/v1/cameras/{id}/snapshot?format=base64
Response 200:
  Content-Type: application/json
  {
    "image_base64": "/9j/4AAQ...==",
    "size_bytes": 63938,
    "format": "jpeg",
    "timestamp": "2026-07-31T11:30:05+08:00",
    "source_mode": "http",                    # rtsp / http / mock
    "latency_ms": 170,
    "camera_id": "cam_a1_main"
  }

# 测试连接 [v1.1新增]
POST /api/v1/cameras/{id}/test
Response 200:
  {
    "connected": true,
    "tests":
      [
        {"target": "TCP IP:Port", "status": "pass", "detail": "23ms"},
        {"target": "HTTP Endpoint", "status": "pass", "detail": "200 OK (64KB JPEG)"},
        {"target": "Digest Auth", "status": "pass", "detail": "认证成功"},
      ],
    "resolution": "704x576",
    "latency_ms": 170
  }
Response 503:
  { "connected": false, "error": "Connection timeout" }
```

#### 3.2.2 系统资源 API (不变)

```yaml
GET /api/v1/system/resources
Response 200:
  cpu:
    percent: 42.5
    cores: 6
    freq_mhz: 1400
    temp_celsius: 52.3
  memory:
    total_mb: 7849
    used_mb: 4552
    percent: 58.0
  gpu:
    model: "Orin NX"
    utilization_pct: 38
    memory_used_mb: 2100
    memory_total_mb: 8192
    temperature_celsius: 41
  storage:
    total_gb: 64
    used_gb: 55.8
    percent: 87.2
  uptime_seconds: 1324500
  load_average: [1.2, 1.5, 1.8]
```

#### 3.2.3 引擎状态 API (不变)

```yaml
GET /api/v1/engines/status
Response 200:
  engines:
    - name: front_hall_infer
      display_name: "前厅视觉"
      status: "running"
      fps: 12.3
      pid: 12345
      port: 9101
      uptime_seconds: 1320000
      last_error: null
      model: "YOLOv8n-FoodSafety-v2.1"

    - name: frame_grabber               # [v1.1新增]
      display_name: "取帧引擎"
      status: "running"
      mode: "http"                       # 当前生效模式
      fps: 6.0                           # HTTP抓拍约6fps
      camera_id: "cam_a1_main"
      total_frames: 152340
      errors: 3
      last_mode_switch: "rtsp→http"      # 上次切换原因
```

#### 3.2.4 平台状态 API (v1.1新增, 只读)

```yaml
# 注意: 这些API只读取Agent层的状态，不直接执行登录/心跳
# 实际的心跳/登录逻辑仍在 Agent (:9100) 的 hub_client.py 中

GET /api/v1/platform/status
Response 200:
  platform:
    hub_url: "http://43.139.143.12:8098"
    login_status: "connected"            # connected / disconnected / error
    token_expires_at: "2026-08-01T12:00:00+08:00"
  heartbeat:
    enabled: true
    interval_seconds: 30
    last_success_time: "2026-08-01T11:29:45+08:00"
    next_expected_time: "2026-08-01T11:30:15+08:00"
    success_count: 2847
    fail_count: 13
    consecutive_failures: 0
  queue:
    depth: 0                             # 待发送消息数
    flushed_total: 1523                  # 累计成功发送
    last_flush_time: "2026-08-01T11:29:50+08:00"

GET /api/v1/platform/heartbeat-detail
Response 200:
  current_run:
    started_at: "2026-08-01T11:29:45+08:00"
    status: "success"                    # success / pending / failed
    latency_ms: 23
  history:                               # 最近10次
    - time: "2026-08-01T11:29:45+08:00"
      status: "success"
      latency_ms: 23
    - time: "2026-08-01T11:29:15+08:00"
      status: "success"
      latency_ms: 25
    ...
```

---

## 4. 与现有代码集成方案

### 4.1 集成点：edge/agent/server.py

**当前状态**：
- `edge/agent/server.py` 是一个 FastAPI 应用，监听 :9100
- 已有路由：推理接口、健康检查、设备信息等
- 已有 `hub_client.py` 负责北向通信（心跳/上报/离线队列）

**v1.1 集成方式**：

```python
# edge/agent/server.py 末尾新增

from edge.edge_ui.api import register_ui_routes
from edge.edge_ui.main import create_app as create_ui_app
from fastapi.staticfiles import StaticFiles
from pathlib import Path
import uvicorn

# 方案A (推荐MVP): 独立进程 :9080
def start_ui_server():
    """在独立线程启动Edge UI服务器"""
    ui_app = create_ui_app()
    # 注册UI路由到独立FastAPI实例
    register_ui_routes(ui_app)
    # 挂载静态文件
    _UI_DIR = Path(__file__).parent.parent / "edge-ui"
    ui_app.mount("/", StaticFiles(directory=str(_UI_DIR), html=True), name="edge-ui")

    config = uvicorn.Config(
        app=ui_app,
        host="0.0.0.0",
        port=9080,
        log_level="info",
    )
    server = uvicorn.Server(config)
    server.run()

# 在 agent/server.py main() 中启动:
import threading
ui_thread = threading.Thread(target=start_ui_server, daemon=True)
ui_thread.start()
print("[Edge UI] 配置界面已启用 → http://0.0.0.0:9080")
```

**关键设计决策（v1.1更新）**：

| 决策 | 选择 | 理由 |
|------|------|------|
| 进程 | **独立线程/进程** | 与业务API 9100隔离，UI崩溃不影响推理 |
| 端口 | **独立端口 9080** | 与业务API隔离，可独立做速率限制+认证 |
| 路由前缀 | `/api/v1/` | RESTful最佳实践，版本化管理 |
| 北向通信 | **UI只读，Agent负责写** | hub_client.py 在 Agent 层，UI 通过本地接口读状态 |
| 取帧引擎 | **FrameGrabber在UI层** | UI层直接控制摄像头取帧，与推理解耦 |

### 4.2 启动方式

```bash
# 方案A: 独立启动 (开发调试用)
cd /opt/hotpot-smart-ops
python3 -m edge.edge-ui.main --port 9080

# 方案B: 随Agent一起启动 (生产环境)
python3 -m edge.agent.server --port 9100 --ui-enable --ui-port 9080
```

### 4.3 配置文件格式 (v1.1 更新: 双模式支持)

所有配置以 JSON 文件存储在 `/opt/hotpot-smart-ops/edge-ui/conf/` 目录：

```json
// conf/device.json — 设备基本信息 (不变)
{
  "device_id": "JT-ZJ-JJ-001",
  "device_name": "椒江店边缘盒子",
  "store_id": "store_jiaojiang",
  "store_name": "冯校长火锅·椒江店",
  "region": "台州",
  "firmware_version": "2.1.0",
  "initialized": true,
  "initialized_at": "2026-07-15T10:00:00+08:00",
  "timezone": "Asia/Shanghai",
  "ntp_server": "ntp.aliyun.com"
}
```

```json
// conf/cameras.json — 摄像头配置 (v1.1: 大幅扩展)
{
  "cameras": [
    {
      "id": "cam_a1_main",
      "name": "海康NVR主摄像头",
      "ip": "192.168.6.21",
      "vendor": "HIKVISION",

      "rtsp_url": "rtsp://admin:******@192.168.6.21:554/Streaming/Channels/101",

      "http_snapshot": {
        "base_url": "http://192.168.6.21",
        "path": "/ISAPI/Streaming/channels/101/picture",
        "auth_type": "digest",
        "avg_latency_ms": 170
      },

      "credentials": {
        "username": "admin",
        "password": "******"
      },

      "available_channels": [101, 102, 103, 201, 202],
      "active_channel": 101,

      "resolution": "704x576",
      "fps": 6,
      "codec": "jpeg",
      "grabber_mode": "auto",
      "purpose": "front_hall",
      "enabled": true,

      "status": "online",
      "last_frame_time": "2026-07-31T11:30:05+08:00",
      "created_at": "2026-07-31T10:00:00+08:00"
    }
  ]
}
```

```json
// conf/hub_connection.json — Hub连接配置 (不变)
{
  "hub_url": "http://43.139.143.12:8098",
  "api_key": "",
  "store_id": "store_jiaojiang",
  "heartbeat_interval_seconds": 30,
  "auto_reconnect": true,
  "offline_queue_enabled": true,
  "max_queue_size": 1000
}
```

```json
// conf/ui_settings.json — UI自身配置 (不变)
{
  "access_password": "$2b$12$hashed_password",
  "session_timeout_minutes": 30,
  "theme": "dark",
  "language": "zh-CN",
  "refresh_interval_seconds": 5,
  "allow_remote_access": false
}
```

---

## 5. FrameGrabber 架构 (v1.1 全新增)

### 5.1 三级自动切换机制

```
取帧请求
    │
    ▼
┌─────────────────┐
│  Mode Selector   │
│  (auto固定顺序)   │
└────────┬────────┘
         │
    ┌────▼────┬─────────┐
    │         │         │
    ▼         ▼         ▼
┌───────┐ ┌───────┐ ┌───────┐
│  RTSP  │ │ HTTP  │ │ Mock  │
│ OpenCV │ │Snapshot│ │ Cache │
│ Video  │ │requests│ │ File  │
│ Capture│ │ Digest │ │       │
└───┬───┘ └───┬───┘ └───┬───┘
    │         │         │
    │  ~25fps │  ~6fps  │  N/A
    │  需554  │  需80   │  零依赖
    │  端口   │  端口   │
    │         │         │
    └────┬────┴────┬────┘
         │ 降级    │ 降级
         ▼         ▼
    [RTSP失败] [HTTP失败]
    │         │
    ▼         ▼
  自动切换到下一级
```

### 5.2 模式选择策略

| 模式 | 条件 | 延迟 | 适用场景 |
|------|------|------|----------|
| `rtsp` | 554端口可达 + VideoCapture打开成功 | ~25fps | 理想情况，NVR正常工作 |
| `http` | 80端口可达 + Digest Auth成功 + JPEG返回 | ~6fps | 海康NVR (当前椒江店) |
| `mock` | 以上都失败 | N/A | 开发调试 / 断网演示 |

### 5.3 运行时状态

FrameGrabber 维护以下运行时状态（内存 only，不持久化）：

```json
{
  "current_mode": "http",
  "camera_id": "cam_a1_main",
  "total_frames": 152340,
  "errors": 3,
  "last_mode_switch": {
    "from": "rtsp",
    "to": "http",
    "reason": "RTSP connection reset by peer",
    "timestamp": "2026-07-31T14:20:00+08:00"
  },
  "buffer_depth": 2,
  "avg_latency_ms": 172
}
```

---

## 6. 北向通信边界 (v1.1 明确化)

### 6.1 职责划分

```
┌─────────────────────────────────────────────────────────┐
│                   Jetson Edge Gateway                    │
│                                                         │
│  ┌──────────────┐    ┌──────────────┐                   │
│  │  Edge UI     │    │  Edge Agent  │                   │
│  │  :9080       │◄──►│  :9100       │                   │
│  │              │    │              │                   │
│  │  职责:        │    │  职责:        │                   │
│  │  ·展示状态    │    │  ·执行心跳    │                   │
│  │  ·配置CRUD    │    │  ·AI推理     │                   │
│  │  ·手动操作    │    │  ·数据上报    │                   │
│  │  ·读取共享状态│    │  ·离线队列    │                   │
│  │              │    │  ·模型管理    │                   │
│  └──────┬───────┘    └──────┬───────┘                   │
│         │                   │                            │
│         │  (本地文件/内存)   │                            │
│         ▼                   ▼                            │
│  ┌──────────────────────────────────────┐                │
│  │  shared_state.json (或内存共享)      │                │
│  │  ·heartbeat_status                  │                │
│  │  ·login_token (脱敏)                │                │
│  │  ·queue_depth                       │                │
│  │  ·engine_statuses                   │                │
│  └──────────────────────────────────────┘                │
└─────────────────────────┬───────────────────────────────┘
                          │
                          ▼
              ┌──────────────────────────┐
              │   云端平台 :8098          │
              │  登录↔心跳↔数据上报       │
              └──────────────────────────┘
```

### 6.2 共享状态接口

Edge UI 通过以下方式获取 Agent 层的状态：

**方式A (推荐MVP): 读取共享文件**
```python
# Agent 写入 /tmp/hotpot-edge-state.json (每5秒)
{
  "heartbeat": { "last_success": "...", "consecutive_failures": 0 },
  "login": { "status": "connected", "token_expires": "..." },
  "queue": { "depth": 0, "flushed_total": 1523 }
}

# Edge UI 读取此文件返回给前端
GET /api/v1/platform/status → 读取并返回
```

**方式B (Phase 2): 内部HTTP调用**
```python
# Edge UI 调用 Agent 的内部API
requests.get("http://127.0.0.1:9100/api/internal/heartbeat-status")
```

---

## 7. 安全架构 (保持v1.0不变)

### 7.1 防御层次

```
┌─────────────────────────────────────────────────────┐
│  L1: 网络层                                         │
│  ├── 默认仅监听局域网地址 (192.168.x.x / 172.16.x.x)│
│  ├── allow_remote_access=false 时拒绝外网请求        │
│  └── 可选: 绑定特定网卡接口                           │
├─────────────────────────────────────────────────────┤
│  L2: 访问控制                                        │
│  ├── 首次访问 → 设置访问密码（6位数字PIN）            │
│  ├── Cookie-based Session（HttpOnly + Secure）       │
│  ├── 30分钟无操作自动登出                             │
│  └── 5次密码错误锁定5分钟                             │
├─────────────────────────────────────────────────────┤
│  L3: 操作安全                                        │
│  ├── 所有写操作需要确认弹窗                           │
│  ├── 危险操作（重启/恢复出厂/OTA）需二次密码确认      │
│  ├── CSRF Token 保护表单提交                          │
│  └── 敏感字段脱敏显示                                │
├─────────────────────────────────────────────────────┤
│  L4: 审计追踪                                        │
│  ├── 所有配置变更记录到 ui_audit.log                  │
│  ├── 记录: 时间/IP/用户/操作/前后值                   │
│  └── 日志保留90天                                    │
└─────────────────────────────────────────────────────┘
```

### 7.2 认证流程 (不变)

```
浏览器首次访问 http://IP:9080/
        │
        ▼
   检查 Cookie session
        │
   ┌────┴────┐
   │ 有session? │
   └────┬────┘
   Yes No
   │   │
   │   ▼
   │  检查是否已设置密码
   │      │
   │   ┌──┴──┐
   │   │有密码?│
   │   └──┬──┘
   │  Yes No
   │   │   │
   │   ▼   ▼
   │  显示  显示「设置初始密码」页
   │  登录页  （一次性，设置后跳转登录）
   │   │
   │   ▼
   │  输入6位PIN
   │   │
   │   ▼
   │  验证通过 → Set-Cookie: session_token
   │   │
   └───┴──► 进入首页
```

---

## 8. 部署架构 (保持v1.0不变)

### 8.1 MVP 部署方式（椒江店现状）

```
Jetson Orin NX (172.16.1.60)
│
├── edge/agent/server.py (:9100)  ← 已有，运行中
│   ├── 业务API (推理/上报/心跳)
│   └── hub_client.py (北向通信)
│
├── edge/edge-ui/main.py (:9080)  ← [v1.1新建] FastAPI版
│   ├── api/v1/* 路由 (35个端点)
│   ├── 静态文件 (HTML/CSS/JS)
│   └── FrameGrabber (南向取帧)
│
├── /opt/hotpot-smart-ops/
│   ├── edge-ui/conf/           ← 配置文件（JSON）
│   │   ├── device.json
│   │   ├── cameras.json
│   │   ├── hub_connection.json
│   │   └── ui_settings.json
│   ├── edge-ui/assets/         ← 前端资源
│   └── edge/agent/             ← 已有代码
│
└── systemd 服务: hotpot-edge.service (已有)
    └── 开机自启 + 保活
```

### 8.2 部署步骤

```bash
# 1. 将 edge-ui/ 目录上传到 Jetson
scp -r edge-ui/ root@172.16.1.60:/opt/hotpot-smart-ops/

# 2. 安装 FastAPI + uvicorn (如未安装)
ssh root@172.16.1.60 "pip3 install fastapi uvicorn pyyaml"

# 3. 测试启动 Edge UI
ssh root@172.16.1.60 "cd /opt/hotpot-smart-ops && python3 -m edge.edge-ui.main --port 9080"

# 4. 浏览器打开 http://172.16.1.60:9080/
# 5. 设置初始PIN → 进入控制面板
```

---

## 9. 性能指标 (保持v1.0不变)

| 指标 | 目标值 | 说明 |
|------|--------|------|
| 首页加载 | < 1.5s | 局域网环境，含API数据 |
| 页面切换 | < 300ms | 纯静态页面 |
| API响应(P99) | < 100ms | 本地接口，无网络开销 |
| 状态刷新 | 5s间隔 | WebSocket推送 or 轮询 |
| 内存占用(UI) | < 30MB | 静态文件服务 + API |
| CPU开销(UI) | < 1% | 仅当有活跃连接时 |
| 并发支持 | 5个标签页 | 单人使用场景足够 |

---

## 10. 开发计划 (v1.1 更新)

### Phase 1: MVP（本次实现，严格对齐本设计文档）

| 任务 | 优先级 | 预估工时 | 对应Step |
|------|--------|----------|----------|
| 项目脚手架 + Design Tokens | P0 | 0.5h | Step 2 |
| FastAPI应用骨架 + 路由注册 | P0 | 1h | Step 2 |
| API客户端封装 (api-client.js) | P0 | 0.5h | Step 4 |
| 首页仪表盘 (index.html) | P0 | 1.5h | Step 4 |
| 摄像头管理 (cameras.html) 含HTTP抓拍 | P0 | 2h | Step 4 |
| 配置文件JSON格式 + ConfigManager | P0 | 1h | Step 3 |
| FrameGrabber集成 | P0 | 1h | Step 2 |
| 诊断工具 (diagnostics.html) | P0 | 1h | Step 4 |
| 后端API路由 (api/*.py) 全量 | P0 | 3h | Step 2 |
| 安全认证L2 (PIN+Session) | P0 | 1.5h | Step 5 |
| server.py 集成 + 部署 | P0 | 0.5h | Step 6 |
| **合计** | | **~13.5h** | |

### Phase 2: 功能完善（展会后）

| 任务 | 优先级 | 预估工时 |
|------|--------|----------|
| IoT传感器管理 | P0 | 1.5h |
| 系统设置（4个子页面） | P0 | 2h |
| 模型管理 | P1 | 1h |
| OTA升级 | P1 | 1.5h |
| 日志查看器 | P1 | 1.5h |
| **合计** | | **~7.5h** |

---

## 11. 风险与缓解 (v1.1 更新)

| 风险 | 影响 | 概率 | 缓解措施 |
|------|------|:----:|----------|
| Jetson资源不足 | UI卡顿 | 低 | 目标<30MB内存，纯静态无构建 |
| RTSP预览延迟 | 用户体验差 | 中 | 用快照替代实时流，按需加载 |
| 浏览器兼容性 | 部分功能异常 | 低 | 目标Chrome/Safari，降级处理 |
| 配置文件损坏 | 无法启动 | 极低 | JSON Schema校验 + 自动备份 |
| 安全漏洞 | 设备被入侵 | 低 | 局域网限制 + 简单认证 + 审计日志 |
| **HTTP抓拍限流** | 无法持续取帧 | **中** | **海康设备连续认证失败会触发临时限流；实现指数退避重试** |
| **FastAPI依赖缺失** | Jetson上无法启动 | **低** | **部署脚本自动 pip3 install fastapi uvicorn** |
