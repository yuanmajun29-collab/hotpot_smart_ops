# 火瞳Edge Gateway · 设计文档 vs 现有代码 差异分析报告

> **报告版本**: v1.0
> **生成日期**: 2026-08-01
> **分析范围**: WebUI架构设计v1.0 vs server.py(v1) + server_v2.py(v2) + config_manager.py + hub_client.py
> **分析维度**: API端点 / 数据模型 / 架构层次 / 功能覆盖度 / 关键不一致列表

---

## A. API端点差异

### A.1 设计文档定义的完整API清单（权威来源）

**来源**: `docs/火瞳_边缘盒子WebUI架构设计_v1.0.md` §3.1
**前缀规范**: 所有API以 `/api/v1/` 为前缀
**总数**: 40个端点

| 分类 | 方法 | 路径 | 功能 |
|------|------|------|------|
| **系统** | GET | `/api/v1/system/info` | 设备基本信息 |
| | GET | `/api/v1/system/resources` | CPU/内存/GPU/磁盘 |
| | GET | `/api/v1/system/uptime` | 运行时间 |
| | GET | `/api/v1/system/version` | 版本信息 |
| | PUT | `/api/v1/system/network` | 更新网络配置 |
| | POST | `/api/v1/system/restart` | 重启网络服务 |
| **摄像头** | GET | `/api/v1/cameras` | 摄像头列表 |
| | POST | `/api/v1/cameras` | 添加摄像头 |
| | GET | `/api/v1/cameras/{id}` | 摄像头详情 |
| | PUT | `/api/v1/cameras/{id}` | 更新摄像头 |
| | DELETE | `/api/v1/cameras/{id}` | 删除摄像头 |
| | POST | `/api/v1/cameras/{id}/reconnect` | 重连摄像头 |
| | GET | `/api/v1/cameras/{id}/snapshot` | 摄像头快照(JPEG) |
| **IoT传感器** | GET | `/api/v1/iot/sensors` | 传感器列表 |
| | POST | `/api/v1/iot/sensors` | 添加传感器 |
| | GET | `/api/v1/iot/sensors/{id}` | 传感器详情+读数 |
| | PUT | `/api/v1/iot/sensors/{id}` | 更新传感器配置 |
| | DELETE | `/api/v1/iot/sensors/{id}` | 删除传感器 |
| | GET | `/api/v1/iot/sensors/{id}/history` | 历史数据 |
| **引擎** | GET | `/api/v1/engines/status` | 五大引擎状态汇总 |
| | GET | `/api/v1/engines/{name}/status` | 单引擎详情 |
| | POST | `/api/v1/engines/{name}/restart` | 重启单引擎 |
| | GET | `/api/v1/engines/{name}/logs` | 引擎日志(100行) |
| **诊断** | POST | `/api/v1/diagnostics/run` | 执行完整诊断 |
| | GET | `/api/v1/diagnostics/network` | 网络连通性测试 |
| | GET | `/api/v1/diagnostics/cameras` | 摄像头连接测试 |
| **初始化** | POST | `/api/v1/setup/initialize` | 执行初始化 |
| | GET | `/api/v1/setup/status` | 初始化状态查询 |
| **OTA** | POST | `/api/v1/ota/check` | 检查新版本 |
| | POST | `/api/v1/ota/upgrade` | 执行升级 |
| | GET | `/api/v1/ota/status` | 升级进度 |
| **模型管理** | GET | `/api/v1/models` | 已安装模型列表 |
| | POST | `/api/v1/models/download` | 从Hub下载模型 |
| | DELETE | `/api/v1/models/{name}` | 删除本地模型 |
| | POST | `/api/v1/models/{name}/activate` | 激活指定模型 |
| **日志** | GET | `/api/v1/logs` | 系统日志(分页/过滤) |
| | GET | `/api/v1/logs/tail` | 实时日志流(SSE) |
| **UI监控** | GET | `/api/v1/ui/metrics` | UI自身监控指标 |

### A.2 server.py (v1) 实现的API

**前缀**: `/api/` （**不符合设计**）
**技术栈**: `http.server.HTTPServer` + `SimpleHTTPRequestHandler`
**总数**: 15个端点（10个GET + 5个POST）

#### GET端点

| 路径 | 对应设计文档？ | 备注 |
|------|--------------|------|
| `/api/device/status` | ⚠️ 部分对应 | 设计为 `/api/v1/system/info`，字段不完全一致 |
| `/api/system/resources` | ⚠️ 路径不同 | 设计为 `/api/v1/system/resources`，缺少GPU详细字段 |
| `/api/engines/status` | ⚠️ 路径不同 | 设计为 `/api/v1/engines/status`，返回结构简化 |
| `/api/cameras/list` | ❌ 完全不同 | 设计为 `/api/v1/cameras`（无/list后缀） |
| `/api/cameras/snapshot` | ⚠️ 路径不同 | 设计为 `/api/v1/cameras/{id}/snapshot`（缺少{id}参数化） |
| `/api/iot/sensors` | ⚠️ 路径不同 | 设计为 `/api/v1/iot/sensors` |
| `/api/network/config` | ❌ 设计无此API | 设计用PUT `/api/v1/system/network` |
| `/api/system/logs` | ⚠️ 路径不同 | 设计为 `/api/v1/logs` |
| `/api/system/ota/status` | ⚠️ 路径不同 | 设计为 `/api/v1/ota/status` |
| `/api/inference/results` | ❌ 设计无此API | **越界**：属于Agent推理层职责 |

#### POST端点

| 路径 | 对应设计文档？ | 备注 |
|------|--------------|------|
| `/api/device/init` | ⚠️ 部分对应 | 设计为 `/api/v1/setup/initialize` |
| `/api/network/config` | ❌ 路径+方法均不同 | 设计为PUT `/api/v1/system/network` |
| `/api/cameras/add` | ⚠️ 路径不同 | 设计为POST `/api/v1/cameras` |
| `/api/cameras/test` | ❌ 设计无此API | **额外功能**（但合理） |
| `/api/iot/threshold` | ❌ 设计无此API | 设计用PUT `/api/v1/iot/sensors/{id}` |
| `/api/system/ota/upgrade` | ⚠️ 路径不同 | 设计为POST `/api/v1/ota/upgrade` |
| `/api/system/reboot` | ❌ 设计无此API | **危险操作**，设计中无此接口 |
| `/api/system/logs/clear` | ❌ 设计无此API | **危险操作** |

