# 火瞳边缘盒子 · 本地 Web UI 架构设计

> **文档版本**: v1.0
> **创建日期**: 2026-07-31
> **关联产品**: 火瞳_边缘盒子WebUI产品设计_v1.0.md
> **关联代码**: `edge/edge-ui/` (新建)

---

## 1. 技术选型

### 1.1 选型原则

| 原则 | 决策 | 理由 |
|------|------|------|
| 轻量级 | ✅ 纯静态HTML+JS，无构建步骤 | Jetson资源有限，避免Node.js打包链 |
| 零依赖 | ✅ 不引入Vue/React框架 | 减少下载体积、降低复杂度 |
| 复用现有 | ✅ 复用平台端Design Tokens | 视觉一致性 |
| 渐进增强 | ✅ 核心功能无需JS也能工作 | 兼容性保障 |

### 1.2 技术栈

```
┌─────────────────────────────────────────────────────┐
│                    前端技术栈                         │
│                                                     │
│  HTML5 + CSS3 + Vanilla JavaScript (ES6+)           │
│  ├── 无框架（原生DOM操作）                           │
│  ├── CSS变量系统（Design Tokens）                    │
│  ├── Fetch API（HTTP请求）                           │
│  ├── WebSocket（实时状态推送，可选）                  │
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
│  Python FastAPI（集成到 edge/agent/server.py）       │
│  ├── 复用现有 FastAPI 实例和中间件                   │
│  ├── 新增路由组: /ui/ 前缀                          │
│  ├── 静态文件服务: StaticFiles 挂载                  │
│  └── CORS: 仅允许局域网段                            │
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
| **A: 纯静态+FastAPI** ✅ | 最轻量、最简单、可维护 | 无SPA体验 | **选中** |
| B: Vue3+Vite构建 | 组件化、开发效率高 | 需要构建步骤、增加复杂度 | 备选 |
| C: Flask+Jinja2模板 | 服务端渲染、SEO友好 | 需要模板引擎、实时性差 | 排除 |
| D: Go+Embed | 单二进制部署 | 团队不熟悉Go | 排除 |

---

## 2. 目录结构

### 2.1 完整目录树

```
hotpot_smart_ops/
├── edge/
│   ├── agent/
│   │   ├── server.py              # [修改] 新增 /ui/ 路由挂载
│   │   ├── modules/
│   │   └── ...
│   │
│   └── edge-ui/                   # [新建] 边缘盒子Web UI
│       ├── index.html             # 首页仪表盘
│       ├── setup.html             # 初始化向导
│       ├── cameras.html           # 摄像头管理
│       ├── iot-sensors.html       # IoT传感器管理
│       ├── system/
│       │   ├── network.html       # 网络配置
│       │   ├── hub-settings.html  # Hub连接设置
│       │   ├── models.html        # 模型管理
│       │   └── ota.html           # OTA升级
│       ├── diagnostics.html       # 诊断工具
│       ├── logs.html              # 日志查看(P1)
│       │
│       ├── assets/
│       │   ├── edge-ui.css        # 主样式表
│       │   ├── edge-ui.js         # 主逻辑模块
│       │   ├── components.js      # UI组件库
│       │   ├── setup-wizard.js    # 初始化向导逻辑
│       │   ├── api-client.js      # API封装层
│       │   └── icons.svg          # SVG精灵图
│       │
│       └── api/                   # [新建] FastAPI路由
│           ├── __init__.py        # 路由注册
│           ├── system_api.py      # 系统/资源接口
│           ├── camera_api.py      # 摄像头CRUD
│           ├── iot_api.py         # IoT传感器接口
│           ├── engine_api.py      # 引擎状态接口
│           └── diagnostics_api.py  # 诊断接口
│
├── hotpot_platform/
│   └── dashboard/
│       └── assets/
│           └── theme.css          # [复用] Design Tokens
│
└── conf/                          # [复用] 配置文件目录
    ├── device.json                # 设备基本信息
    ├── cameras.json               # 摄像头配置
    ├── iot_sensors.json           # IoT传感器配置
    ├── hub_connection.json        # Hub连接配置
    └── ui_settings.json            # UI自身设置
