# 火锅智能系统 — 部署

## 目录

| 目录 | 用途 | 入口 |
|------|------|------|
| `jetson/` | Jetson Orin 板端全量部署（YOLO+VLM GPU推理） | `./deploy.sh` |
| `cloud/` | 云端 Hub + Dashboard | `docker compose up` |
| `edge/` | 边缘端容器编排（前厅+Agent） | `docker compose up` |
| `bridge/` | VLM→Hub 图像桥接 | `./bridge.sh` |

## 板端部署（Jetson）

```bash
# 从 Mac 源码端 → Jetson 板端 /opt/hotpot-infer/
cd deploy/jetson
JETSON_HOST=192.168.2.240 ./deploy.sh
```

- 目标目录：`/opt/hotpot-infer/`（板端）
- 自动：编译 llama.cpp → 启动 llama-server → docker cp jetson_server.py → 启动推理服务
- 支持参数：`./deploy.sh 20`（指定 GPU 层数）

## 云端部署

```bash
cd deploy/cloud
docker compose up -d
```

## 桥接

```bash
deploy/bridge/bridge.sh /path/to/image.jpg store_yuhuan 备餐废弃区 http://127.0.0.1:8098
```
