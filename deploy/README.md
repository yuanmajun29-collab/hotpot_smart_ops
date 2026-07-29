# 火瞳（HotpotEye）— 部署文档

> **版本**: v5.3i | **更新**: 2026-07-29 | **详细架构**: `docs/01-核心权威/火瞳_详细架构设计_v1.0.md`

## 四层架构总览

```
┌─────────────────────────────────────────────────────────────┐
│  L4 应用层 (Application)                                     │
│  Web Dashboard / PDA App / 数字座舱 / AI 助理                │
└──────────────────────────┬──────────────────────────────────┘
                           │ HTTPS / WebSocket
┌──────────────────────────▼──────────────────────────────────┐
│  L3 平台层 (Platform) — 云端/总部服务器                       │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────────┐    │
│  │Event Hub │ │Data Engine│ │Alert GW  │ │Order Advisor │    │
│  │ :8098    │ │(预测/订货)│ │ :8099    │ │(智能采购)    │    │
│  └──────────┘ └──────────┘ └──────────┘ └──────────────┘    │
│  PostgreSQL · Redis · RabbitMQ                               │
└──────────────────────────┬──────────────────────────────────┘
                           │ mTLS + MQTT/HTTP
┌──────────────────────────▼──────────────────────────────────┐
│  L2 边缘层 (Edge) — 门店 Jetson / 工业PC                     │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────────┐    │
│  │Vision    │ │Pipeline  │ │IoT Bridge│ │Hub Client    │    │
│  │Worker    │ │Manager   │ │(MQTT)    │ │(上报+指令)   │    │
│  │(YOLO推理)│ │(编排)    │ │          │ │              │    │
│  └──────────┘ └──────────┘ └──────────┘ └──────────────┘    │
└──────────────────────────┬──────────────────────────────────┘
                           │ USB/RTSP
┌──────────────────────────▼──────────────────────────────────┐
│  L1 设备层 (Device) — IPC摄像头 / RFID读写器 / 电子秤        │
│  海康/大华IPC · RFID UHF · 智能称重                          │
└─────────────────────────────────────────────────────────────┘
```

## 部署模式

| 模式 | 场景 | 说明 |
|------|------|------|
| **L0 单机** | 开发/演示 | Jetson 一体运行 Edge+Platform |
| **L1 单店** | 门店部署 | Jetson(Edge) + 云服务器(Platform) |
| **L2 多店** | 连锁运营**★当前** | 多店Edge + 总部Platform |
| **L3 SaaS** | 未来 | 多租户隔离 + 弹性扩展 |

## 目录结构

```
deploy/
├── edge/              # L2 边缘层部署 (Dockerfile + docker-compose + systemd)
│   ├── Dockerfile
│   ├── docker-compose.yml    # 4容器: vision-worker/iot-bridge/pipeline-manager/hub-client
│   ├── entrypoint.sh
│   └── systemd/              # hotpot-pipeline.service + ipc-grabber.service
├── cloud/             # L3 平台层部署
│   └── docker-compose.yml    # 7容器: eventhub-api/postgres/redis/rabbitmq/alert-gateway/data-engine/scheduler/web
├── jetson/            # Jetson Orin 专用优化
│   ├── Dockerfile             # CUDA + TensorRT 基础镜像
│   ├── docker-compose.yml     # Jetson 端完整编排
│   ├── build.sh               # 镜像构建
│   ├── deploy.sh              # 一键部署到设备
│   ├── download_models.sh     # YOLO + VLM 模型下载
│   ├── entrypoint.sh
│   ├── .dockerignore
│   └── models/.gitkeep
├── bridge/
│   └── bridge.sh              # VLM→Hub 数据桥接脚本
├── deploy-hotpot.sh           # Mac→Jetson 一键部署主入口
├── watchdog.sh                # 服务保活看门狗
├── README.md                  # 本文件
└── VERSION                    # 版本号
```

## 快速开始

### 单店部署 (L1)

```bash
# 1. 边缘端 (Jetson)
cd deploy/jetson
bash build.sh              # 构建镜像
bash deploy.sh             # 部署到设备

# 2. 平台端 (云服务器)
cd deploy/cloud
docker compose up -d       # 启动全部7个容器

# 3. 验证
curl http://<JETSON_IP>:9100/health   # Edge
curl http<CLOUD_IP>:8098/health       # Platform
```