### A.3 server_v2.py (v2) 实现的API

**前缀**: `/api/` （**仍不符合设计**）
**技术栈**: 同v1，仍使用`http.server.HTTPServer`
**总数**: 28个端点（16个GET + 12个POST）

#### 新增的GET端点（vs v1）

| 路径 | 对应设计文档？ | 备注 |
|------|--------------|------|
| `/api/config/all` | ❌ 设计无此API | **ConfigManager特有**，设计用多个JSON文件 |
| `/api/config/southbound` | ❌ 设计无此API | **越界**：暴露内部配置结构 |
| `/api/config/northbound` | ❌ 设计无此API | **越界**：同上 |
| `/api/platform/status` | ❌ 设计无此API | **严重越界**：属于Agent职责 |
| `/api/platform/heartbeat-detail` | ❌ 设计无此API | **严重越界**：属于Agent职责 |
| `/api/platform/queue-status` | ❌ 设计无此API | **严重越界**：属于HubClient职责 |

#### 新增的POST端点（vs v1）

| 路径 | 对应设计文档？ | 备注 |
|------|--------------|------|
| `/api/config/southbound` | ❌ 设计无此API | ConfigManager写操作 |
| `/api/config/northbound` | ❌ 设计无此API | ConfigManager写操作 |
| `/api/config/reload` | ❌ 设计无此API | 配置热重载 |
| `/api/cameras/test-connection` | ❌ 设计无此API | 改良版连接测试 |
| `/api/platform/login` | ❌ 设计无此API | **严重越界**：属于Agent职责 |
| `/api/platform/logout` | ❌ 设计无此API | **严重越界**：同上 |
| `/api/platform/send-heartbeat` | ❌ 设计无此API | **严重越界**：同上 |
| `/api/platform/test-connect` | ❌ 设计无此API | **严重越界**：同上 |
| `/api/platform/flush-queue` | ❌ 设计无此API | **严重越界**：同上 |

### A.4 API端点覆盖率统计

| 维度 | 设计要求 | v1实现 | v2实现 | v2符合率 |
|------|---------|--------|--------|----------|
| 总端点数 | 40 | 15 | 28 | 70% |
| 路径完全匹配 | 40 | **0** | **0** | **0%** |
| 功能对应（忽略路径差异） | 40 | ~10 | ~12 | ~30% |
| 额外端点（设计无） | 0 | 5 | **16** | **越界** |

---

## B. 数据模型差异

### B.1 配置文件格式与结构

#### 设计文档要求（§4.3）

**格式**: JSON
**存储位置**: `/opt/hotpot-smart-ops/conf/`
**文件组织**: 多文件分离

```
conf/
├── device.json          # 设备基本信息
├── cameras.json         # 摄像头配置
├── iot_sensors.json     # IoT传感器配置
├── hub_connection.json  # Hub连接配置
└── ui_settings.json     # UI自身设置
```

**device.json 示例结构**:
```json
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

**cameras.json 示例结构**:
```json
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

#### 代码实现（config_manager.py + edge_config.yml）

**格式**: YAML（可降级JSON）
**存储位置**: `edge/edge-ui/conf/edge_config.yml`
**文件组织**: 单一统一配置文件

**edge_config.yml 顶层结构**:
```yaml
device:                    # ✅ 对应 device.json
  device_id: "edge-jiaojiang-001"
  device_name: "椒江店-01号盒"
  ...

southbound:                # ❌ 设计无此层级（新增）
  grabber:                 # ❌ 设计无此层级
    mode: "auto"
    buffer_size: 2
    ...
  cameras:                 # ⚠️ 合并了 cameras.json
    - id: "cam_a1_main"
      name: "Camera 01 (海康NVR)"
      vendor: "HIKVISION"   # ❌ 设计无此字段
      ip: "192.168.6.21"    # ❌ 设计用 rtsp_url
      port: 554             # ❌ 设计无此字段
      zone: "..."           # ❌ 设计无此字段
      priority: "critical"  # ❌ 设计无此字段
      credentials:          # ❌ 设计无此嵌套（明文密码风险）
        username: "admin"
        password: "hy898989"
        auth_type: "digest"
      rtsp:                 # ❌ 设计用扁平 rtsp_url 字段
        enabled: false
        url: "..."
        channels: {...}
      http_snapshot:        # ❌ 设计无此结构
        enabled: true
        base_url: "..."
        paths: {...}
      _runtime: {...}       # ❌ 运行时状态混入配置文件

northbound:                # ❌ 设计无此层级（合并了 hub_connection.json）
  hub: {...}
  auth: {...}
  heartbeat: {...}
  reporting: {...}
  _runtime: {...}

services:                  # ❌ 设计无此层级（合并了 ui_settings.json）
  edge_ui: {...}
  edge_agent: {...}
  demo_web: {...}

logging: {...}             # ❌ 设计无此层级
```

### B.2 核心数据模型字段对比

#### 摄像头模型

| 字段 | 设计文档 | server.py (v1) | server_v2.py (v2) | 一致? |
|------|---------|----------------|-------------------|-------|
| id | ✅ `cam_kitchen_1` | ✅ `cam_a1_main` | ✅ `cam_a1_main` | ⚠️ 命名风格不同 |
| name | ✅ string | ✅ string | ✅ string | ✅ |
| rtsp_url | ✅ 完整URL | ❌ 无（拆分为ip+port） | ❌ 无（嵌套rtsp.url） | ❌ |
| resolution | ✅ `1920x1080` | ✅ string | ❌ 无 | ⚠️ v2缺失 |
| fps | ✅ integer | ✅ string ("~6") | ❌ 无 | ⚠️ v2缺失 |
| codec | ✅ `h264/h265/mjpeg` | ✅ string | ❌ 无 | ⚠️ v2缺失 |
| purpose | ✅ `kitchen_sop` 等 | ❌ 无（用scenes数组） | ❌ 无 | ❌ |
| enabled | ✅ boolean | ❌ 无 | ❌ 无 | ❌ |
| status | ✅ `online/offline/error` | ✅ string | ✅ _runtime.status | ⚠️ v2在_runtime中 |
| ip | ❌ 无 | ✅ string | ✅ string | ❌ 设计无 |
| vendor | ❌ 无 | ✅ string | ✅ string | ❌ 设计无 |
| credentials | ❌ 无 | ❌ 明文字典 | ✅ 嵌套对象 | ❌ 设计无（安全风险） |
| zone | ❌ 无 | ✅ string | ✅ string | ❌ 设计无 |
| _runtime | ❌ 无 | ❌ 无 | ✅ dict | ❌ 不应持久化 |

