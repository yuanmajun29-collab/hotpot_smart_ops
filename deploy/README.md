# 火锅连锁餐饮 — 部署文档

## 架构

```
┌─────────────────────────────────────────┐
│  Jetson (192.168.2.240)                 │
│  /opt/hotpot-infer/                     │
│                                         │
│  ┌──────────┐  ┌──────────┐  ┌───────┐ │
│  │ Hub :8098│←→│Edge :9100│  │ VLM   │ │
│  │(配置管理) │  │(YOLO推理)│  │ :8084 │ │
│  └──────────┘  └──────────┘  └───────┘ │
│       ↑              ↓                  │
│       └──── SQLite ──┘                  │
└─────────────────────────────────────────┘
         ↑ rsync from Mac 源码端
```

## 一键部署

```bash
# 从 Mac 源码端一键部署到 Jetson
cd ~/company/products/to-b/hotpot_smart_ops
bash deploy/deploy-hotpot.sh

# 仅监控
bash deploy/deploy-hotpot.sh monitor
```

## 手动部署步骤

### 0\. 前置条件
- Jetson 可 SSH: `ssh root@192.168.2.240`
- 模型文件就位: `models/qwen2-vl-2b/` (GGUF + mmproj)
- YOLO 模型: `yolov8n.pt`

### 1\. 推送源码
```bash
rsync -avz --exclude '.git' --exclude '__pycache__' \
  ~/company/products/to-b/hotpot_smart_ops/ \
  root@192.168.2.240:/opt/hotpot-infer/
```

### 2\. 安装依赖
```bash
ssh root@192.168.2.240 "
pip install -i https://pypi.tuna.tsinghua.edu.cn/simple \
  fastapi uvicorn httpx pyyaml opencv-python-headless \
  python-multipart backports.zoneinfo \
  'ultralytics>=8.0,<8.3' 'torchvision>=0.15,<0.16'
"
```

### 3\. 启动服务
```bash
# Hub
ssh root@192.168.2.240 "cd /opt/hotpot-infer && PYTHONPATH=. \
  python3 -m uvicorn hotpot_platform.cloud.event_hub.app:app \
  --host 0.0.0.0 --port 8098 &"

# Edge Agent  
ssh root@192.168.2.240 "cd /opt/hotpot-infer && \
  HOTPOT_DEV_MODE=1 HOTPOT_HUB_URL=http://localhost:8098 PYTHONPATH=. \
  python3 -m uvicorn edge.agent.server:app \
  --host 0.0.0.0 --port 9100 &"
```

### 4\. 激活 kitchen 模块
```bash
curl -X PUT http://192.168.2.240:8098/v1/devices/jetson-yuhuan-01/config \
  -H 'Content-Type: application/json' \
  -d '{"modules":{"kitchen":{"enabled":true,...}}}'
```

## 验证

```bash
# 健康检查
curl http://192.168.2.240:8098/health  # Hub
curl http://192.168.2.240:9100/health  # Edge
curl http://192.168.2.240:8084/health  # VLM (待部署)

# YOLO 推理测试
curl "http://192.168.2.240:9100/infer/kitchen/yolo?image_path=/tmp/test.jpg&store_id=store_yuhuan"
```

## 坑点记录

| 问题 | 原因 | 解决 |
|------|------|------|
| BeiBei 频繁重启 | netstat 检测 LISTEN 误判 | digital-life-health.sh 修复 |
| zoneinfo 缺失 | Python 3.8 无此模块 | pip install backports.zoneinfo |
| torchvision 不兼容 | 0.19 需新 torch | 降级到 0.15 |
| Jetson 外网不通 | 网络限制 | Mac SSH 代理隧道 |
| nvcc 缺失 | CUDA 工具链未安装 | apt 安装 cuda-nvcc-11-8 |
| NGC 镜像拉不到 | 网络限制 | 放弃 Docker，直接编译 |
