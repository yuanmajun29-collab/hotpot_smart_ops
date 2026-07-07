# 火锅智能系统 — 部署

**一切从源码端出发，板端不做任何编译。**

## 目录

| 目录 | 用途 | 入口 |
|------|------|------|
| `jetson/` | Jetson Orin 板端部署 | `build.sh`（首次）/ `deploy.sh`（日常） |
| `cloud/` | 云端 Hub + Dashboard | `docker compose up` |
| `edge/` | 边缘端容器编排（前厅+Agent） | `docker compose up` |
| `bridge/` | VLM→Hub 图像桥接 | `./bridge.sh` |

## 板端部署（Jetson）

### 首次构建（源码端 Mac）
```bash
cd deploy/jetson
JETSON_HOST=192.168.2.240 ./build.sh
```
→ 源码端编译 llama.cpp → 打入 Docker 镜像 → `docker save` → `ssh docker load` 推板端
→ 板端**不做任何编译**

### 日常增量部署
```bash
cd deploy/jetson
JETSON_HOST=192.168.2.240 ./deploy.sh
```
→ 检查镜像+模型 → 同步代码(tar直传) → 重启容器 → 验证

### 板端目录
```
/opt/hotpot-infer/
├── models/          ← 大模型权重（镜像外，卷挂载）
└── data/            ← 推理数据
```

## 云端部署
```bash
cd deploy/cloud && docker compose up -d
```