#### 系统资源响应模型

| 字段 | 设计文档 | server.py (v1) | server_v2.py (v2) | 一致? |
|------|---------|----------------|-------------------|-------|
| cpu.percent | ✅ float | ✅ cpu_percent | ✅ cpu_percent | ⚠️ 嵌套差异 |
| cpu.cores | ✅ integer | ❌ 无 | ❌ 无 | ❌ v1/v2均缺 |
| cpu.freq_mhz | ✅ integer | ❌ 无 | ❌ 无 | ❌ v1/v2均缺 |
| cpu.temp_celsius | ✅ float | ✅ cpu_temp_celsius | ❌ 无 | ⚠️ 仅v1有 |
| memory.total_mb | ✅ integer | ✅ memory_mb.total | ✅ memory_mb.total_mb | ⚠️ 命名差异 |
| memory.used_mb | ✅ integer | ✅ memory_mb.used | ✅ memory_mb.used_mb | ⚠️ 命名差异 |
| memory.percent | ✅ float | ❌ 无 | ❌ 无 | ❌ v1/v2均缺 |
| gpu.model | ✅ string | ❌ 无 | ❌ 无 | ❌ v1/v2均缺（Jetson必需！） |
| gpu.utilization_pct | ✅ integer | ✅ gpu_percent | ❌ 无 | ⚠️ 仅v1有 |
| gpu.memory_* | ✅ multiple | ✅ gpu_memory_mb | ❌ 无 | ⚠️ 仅v1有 |
| storage.total_gb | ✅ float | ✅ disk_gb.total | ✅ disk_gb.total_gb | ⚠️ 命名差异 |
| uptime_seconds | ✅ integer | ❌ 在device/status中 | ✅ 有 | ⚠️ 位置不同 |
| load_average | ✅ array[3] | ❌ 无 | ❌ 无 | ❌ v1/v2均缺 |

#### 引擎状态模型

| 字段 | 设计文档 | server.py (v1) | server_v2.py (v2) | 一致? |
|------|---------|----------------|-------------------|-------|
| name | ✅ display_name | ✅ name | ✅ name | ⚠️ 字段名不同 |
| status | ✅ running/stopped/error/idle | ✅ status | ✅ status | ✅ |
| fps | ✅ float | ✅ fps | ✅ fps | ✅ |
| pid | ✅ integer | ❌ 无 | ❌ 无 | ❌ v1/v2均缺 |
| port | ✅ integer | ❌ 无 | ❌ 无 | ❌ v1/v2均缺 |
| uptime_seconds | ✅ integer | ✅ uptime_sec | ❌ 无 | ⚠️ 仅v1有 |
| last_error | ✅ nullable | ❌ 无 | ❌ 无 | ❌ v1/v2均缺 |
| model | ✅ string | ✅ model | ❌ 无 | ⚠️ 仅v1有 |
| sensors_online | ✅ (IoT桥接) | ❌ 无 | ❌ 无 | ❌ |
| hub_connected | ✅ (数据上报) | ❌ 无 | ❌ 无 | ❌ |
| last_report | ✅ ISO8601 | ❌ 无 | ❌ 无 | ❌ |
| reports_today | ✅ integer | ❌ 无 | ❌ 无 | ❌ |

### B.3 两套旧配置文件并存问题

项目中存在**三套**不兼容的配置格式：

1. **ipc_config_jiaojiang.yml** (旧，FrameGrabber使用)
   - 顶层键: `store`, `cameras`, `grabber`, `inference`, `hub`, `scene_camera_map`
   - 结构扁平，面向FrameGrabber设计

2. **edge_config.yml** (新，ConfigManager使用)
   - 顶层键: `device`, `southbound`, `northbound`, `services`, `logging`
   - 结构分层，面向Edge Gateway设计

3. **设计文档期望的JSON文件** (未实现)
   - 多文件分离: `device.json`, `cameras.json`, `iot_sensors.json` 等

**问题**: FrameGrabber仍使用字典传参（与ConfigManager的YAML结构不兼容），导致配置链路断裂。

---

## C. 架构层次差异

### C.1 技术栈对比

| 维度 | 设计文档要求 | server.py (v1) | server_v2.py (v2) | 符合? |
|------|-------------|----------------|-------------------|-------|
| **Web框架** | FastAPI（集成到agent/server.py） | `http.server.HTTPServer` | `http.server.HTTPServer` | ❌ **严重不符** |
| **静态文件服务** | `StaticFiles` 挂载 | `SimpleHTTPRequestHandler` | `SimpleHTTPRequestHandler` | ❌ |
| **异步支持** | FastAPI原生async | ❌ 全同步阻塞 | ❌ 全同步阻塞 | ❌ |
| **中间件** | CORS、认证、日志 | ❌ 无 | ❌ 无 | ❌ |
| **API文档** | FastAPI自动OpenAPI/Swagger | ❌ 无 | ❌ 无 | ❌ |
| **数据验证** | Pydantic模型 | ❌ 手动解析 | ❌ 手动解析 | ❌ |
| **依赖注入** | FastAPI Depends | ❌ 全局变量 | ❌ 全局变量 | ❌ |

### C.2 进程与端口架构

#### 设计文档方案（§4.1-4.2, §6.1）

```
┌─────────────────────────────────────────────────────┐
│  edge/agent/server.py (FastAPI, 单进程)              │
│                                                     │
│  :9100 ── 业务API（推理/上报/心跳）                   │
│  :9080 ── Edge UI（MVP阶段复用:9100，Phase 2独立）    │
│                                                     │
│  路由挂载:                                          │
│  ├── app.mount("/", StaticFiles) → index.html       │
│  ├── register_ui_routes(app) → /api/v1/*            │
│  └── 原有路由 → /inference/*, /health, ...          │
└─────────────────────────────────────────────────────┘
```

**启动命令**:
```bash
python3 -m edge.agent.server --api-port 9100 --ui-port 9080 --ui-enable
```