### 开发模式 (L0 — Jetson 一体)

```bash
# 从 Mac 源码端一键部署到 Jetson（一体化运行）
cd ~/company/products/to-b/hotpot_smart_ops
bash deploy/deploy-hotpot.sh

# 仅监控服务状态
bash deploy/deploy-hotpot.sh monitor
```

### 手动部署步骤 (L0 详细)

#### 0\. 前置条件
- Jetson 可 SSH: `ssh root@192.168.2.240`
- 模型文件就位: `models/qwen2-vl-2b/` (GGUF + mmproj)
- YOLO 模型: `yolov8n.pt`

#### 1\. 推送源码
```bash
rsync -avz --exclude '.git' --exclude '__pycache__' \
  ~/company/products/to-b/hotpot_smart_ops/ \
  root@192.168.2.240:/opt/hotpot-infer/
```

#### 2\. 安装依赖
```bash
ssh root@192.168.2.240 "
pip install -i https://pypi.tuna.tsinghua.edu.cn/simple \
  fastapi uvicorn httpx pyyaml opencv-python-headless \
  python-multipart backports.zoneinfo \
  'ultralytics>=8.0,<8.3' 'torchvision>=0.15,<0.16'
"
```

#### 3\. 启动服务
```bash
# Platform Hub
ssh root@192.168.2.240 "cd /opt/hotpot-infer && PYTHONPATH=. \
  python3 -m uvicorn hotpot_platform.cloud.event_hub.app:app \
  --host 0.0.0.0 --port 8098 &"

# Edge Agent
ssh root@192.168.2.240 "cd /opt/hotpot-infer && \
  HOTPOT_DEV_MODE=1 HOTPOT_HUB_URL=http://localhost:8098 PYTHONPATH=. \
  python3 -m uvicorn edge.agent.server:app \
  --host 0.0.0.0 --port 9100 &"
```

#### 4\. 激活模块
```bash
curl -X PUT http://192.168.2.240:8098/v1/devices/jetson-yuhuan-01/config \
  -H 'Content-Type: application/json' \
  -d '{"modules":{"kitchen":{"enabled":true}}}'
```

## 验证

```bash
# 健康检查
curl http://192.168.2.240:8098/health  # Platform Hub
curl http://192.168.2.240:9100/health  # Edge Agent
curl http://192.168.2.240:8084/health  # VLM Review (可选)

# YOLO 推理测试
curl "http://192.168.2.240:9100/infer/kitchen/yolo?image_path=/tmp/test.jpg&store_id=store_yuhuan"
```

## 环境变量

| 变量 | 说明 | 默认值 | 必填 |
|------|------|--------|:----:|
| `JETSON_HOST` | Jetson IP | `192.168.2.240` | ✅ |
| `JETSON_USER` | SSH 用户 | `root` | ✅ |
| `JETSON_DIR` | 远程目录 | `/opt/hotpot-infer` | — |
| `STORE_ID` | 门店ID | `store_yuhuan` | ✅ |
| `DEVICE_ID` | 设备ID | `jetson-yuhuan-01` | ✅ |
| `HOTPOT_HUB_URL` | Hub 地址 | `http://localhost:8098` | — |
| `HOTPOT_DEV_MODE` | 开发模式 | `1` | — |

详见 `.env.example` 和 `docs/01-核心权威/火瞳_详细架构设计_v1.0.md` §6。

## 坑点记录

| 问题 | 原因 | 解决 |
|------|------|------|
| BeiBei 频繁重启 | netstat 检测 LISTEN 误判 | watchdog.sh 修复 |
| zoneinfo 缺失 | Python 3.8 无此模块 | pip install backports.zoneinfo |
| torchvision 不兼容 | 0.19 需新 torch | 降级到 0.15 |
| Jetson 外网不通 | 网络限制 | Mac SSH 代理隧道 |
| nvcc 缺失 | CUDA 工具链未安装 | apt install cuda-nvcc-11-8 |
| NGC 镜像拉不到 | 网络限制 | 放弃 Docker，直接编译 |
| Docker 内存不足 OOM | Jetson 8GB RAM 限制 | 减少容器数 / swap 扩展 |