```

### 2.2 文件职责说明

| 文件/目录 | 行数估计 | 职责 |
|-----------|----------|------|
| `index.html` | ~300 | 首页仪表盘，包含资源卡片、引擎状态、最近事件 |
| `setup.html` | ~250 | 4步初始化向导，含表单验证和API调用 |
| `cameras.html` | ~280 | 摄像头列表、添加/编辑弹窗、RTSP预览 |
| `iot-sensors.html` | ~260 | 传感器表格、阈值编辑、简易图表 |
| `system/*.html` | ~200 each | 各设置页面的表单UI |
| `diagnostics.html` | ~220 | 一键诊断、逐项检测展示 |
| `assets/edge-ui.css` | ~400 | 全局样式、组件样式、响应式 |
| `assets/edge-ui.js` | ~350 | 导航、状态轮询、通用工具函数 |
| `assets/components.js` | ~250 | 可复用UI组件（Modal/Toast/Table/Card） |
| `assets/api-client.js` | ~200 | API请求封装、错误处理、重试逻辑 |
| `api/*.py` | ~150 each | FastAPI路由处理器 |

**总代码量预估**: ~4,000 行（前端~2,800 + 后端~1,200）

---

## 3. API 设计

### 3.1 API 总览

所有API以 `/api/v1/` 为前缀，由 `edge/agent/server.py` 的 FastAPI 实例提供服务。

```
GET    /api/v1/system/info          设备基本信息
GET    /api/v1/system/resources     系统资源(CPU/内存/GPU/磁盘)
GET    /api/v1/system/uptime        运行时间
GET    /api/v1/system/version       版本信息
PUT    /api/v1/system/network       更新网络配置
POST   /api/v1/system/restart       重启网络服务

GET    /api/v1/cameras              摄像头列表
POST   /api/v1/cameras              添加摄像头
GET    /api/v1/cameras/{id}         摄像头详情
PUT    /api/v1/cameras/{id}         更新摄像头配置
DELETE /api/v1/cameras/{id}         删除摄像头
POST   /api/v1/cameras/{id}/reconnect 重连摄像头
GET    /api/v1/cameras/{id}/snapshot 摄像头快照(JPEG)

GET    /api/v1/iot/sensors          传感器列表
POST   /api/v1/iot/sensors          添加传感器
GET    /api/v1/iot/sensors/{id}     传感器详情(含当前读数)
PUT    /api/v1/iot/sensors/{id}     更新传感器配置(阈值等)
DELETE /api/v1/iot/sensors/{id}     删除传感器
GET    /api/v1/iot/sensors/{id}/history 传感器历史数据

GET    /api/v1/engines/status       五大引擎状态汇总
GET    /api/v1/engines/{name}/status 单个引擎详情
POST   /api/v1/engines/{name}/restart 重启单个引擎
GET    /api/v1/engines/{name}/logs  引擎日志(最后100行)

GET    /api/v1/diagnostics/run      执行完整诊断
GET    /api/v1/diagnostics/network  网络连通性测试
GET    /api/v1/diagnostics/cameras  摄像头连接测试
POST   /api/v1/setup/initialize     执行初始化(绑定门店+配置Hub)
GET    /api/v1/setup/status         初始化状态查询
POST   /api/v1/ota/check            检查新版本
POST   /api/v1/ota/upgrade          执行OTA升级
GET    /api/v1/ota/status           升级进度查询
GET    /api/v1/models               已安装模型列表
POST   /api/v1/models/download      从Hub下载模型
DELETE /api/v1/models/{name}        删除本地模型
POST   /api/v1/models/{name}/activate 激活指定模型

GET    /api/v1/logs                 系统日志(支持分页/过滤)
GET    /api/v1/logs/tail            实时日志流(SSE)
```

### 3.2 核心 API 详细设计

#### 3.2.1 系统资源 API

```yaml
GET /api/v1/system/resources

Response 200:
  cpu:
    percent: 42.5          # 使用率百分比
    cores: 6               # ARM核心数
    freq_mhz: 1400         # 当前频率
    temp_celsius: 52.3     # 温度(如可获取)
  memory:
    total_mb: 7849         # 总内存MB
    used_mb: 4552          # 已用MB
    percent: 58.0          # 使用率
  gpu:
    model: "Orin NX"       # GPU型号
    utilization_pct: 38    # GPU利用率
    memory_used_mb: 2100   # 显存已用
    memory_total_mb: 8192  # 显存总量
    temperature_celsius: 41 # GPU温度
  storage:
    total_gb: 64
    used_gb: 55.8
    percent: 87.2
  uptime_seconds: 1324500  # 运行秒数
  load_average: [1.2, 1.5, 1.8]  # 1/5/15分钟负载
```

#### 3.2.2 引擎状态 API

```yaml
GET /api/v1/engines/status

Response 200:
  engines:
    - name: front_hall_infer
      display_name: "前厅视觉"
      status: "running"       # running/stopped/error/idle
      fps: 12.3               # 当前推理帧率
      pid: 12345              # 进程ID
      port: 9101              # 服务端口
      uptime_seconds: 1320000
      last_error: null
      model: "YOLOv8n-FoodSafety-v2.1"

    - name: kitchen_vlm
      display_name: "后厨VLM"
      status: "running"
      fps: 8.1
      pid: 12346
      port: 9102
      uptime_seconds: 1319000
      last_error: null
      model: "Qwen-VL-Chat-v1.1"

    - name: receiving_infer
      display_name: "收货检测"
      status: "idle"           # 待机中(无视频输入时)
      fps: 0
      pid: 12347
      port: 9103
      uptime_seconds: 1320000
      last_error: null
      model: "YOLOv8n-Detect-v2.0"

    - name: iot_bridge
      display_name: "IoT桥接"
      status: "running"
      sensors_online: 5
      sensors_total: 6
      pid: 12348
      port: 9104

    - name: store_forward
      display_name: "数据上报"
      status: "running"
      hub_connected: true
      last_report: "2026-07-31T11:30:00+08:00"
      reports_today: 1523
      pid: 12349
```

#### 3.2.3 摄像头 API

```yaml
# 列表
GET /api/v1/cameras
Response 200:
  cameras:
    - id: "cam_kitchen_1"
      name: "后厨主摄像头"
      rtsp_url: "rtsp://192.168.2.100:554/stream1"
      resolution: "1920x1080"
      fps: 15
      codec: "h264"
      purpose: "kitchen_sop"     # kitchen_sop/kitchen_vlm/receiving/front_hall
      enabled: true
      status: "online"           # online/offline/error
      last_frame_time: "2026-07-31T11:30:05+08:00"
      created_at: "2026-07-15T10:00:00+08:00"

# 添加
POST /api/v1/cameras
Body:
  name: string (required)
  rtsp_url: string (required)
  resolution: string (required)  # 1920x1080/1280x720/640x480
  fps: integer (required)        # 5-30
  codec: string (required)       # h264/h265/mjpeg
  purpose: string (required)
  enabled: boolean (default: true)

Response 201:
  id: "cam_new_1"
  ... (同上，含生成字段)

# 快照
GET /api/v1/cameras/{id}/snapshot
Response 200:
  Content-Type: image/jpeg
  Body: <JPEG binary data>
Response 503:
  detail: "Camera offline or snapshot failed"
```

#### 3.2.4 诊断 API

```yaml
POST /api/v1/diagnostics/run
# 异步执行，返回诊断任务ID

Response 202:
  task_id: "diag-20260731-113000"
  status: "running"

# 轮询结果
GET /api/v1/diagnostics/tasks/{task_id}
Response 200:
  task_id: "diag-20260731-113000"
  status: "completed"
  started_at: "2026-07-31T11:30:00+08:00"
  completed_at: "2026-07-31T11:30:05+08:00"
  results:
    - category: "network"
      name: "Hub连通性"
      target: "43.139.143.12:8098"
      status: "pass"
      detail: "延迟 23ms"
      timestamp: "2026-07-31T11:30:01+08:00"

    - category: "camera"
      name: "cam_kitchen_1"
      target: "rtsp://192.168.2.100:554/stream1"
      status: "pass"
      detail: "15fps正常"
      timestamp: "2026-07-31T11:30:02+08:00"

    - category: "camera"
      name: "cam_front_1"
      target: "rtsp://192.168.2.102:554/stream1"
      status: "fail"
      detail: "连接超时 (最后在线: 2小时前)"
      timestamp: "2026-07-31T11:30:03+08:00"

    - category: "resource"
      name: "CPU使用率"
      target: null
      status: "warn"
      detail: "78% (偏高，建议检查进程)"
      timestamp: "2026-07-31T11:30:04+08:00"
```

---

## 4. 与现有代码集成方案

### 4.1 集成点：edge/agent/server.py

**当前状态**：
- `edge/agent/server.py` 是一个 FastAPI 应用，监听 :9100
- 已有路由：推理接口、健康检查、设备信息等

**集成方式**：

```python
# edge/agent/server.py 末尾新增

from edge.edge_ui.api import register_ui_routes
from fastapi.staticfiles import StaticFiles
from pathlib import Path

# 注册 Edge UI 的 API 路由
register_ui_routes(app)

# 挂载静态文件（HTML/CSS/JS）
_UI_DIR = Path(__file__).parent.parent / "edge-ui"
if _UI_DIR.exists():
    app.mount("/", StaticFiles(directory=str(_UI_DIR), html=True), name="edge-ui")
    print("[Edge UI] 本地配置界面已启用 → http://0.0.0.0:9080")
```

**关键设计决策**：

| 决策 | 选择 | 理由 |
|------|------|------|
| 端口 | **独立端口 9080** | 与业务API 9100隔离，降低安全风险 |
| 进程 | **同一进程** | 共享内存/状态，无需IPC；资源占用最小 |
| 路由前缀 | `/api/v1/` | 与现有API风格一致 |
| 静态挂载 | 根路径 `/` | 访问 `http://IP:9080` 直接进入首页 |

### 4.2 启动方式变更

```bash
# Before: 只启动业务API
python3 -m edge.agent.server --port 9100

# After: 同时启动业务API + Web UI
python3 -m edge.agent.server \
  --api-port 9100 \     # 业务API端口（不变）
  --ui-port 9080 \      # Web UI端口（新增）
  --ui-enable           # 启用Web UI开关
```

或者更简单——**在现有 uvicorn 上多监听一个端口**：

```python
# server.py 中使用 uvicorn.Config 多端口
import uvicorn

if __name__ == "__main__":
    config = uvicorn.Config(
        app="edge.agent.server:app",
        host="0.0.0.0",
        port=9100,          # 主端口：业务API
    )
    # Web UI 在同一进程额外监听 9080
    ui_config = uvicorn.Config(
        app="edge.agent.server:app",
        host="0.0.0.0",
        port=9080,          # UI端口：仅提供静态文件+/api/v1/*
    )
    server = uvicorn.Server(config)
    # ... (实际可用线程/协程同时启动两个端口)
```

**简化方案（推荐MVP）**：直接让现有 :9100 同时服务 UI 静态文件，通过路径区分：

```
http://IP:9100/              → index.html (首页仪表盘)
http://IP:9100/api/v1/*      → API接口（原有+新增）
http://IP:9100/cameras.html  → 摄像头管理页面
...
```

这样**不需要改端口**，只需在 server.py 末尾加几行挂载代码。

### 4.3 配置文件格式

所有配置以 JSON 文件存储在 `/opt/hotpot-smart-ops/conf/` 目录：

```json
// conf/device.json — 设备基本信息
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
// conf/cameras.json — 摄像头配置
{
  "cameras": [
    {
      "id": "cam_kitchen_1",
      "name": "后厨主摄像头",
      "rtsp_url": "rtsp://192.168.2.100:554/stream1",
      "resolution": "1920x1080",
      "fps": 15,
      "codec": "h264",
      "purpose": "kitchen_sop",
      "enabled": true,
      "created_at": "2026-07-15T10:00:00+08:00"
    }
  ]
}
```

```json
// conf/ui_settings.json — UI自身配置
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

## 5. 安全架构

### 5.1 防御层次

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

### 5.2 认证流程

```
浏览器首次访问 http://IP:9100/
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

## 6. 部署架构

### 6.1 MVP 部署方式（椒江店现状）

```
Jetson Orin NX (172.16.1.60)
│
├── edge/agent/server.py (:9100)  ← 已有，运行中
│   ├── 业务API (推理/上报/心跳)
│   └── [+新增] Edge UI API (:9100 同端口)
│       ├── GET / → index.html
│       ├── GET /cameras.html → cameras.html
│       └── GET /api/v1/* → 新增API路由
│
├── /opt/hotpot-smart-ops/
│   ├── conf/           ← 配置文件（JSON）
│   ├── edge-ui/        ← 新增：静态文件
│   │   ├── index.html
│   │   ├── setup.html
│   │   ├── cameras.html
│   │   ├── assets/
│   │   └── ...
│   └── edge/agent/     ← 已有代码
│
└── systemd 服务: hotpot-edge.service (已有)
    └── 开机自启 + 保活
```

### 6.2 部署步骤

```bash
# 1. 将 edge-ui/ 目录上传到 Jetson
scp -r edge-ui/ root@172.16.1.60:/opt/hotpot-smart-ops/

# 2. 在 server.py 末尾添加 UI 挂载（3行代码）
# 3. 重启服务
ssh root@172.16.1.60 "systemctl restart hotpot-edge"

# 4. 浏览器打开 http://172.16.1.60:9100/
# 5. 设置初始PIN → 进入控制面板
```

### 6.3 未来演进：独立端口

```
Phase 2 (展会后):
  :9100 → 纯业务API（供内部调用）
  :9080 → Edge UI（供人工访问）

  理由:
  - UI和API分离，可独立做速率限制
  - UI端口可加更严格的认证
  - API端口可保持轻量无认证（信任内网）
```

---

## 7. 性能指标

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

## 8. 监控与告警

### 8.1 内置监控点

Edge UI 自身暴露以下监控端点（供上级系统采集）：

```
GET /api/v1/ui/metrics
Response:
  ui_sessions_active: 2          # 当前在线会话数
  ui_requests_total: 1523         # 今日请求数
  ui_avg_response_ms: 12          # 平均响应时间
  ui_errors_5xx: 0               # 5xx错误数
  ui_page_views:                  # 页面访问统计
    index: 45
    cameras: 23
    diagnostics: 12
```

### 8.2 异常告警条件

| 条件 | 级别 | 动作 |
|------|------|------|
| 连续3次API 5xx错误 | warn | 记录日志 |
| UI进程CPU > 80% 持续5min | warn | 记录日志 |
| 配置文件校验失败 | error | 拒绝保存 + 提示用户 |
| 检测到未授权访问尝试 | critical | 记录IP + 临时封禁 |

---

## 9. 开发计划

### Phase 1: MVP（本次实现）

| 任务 | 优先级 | 预估工时 |
|------|--------|----------|
| 项目脚手架 + Design Tokens | P0 | 0.5h |
| API客户端封装 (api-client.js) | P0 | 0.5h |
| 首页仪表盘 (index.html) | P0 | 1.5h |
| 初始化向导 (setup.html) | P0 | 1h |
| 摄像头管理 (cameras.html) | P0 | 1.5h |
| 诊断工具 (diagnostics.html) | P0 | 1h |
| 后端API路由 (api/*.py) | P0 | 2h |
| server.py 集成 + 部署 | P0 | 0.5h |
| **合计** | | **~8.5h** |

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

## 10. 风险与缓解

| 风险 | 影响 | 概率 | 缓解措施 |
|------|------|:----:|----------|
| Jetson资源不足 | UI卡顿 | 低 | 目标<30MB内存，纯静态无构建 |
| RTSP预览延迟 | 用户体验差 | 中 | 用快照替代实时流，按需加载 |
| 浏览器兼容性 | 部分功能异常 | 低 | 目标Chrome/Safari，降级处理 |
| 配置文件损坏 | 无法启动 | 极低 | JSON Schema校验 + 自动备份 |
| 安全漏洞 | 设备被入侵 | 低 | 局域网限制 + 简单认证 + 审计日志 |