#### 代码实现方案

```
┌─────────────────────────────────────────────────────┐
│  server.py / server_v2.py (独立进程)                 │
│                                                     │
│  :9080 ── 静态文件 + /api/* (全部混合)               │
│                                                     │
│  特点:                                             │
│  ├── 与 agent/server.py :9100 完全独立              │
│  ├── 无FastAPI，无中间件                            │
│  ├── 全局变量状态管理                               │
│  └── 无法共享agent内存状态                          │
└─────────────────────────────────────────────────────┘
```

**启动命令**:
```bash
python3 server.py [--port 9080] [--mode auto] [--config path]
```

### C.3 模块职责边界

#### 设计文档定义的职责边界

```
┌─────────────────────────────────────────────────────┐
│                   Edge UI 层                        │
│  职责: 本地配置界面、设备管理、摄像头CRUD、诊断工具    │
│  不负责: 推理、心跳、数据上报、平台认证               │
├─────────────────────────────────────────────────────┤
│                Agent 服务层                         │
│  职责: 推理调度、心跳保活、配置轮询、模块管理         │
│  文件: edge/agent/server.py                        │
├─────────────────────────────────────────────────────┤
│               HubClient 层                          │
│  职责: Edge→Event Hub通信、离线队列                  │
│  文件: common/hub_client.py                        │
└─────────────────────────────────────────────────────┘
```

#### server_v2.py 的实际职责（越界）

```
┌─────────────────────────────────────────────────────┐
│          server_v2.py (Edge Gateway v2)             │
│                                                     │
│  ✅ Edge UI职责:                                    │
│  ├── 配置展示/编辑                                  │
│  ├── 摄像头列表/抓拍                                 │
│  ├── 系统资源监控                                   │
│  └── 日志查看                                       │
│                                                     │
│  ❌ 越界到Agent职责:                                 │
│  ├── 平台登录/登出 (do_platform_login/logout)       │
│  ├── 心跳发送/循环 (do_heartbeat/start_heartbeat)   │
│  ├── 心跳详情展示 (/api/platform/heartbeat-detail)  │
│  └── 平台连接状态总览 (/api/platform/status)        │
│                                                     │
│  ❌ 越界到HubClient职责:                             │
│  ├── 离线队列刷新 (/api/platform/flush-queue)        │
│  └── 队列状态查询 (/api/platform/queue-status)       │
│                                                     │
│  ❌ 安全风险:                                        │
│  ├── JWT Token明文内存存储                           │
│  ├── 密码明文YAML存储                                │
│  └── 无认证机制（设计要求PIN+Session）               │
└─────────────────────────────────────────────────────┘
```

### C.4 认证方式冲突

| 组件 | 认证方式 | 说明 |
|------|---------|------|
| **设计文档要求** | Cookie-based Session + 6位PIN | L2访问控制层 |
| **hub_client.py** | `X-Api-Key` Header | Edge→Hub通信 |
| **server_v2.py 北向** | `Authorization: Bearer <JWT>` | 平台登录获取token |
| **server.py/v2.py UI** | ❌ **无任何认证** | 任何人可访问 |

**问题**: 存在三种互不兼容的认证机制，且UI层完全没有认证（设计要求最基础的PIN保护都没有实现）。

---

## D. 功能覆盖度

### D.1 功能矩阵（设计要求 vs 实现）

| 功能模块 | 设计优先级 | 设计要求 | v1状态 | v2状态 | 覆盖率 |
|---------|-----------|---------|--------|--------|--------|
| **首页仪表盘** | P0 | 资源卡片+引擎状态+最近事件 | ⚠️ Mock | ⚠️ Mock | 40% |
| **初始化向导** | P0 | 4步向导+表单验证 | ⚠️ 简化版 | ⚠️ 简化版 | 30% |
| **摄像头管理** | P0 | CRUD+RTSP预览+快照 | ⚠️ 仅列表+快照 | ⚠️ 列表+快照+添加 | 50% |
| **系统资源监控** | P0 | CPU/内存/GPU/磁盘实时 | ✅ 有（Mock） | ✅ 真实采集 | 70% |
| **诊断工具** | P0 | 一键诊断+逐项检测 | ❌ 无 | ❌ 无 | 0% |
| **后端API路由** | P0 | FastAPI路由组 | ❌ http.server | ❌ http.server | 0% |
| **server.py集成** | P0 | 3行挂载代码 | ❌ 独立进程 | ❌ 独立进程 | 0% |
| **IoT传感器管理** | P1 (Phase 2) | CRUD+阈值+图表 | ⚠️ 仅Mock列表 | ⚠️ 仅Mock列表 | 20% |
| **网络配置** | P1 (Phase 2) | DHCP/静态IP/DNS | ⚠️ 仅展示 | ⚠️ 仅展示 | 30% |
| **Hub设置** | P1 (Phase 2) | 连接参数+测试 | ❌ 无 | ✅ 有（越界实现） | N/A |
| **模型管理** | P1 | 列表/下载/激活/删除 | ❌ 无 | ❌ 无 | 0% |
| **OTA升级** | P1 | 检查/执行/进度 | ⚠️ 仅状态Mock | ⚠️ 仅状态Mock | 20% |
| **日志查看器** | P1 | 分页/过滤/SSE实时流 | ⚠️ Mock列表 | ⚠️ Mock列表 | 20% |
| **安全认证** | P0 | PIN+Session+审计 | ❌ **完全缺失** | ❌ **完全缺失** | **0%** |
| **Design Tokens** | P0 | CSS变量系统 | ❌ 无 | ⚠️ gateway.html有 | 30% |

### D.2 Phase 1 (MVP) 完成度评估

**设计文档Phase 1任务清单** (§9.1):

| 任务 | 预估工时 | 状态 | 备注 |
|------|---------|------|------|
| 项目脚手架 + Design Tokens | 0.5h | ⚠️ 部分 | gateway.html有CSS变量，但不规范 |
| API客户端封装 (api-client.js) | 0.5h | ❌ 无 | 缺少独立JS模块 |
| 首页仪表盘 (index.html) | 1.5h | ⚠️ 有gateway.html替代 | 单文件，非index.html |
| 初始化向导 (setup.html) | 1h | ⚠️ 有HTML但逻辑简单 | 缺少4步向导流程 |
| 摄像头管理 (cameras.html) | 1.5h | ❌ 无独立页面 | 集成在gateway.html |
| 诊断工具 (diagnostics.html) | 1h | ❌ 完全缺失 | 设计有完整交互规范 |
| 后端API路由 (api/*.py) | 2h | ❌ 完全偏离 | 用http.server代替FastAPI |
| server.py 集成 + 部署 | 0.5h | ❌ 未集成 | 独立进程运行 |

**MVP总体完成度**: **~25-30%** （核心架构选型错误导致大量返工风险）

### D.3 Phase 2 (展会后) 功能前瞻

| 任务 | 风险评估 | 说明 |
|------|---------|------|
| IoT传感器管理 | 中 | 数据结构已定义，需补CRUD API |
| 系统设置（4个子页面） | 高 | 需要真正的系统调用权限 |
| 模型管理 | 高 | 需要与Agent层协作 |
| OTA升级 | 极高 | 需要系统级权限+回滚机制 |
| 日志查看器 | 低 | 技术简单，SSE流需异步支持 |

---

## E. 关键不一致列表（最重要！）

### E.1 不一致项总览

| # | 类型 | 设计要求 | 代码实现 | 严重程度 | 修复方向 |
|---|------|---------|---------|----------|----------|
| E-001 | **技术栈** | FastAPI集成到agent/server.py | http.server.HTTPServer独立进程 | **P0** | 重写为FastAPI路由组 |
| E-002 | **API前缀** | `/api/v1/` | `/api/` | **P0** | 全局替换+路由注册调整 |
| E-003 | **配置格式** | JSON多文件 | YAML单文件 | **P1** | 迁移到JSON或修改设计文档 |
| E-004 | **职责越界** | Edge UI不含北向通信 | server_v2.py含登录/心跳/队列API | **P0** | 移除或代理到Agent |
| E-005 | **认证缺失** | PIN+Session+Cookie | 完全无认证 | **P0** | 实现L2访问控制层 |
| E-006 | **数据模型** | 摄像头用rtsp_url扁平字段 | 拆分为ip+port+rtsp嵌套 | **P1** | 统一字段映射 |
| E-007 | **安全隐患** | 敏感字段脱敏存储 | password明文YAML+内存 | **P0** | 加密存储+脱敏API |
| E-008 | **响应格式** | 统一返回结构（无code包裹） | `{code: 0, data: {...}}` 包裹 | **P2** | 移除code包裹或对齐设计 |
| E-009 | **配置分裂** | 统一配置源 | ipc_config.yml + edge_config.yml并存 | **P1** | 统一到ConfigManager |
| E-010 | **目录结构** | 多HTML文件分离 | 单一gateway.html (~50KB) | **P2** | 拆分为独立页面 |
| E-011 | **引擎API** | 支持{name}参数化路径 | 硬编码5个引擎 | **P1** | 动态路由+进程探测 |
| E-012 | **诊断功能** | 异步诊断任务+轮询 | 完全缺失 | **P1** | 实现diagnostics API |
| E-013 | **模型管理** | 完整CRUD+下载激活 | 完全缺失 | **P2** (Phase 2) | 后续迭代 |
| E-014 | **实时日志** | SSE推送 | 仅Mock列表 | **P2** (Phase 2) | 需要异步支持 |
| E-015 | **静态资源** | assets/目录规范化 | 根目录散落 | **P2** | 按设计重构目录 |

---

### E.2 P0级不一致详解（必须立即修复）

#### E-001: 技术栈错误 — 使用http.server而非FastAPI

**设计怎么说** (§1.2):
> Python FastAPI（集成到 edge/agent/server.py）
> - 复用现有 FastAPI 实例和中间件
> - 新增路由组: /ui/ 前缀
> - 静态文件服务: StaticFiles 挂载

**代码怎么做**:
```python
# server.py (line 18) / server_v2.py (line 24)
from http.server import HTTPServer, SimpleHTTPRequestHandler

class EdgeUIHandler(SimpleHTTPRequestHandler):  # ❌ 不是FastAPI
    def do_GET(self): ...  # ❌ 手动路由分发
    def do_POST(self): ...
```

**影响**:
- 无法利用FastAPI的异步能力、自动文档、Pydantic验证
- 无法与agent/server.py共享中间件（CORS、认证、日志）
- 无法实现设计要求的OpenAPI/Swagger自动文档
- 独立进程导致无法共享Agent内存状态（引擎状态、推理结果）

**修复方向**:
1. **短期（MVP）**: 将server_v2.py的路由逻辑提取为FastAPI Router，在agent/server.py中挂载
2. **代码示例**:
```python
# edge/edge-ui/api/__init__.py
from fastapi import APIRouter

router = APIRouter(prefix="/api/v1")

@router.get("/system/resources")
async def get_system_resources():
    # 迁移原有逻辑
    ...

# edge/agent/server.py (末尾添加)
from edge.edge_ui.api import router
app.include_router(router)

from fastapi.staticfiles import StaticFiles
app.mount("/", StaticFiles(directory="edge/edge-ui"), name="edge-ui")
```

**预估工作量**: 2-3天（含测试）

---

#### E-002: API前缀错误 — /api/ 而非 /api/v1/

**设计怎么说** (§3.1):
> 所有API以 `/api/v1/` 为前缀，由 `edge/agent/server.py` 的 FastAPI 实例提供服务。

**代码怎么做**:
```python
# server.py (line 121)
if path.startswith('/api/'):  # ❌ 应为 '/api/v1/'

# server_v2.py (line 435)
if path.startswith('/api/'):  # ❌ 同上
```

**影响**:
- 前端api-client.js无法按设计文档开发
- 未来版本化困难（已无法区分v1/v2 API）
- 与agent/server.py现有API风格不一致

**修复方向**:
1. 全局搜索替换 `/api/` → `/api/v1/`（注意排除静态资源路径）
2. 如果采用FastAPI重构(E-001)，则在Router层面统一prefix
3. 前端gateway.html中的fetch URL同步更新

**预估工作量**: 0.5天

---

#### E-004: 职责越界 — Edge UI包含北向通信功能

**设计怎么说** (§4.1, §6.1):
> Edge UI职责: 本地配置界面、设备管理、摄像头CRUD、诊断工具
> Agent服务职责: 推理调度、心跳保活、配置轮询、模块管理

**代码怎么做** (server_v2.py):
```python
# 第142-218行: 平台登录/登出
def do_platform_login(): ...    # ❌ 属于Agent职责
def do_platform_logout(): ...   # ❌ 属于Agent职责

# 第220-289行: 心跳发送
def do_heartbeat(): ...         # ❌ 属于Agent职责
def start_heartbeat_loop(): ... # ❌ 属于Agent职责

# 第583-618行: 平台状态API
elif path == '/api/platform/status': ...           # ❌ 越界
elif path == '/api/platform/heartbeat-detail': ... # ❌ 越界
elif path == '/api/platform/queue-status': ...     # ❌ 越界

# 第669-694行: 平台操作API
elif path == '/api/platform/login': ...            # ❌ 越界
elif path == '/api/platform/logout': ...           # ❌ 越界
elif path == '/api/platform/send-heartbeat': ...   # ❌ 越界
elif path == '/api/platform/test-connect': ...     # ❌ 越界
elif path == '/api/platform/flush-queue': ...      # ❌ 越界
```

**影响**:
- **架构腐化**: UI层承担业务逻辑，违反单一职责原则
- **安全风险**: UI层持有JWT Token，增加攻击面
- **维护困难**: 心跳逻辑分散在UI和Agent两处，状态同步复杂
- **扩展瓶颈**: 无法独立部署UI（强依赖Agent生命周期）

**修复方向**:

**方案A（推荐）**: 代理模式
- Edge UI保留只读状态API（从Agent查询）
- 写操作（登录/心跳/刷新队列）通过内部HTTP调用转发到Agent
- Agent暴露内部API（仅监听127.0.0.1:9100）

```python
# server_v2.py (改造后)
import httpx

@router.get("/api/v1/platform/status")  # ✅ 只读，允许
async def get_platform_status():
    async with httpx.AsyncClient() as client:
        resp = await client.get("http://127.0.0.1:9100/internal/platform/status")
        return resp.json()

@router.post("/api/v1/platform/login")  # ✅ 代理到Agent
async def login(body: LoginRequest):
    async with httpx.AsyncClient() as client:
        resp = await client.post("http://127.0.0.1:9100/internal/auth/login", json=body.dict())
        return resp.json()
```

**方案B（彻底）**: 移除所有北向API
- 从server_v2.py删除16个platform/*端点
- 心跳/登录逻辑完全回归agent/server.py
- UI前端通过Agent的公开API间接获取状态

**预估工作量**: 方案A: 1-2天 / 方案B: 3-4天

---

#### E-005: 认证机制完全缺失

**设计怎么说** (§5.1-5.2):
```
L2: 访问控制
  ├── 首次访问 → 设置访问密码（6位数字PIN）
  ├── Cookie-based Session（HttpOnly + Secure）
  ├── 30分钟无操作自动登出
  └── 5次密码错误锁定5分钟
```

**代码怎么做**:
```python
# server.py / server_v2.py: 完全无认证代码
class EdgeUIHandler(SimpleHTTPRequestHandler):
    def do_GET(self):
        # ❌ 无Session检查
        # ❌ 无PIN验证
        # ❌ 无Cookie处理
        if path.startswith('/api/'):
            return self._handle_api_get(path)  # 直接处理，无任何鉴权
```

**影响**:
- **安全漏洞**: 局域网内任何人可访问配置界面
- **敏感信息泄露**: 可直接读取 `/api/config/all` 获取明文密码
- **操作风险**: 可通过API重启系统、清除日志、执行OTA
- **合规问题**: 设计明确要求的安全措施完全未实现

**修复方向**:

**MVP阶段（最小实现）**:
```python
from fastapi import Cookie, HTTPException, Response
from itsdangerous import TimedJSONWebSignatureSerializer as Serializer

# 简单PIN认证中间件
SESSION_SECRET = "change-me-in-production"
SESSION_MAX_AGE = 1800  # 30分钟

def require_auth(session_token: str = Cookie(None)):
    if not session_token:
        raise HTTPException(status_code=401, detail="未登录")
    try:
        s = Serializer(SESSION_SECRET, expires_in=SESSION_MAX_AGE)
        s.loads(session_token)
    except:
        raise HTTPException(status_code=401, detail="会话已过期")

@router.post("/api/v1/auth/login")
async def login(pin: str, response: Response):
    stored_pin = load_stored_pin()  # 从ui_settings.json读取
    if pin == stored_pin:
        token = Serializer(SESSION_SECRET, expires_in=SESSION_MAX_AGE).dumps({"auth": True})
        response.set_cookie(key="session_token", value=token, httponly=True)
        return {"ok": True}
    raise HTTPException(status_code=403, detail="PIN错误")

# 保护所有写操作API
@router.post("/api/v1/cameras", dependencies=[Depends(require_auth)])
async def add_camera(camera: CameraCreate): ...
```

**预估工作量**: 1-2天

---

#### E-007: 敏感信息安全漏洞

**设计怎么说** (§5.1 L3):
> 敏感字段脱敏显示

**代码怎么做**:

**问题1: YAML明文存储**
```yaml
# edge_config.yml (line 43)
credentials:
  username: "admin"
  password: "hy898989"     # ❌ 明文密码！
```

**问题2: API返回明文（config_manager.py有部分脱敏，但不完整）**
```python
# server_v2.py (line 509-511) - 仅对password做简单掩码
creds = c.get("credentials", {})
if creds.get("password"):
    creds["password"] = "******"  # ⚠️ 但 /api/config/all 可能绕过
```

**问题3: 内存中JWT Token明文**
```python
# server_v2.py (line 45)
_platform_state = {
    "token": "",  # ❌ JWT Token明文存储
    ...
}
```

**影响**:
- 配置文件泄露导致IPC摄像头被恶意控制
- 平台账号密码泄露
- 不符合设计文档的安全基线要求

**修复方向**:
1. **加密存储**: 使用Fernet对称加密或系统keyring
```python
from cryptography.fernet import Fernet

ENCRYPTION_KEY = Fernet.generate_key()  # 存储在安全位置
fernet = Fernet(ENCRYPTION_KEY)

# 保存时加密
encrypted_pwd = fernet.encrypt(password.encode())

# 读取时解密
password = fernet.decrypt(encrypted_pwd).decode()
```

2. **API严格脱敏**: 所有API响应必须经过mask_secrets过滤
3. **运行时Token保护**: 内存中使用secure_string或及时清理

**预估工作量**: 1天

---

### E.3 P1级不一致详解（尽快修复）

#### E-003: 配置格式 — JSON vs YAML

**设计怎么说** (§4.3):
> 所有配置以 JSON 文件存储在 `/opt/hotpot-smart-ops/conf/` 目录

**代码怎么做**:
- ConfigManager默认使用YAML格式
- 单一edge_config.yml文件而非多JSON文件

**修复方向**:
- **选项A（推荐）**: 修改设计文档，接受YAML格式（YAML更易读，支持注释）
- **选项B**: 修改ConfigManager，改为JSON多文件存储
- **无论哪种**: 必须统一，不能两套并存

**预估工作量**: 1-2天（含迁移脚本）

---

#### E-006: 摄像头数据模型不统一

**设计怎么说** (§3.2.3):
```json
{
  "id": "cam_kitchen_1",
  "name": "后厨主摄像头",
  "rtsp_url": "rtsp://192.168.2.100:554/stream1",
  "resolution": "1920x1080",
  "fps": 15,
  "codec": "h264",
  "purpose": "kitchen_sop",
  "enabled": true
}
```

**代码怎么做** (edge_config.yml):
```yaml
- id: "cam_a1_main"
  name: "Camera 01 (海康NVR)"
  ip: "192.168.6.21"        # ❌ 拆分了
  port: 554                 # ❌ 拆分了
  rtsp:                     # ❌ 嵌套对象
    url: "rtsp://admin:pwd@..."
  credentials:              # ❌ 额外嵌套
    username: "admin"
    password: "hy898989"
```

**修复方向**:
1. 定义统一的Camera Pydantic模型
2. ConfigManager负责内部格式↔API格式的转换
3. 保持YAML的可读性（注释、嵌套），但API输出符合设计文档

```python
# edge/edge-ui/models.py
from pydantic import BaseModel

class CameraInput(BaseModel):  # 内部格式（YAML）
    id: str
    name: str
    ip: str
    port: int
    credentials: CredentialInfo
    rtsp: RtspConfig
    http_snapshot: HttpSnapshotConfig

class CameraOutput(BaseModel):  # API输出格式（对齐设计）
    id: str
    name: str
    rtsp_url: str              # 自动拼接
    resolution: str
    fps: int
    codec: str
    purpose: str
    enabled: bool
    status: str

def camera_to_api(cam: CameraInput) -> CameraOutput:
    """内部格式→API格式转换"""
    return CameraOutput(
        id=cam.id,
        name=cam.name,
        rtsp_url=f"rtsp://{cam.credentials.username}:***@{cam.ip}:{cam.port}{cam.rtsp.url}",
        resolution="1920x1080",  # 从IPC获取
        fps=15,
        codec="h264",
        purpose="kitchen_sop",  # 从zone映射
        enabled=True,
        status=cam._runtime.status,
    )
```

**预估工作量**: 1天

---

#### E-009: 配置文件分裂 — 两套并存

**现状**:
1. `edge/common/config/ipc_config_jiaojiang.yml` — FrameGrabber使用
2. `edge/edge-ui/conf/edge_config.yml` — ConfigManager使用

**问题**:
- FrameGrabber接收字典参数，不从ConfigManager读取
- 两份配置的字段名、结构完全不兼容
- 修改一处不会同步到另一处

**修复方向**:
1. 让FrameGrabber接受ConfigManager实例或标准字典
2. 废弃ipc_config_jiaojiang.yml
3. 统一从edge_config.yml读取

```python
# 改造后的 init_frame_grabber (server_v2.py)
def init_frame_grabber(mode="auto"):
    cameras = _config_manager.get_cameras()
    cam = cameras[0]

    # 统一转换为FrameGrabber期望的格式
    fg_config = {
        "ipc_ip": cam["ip"],
        "username": cam["credentials"]["username"],
        "password": cam["credentials"]["password"],
        "mode": mode,
        "rtsp_url": cam.get("rtsp", {}).get("url", ""),
        "http_snapshot_url": (
            cam.get("http_snapshot", {}).get("base_url", "") +
            cam.get("http_snapshot", {}).get("paths", {}).get("main", "")
        ),
        "auth_type": cam["credentials"].get("auth_type", "digest"),
    }
    _frame_grabber = FrameGrabber(fg_config)
```

**预估工作量**: 0.5天

---

#### E-011: 引擎API硬编码

**设计怎么说** (§3.2.2):
```
GET /api/v1/engines/{name}/status     # 动态路径参数
POST /api/v1/engines/{name}/restart   # 支持任意引擎
GET /api/v1/engines/{name}/logs       # 查询指定引擎日志
```

**代码怎么做**:
```python
# server.py (line 171-185) / server_v2.py (line 491-499)
elif path == '/api/engines/status':
    return self._send_json({
        "data": [
            {"id": "food_rec", "name": "菜品识别", ...},  # ❌ 硬编码
            {"id": "waste_det", "name": "损耗检测", ...},
            # ... 固定5个，无法扩展
        ]
    })
```

**影响**:
- 无法动态增删引擎
- 无法查询单个引擎详情/日志
- 与Agent的实际模块注册表脱节

**修复方向**:
```python
@router.get("/api/v1/engines/{engine_name}/status")
async def get_engine_status(engine_name: str):
    # 从Agent进程查询（HTTP/gRPC/共享内存）
    engine = await query_agent_engine(engine_name)
    if not engine:
        raise HTTPException(status_code=404, detail=f"引擎 {engine_name} 不存在")
    return engine

@router.get("/api/v1/engines/status")
async def get_all_engines_status():
    engines = await query_agent_all_engines()
    return {"engines": engines}
```

**预估工作量**: 1-2天（需要Agent侧配合）

---

#### E-012: 诊断功能完全缺失

**设计怎么说** (§3.2.4):
```yaml
POST /api/v1/diagnostics/run
Response 202:
  task_id: "diag-20260731-113000"
  status: "running"

GET /api/v1/diagnostics/tasks/{task_id}
Response 200:
  results:
    - category: "network"
      name: "Hub连通性"
      target: "43.139.143.12:8098"
      status: "pass"
      detail: "延迟 23ms"
```

**代码怎么做**: 完全没有实现

**修复方向**:
```python
import asyncio
from dataclasses import dataclass

@dataclass
class DiagnosticTask:
    task_id: str
    status: str  # running/completed/failed
    results: list
    started_at: str
    completed_at: str = None

_diagnostic_tasks: Dict[str, DiagnosticTask] = {}

@router.post("/api/v1/diagnostics/run")
async def run_diagnostics(response: Response):
    task_id = f"diag-{time.strftime('%Y%m%d-%H%M%S')}"
    task = DiagnosticTask(task_id=task_id, status="running", results=[], started_at=time.strftime('%Y-%m-%d %H:%M:%S'))
    _diagnostic_tasks[task_id] = task

    # 异步执行诊断
    asyncio.create_task(_execute_diagnostics(task))

    response.status_code = 202
    return {"task_id": task_id, "status": "running"}

async def _execute_diagnostics(task: DiagnosticTask):
    # 1. 网络连通性测试
    task.results.append(await test_hub_connectivity())
    # 2. 摄像头连接测试
    for cam in _config_manager.get_cameras():
        task.results.append(await test_camera_connection(cam))
    # 3. 系统资源检查
    task.results.append(check_system_resources())

    task.status = "completed"
    task.completed_at = time.strftime('%Y-%m-%d %H:%M:%S')

@router.get("/api/v1/diagnostics/tasks/{task_id}")
async def get_diagnostic_result(task_id: str):
    task = _diagnostic_tasks.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    return task
```

**预估工作量**: 1-2天

---

### E.4 P2级不一致（后续迭代优化）

#### E-008: 响应格式包裹

**设计**: 直接返回数据对象
**代码**: `{code: 0, data: {...}}` 或 `{code: -1, error: "..."}`
**建议**: 采用FastAPI后自然解决（直接return dict/model）

#### E-010: 前端单文件膨胀

**设计**: 多HTML文件分离（index.html, setup.html, cameras.html...）
**代码**: 单一gateway.html (~50KB)
**建议**: Phase 2拆分，MVP阶段可接受

#### E-013/E-014: 模型管理与实时日志

**优先级**: Phase 2（展会后）
**说明**: 当前不影响核心功能，可后续迭代

---

## F. 修复路线图建议

### F.1 第一阶段：紧急修复（1周内）

**目标**: 解决P0问题，使代码基本可用且安全

| 序号 | 任务 | 工作量 | 依赖 |
|------|------|--------|------|
| F-001 | E-002: API前缀修正 `/api/` → `/api/v1/` | 0.5d | 无 |
| F-002 | E-007: 敏感字段加密+API脱敏强化 | 1d | 无 |
| F-003 | E-005: 实现基础PIN认证（Cookie Session） | 1.5d | 无 |
| F-004 | E-004: 移除/代理北向通信API（8个端点） | 1d | 无 |

**小计**: 4天

### F.2 第二阶段：架构对齐（1-2周）

**目标**: 技术栈切换到FastAPI，对齐设计文档

| 序号 | 任务 | 工作量 | 依赖 |
|------|------|--------|------|
| F-005 | E-001: 重构为FastAPI Router | 2-3d | F-001 |
| F-006 | E-009: 统一配置源（废弃ipc_config.yml） | 0.5d | F-005 |
| F-007 | E-006: 摄像头数据模型标准化+转换层 | 1d | F-005 |
| F-008 | E-003: 确定配置格式(JSON/YAML)并文档化 | 0.5d | F-005 |
| F-009 | agent/server.py集成（挂载Router+StaticFiles） | 0.5d | F-005 |

**小计**: 4.5-5.5天

### F.3 第三阶段：功能补全（2-3周）

**目标**: 达到设计文档Phase 1的完整功能

| 序号 | 任务 | 工作量 | 依赖 |
|------|------|--------|------|
| F-010 | E-011: 引擎API动态化（{name}参数） | 1-2d | F-005 |
| F-011 | E-012: 诊断功能完整实现 | 1-2d | F-005 |
| F-012 | 前端页面拆分（index/setup/cameras/diagnostics） | 2-3d | F-001 |
| F-013 | Design Tokens规范化+组件库 | 1d | F-012 |
| F-014 | api-client.js封装+错误处理 | 0.5d | F-001 |
| F-015 | 集成测试+部署验证 | 1d | 全部 |

**小计**: 6.5-9.5天

### F.4 第四阶段：Phase 2功能（展会后）

- OTA升级
- 模型管理
- IoT传感器完整CRUD
- SSE实时日志流
- 独立端口部署(:9080)

---

## G. 总结与风险评估

### G.1 核心发现

1. **架构选型根本性偏离**: 技术栈错误(http.server vs FastAPI)是所有问题的根源
2. **职责边界模糊**: server_v2.py越界承担Agent/HubClient职责，导致架构腐化
3. **安全基线未达标**: 认证、加密、脱敏三项安全要求完全未实现
4. **配置体系混乱**: 三套不兼容的配置格式并存，数据模型不统一
5. **API规范未遵循**: 前缀、路径、响应格式均与设计文档不符

### G.2 风险矩阵

| 风险 | 概率 | 影响 | 缓解措施 |
|------|:----:|:----:|---------|
| 安全漏洞被利用 | 高 | 严重 | 立即实施F-001~F-004 |
| 技术债累积 | 极高 | 高 | 按路线图严格执行 |
| MVP交付延期 | 中 | 中 | 分阶段交付，先P0再P1/P2 |
| 团队认知不一致 | 高 | 中 | 本报告作为统一事实来源 |

### G.3 最终建议

**必须立即行动**:
1. 停止在server_v2.py基础上继续堆砌功能
2. 按F-001~F-004顺序紧急修复P0安全问题
3. 尽快启动F-005 FastAPI重构（否则技术债将持续恶化）

**设计文档更新建议**:
考虑到YAML在实际场景的优势（可读性、注释），建议**反向更新设计文档§4.3**，接受YAML作为配置格式，但必须：
- 明确单一配置文件策略（edge_config.yml）
- 规定严格的字段命名规范
- 强制敏感字段加密存储
- 提供完整的JSON Schema用于校验

---

> **报告结束**
>
> 下一步行动: 召开技术评审会议，确认修复路线图优先级，分配F-001~F-004任务。
