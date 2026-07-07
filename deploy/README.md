# 火锅智能系统 — 部署

## 目录

| 目录 | 用途 | 入口 |
|------|------|------|
| `jetson/` | Jetson Orin 板端部署 | `deploy.sh`（日常）/ `build.sh`（首次） |
| `cloud/` | 云端 Hub + Dashboard | `docker compose up` |
| `edge/` | 边缘端容器编排（前厅+Agent） | `docker compose up` |
| `bridge/` | VLM→Hub 图像桥接 | `./bridge.sh` |

## 板端部署（Jetson）

**首次部署：**
```bash
cd deploy/jetson
JETSON_HOST=192.168.2.240 ./build.sh     # 编译 llama.cpp + 下载模型（只跑一次）
```

**日常增量部署（无编译）：**
```bash
cd deploy/jetson
JETSON_HOST=192.168.2.240 ./deploy.sh    # 同步代码 → 重启 → 验证
```

- 目标目录：`/opt/hotpot-infer/`（板端）
- llama-server 二进制：`/opt/hotpot-infer/bin/llama-server-cuda`（build.sh 产出）
- 大模型不受 deploy.sh 管控，板端本地缓存

## 云端部署

```bash
cd deploy/cloud
docker compose up -d
```

## 桥接

```bash
deploy/bridge/bridge.sh /path/to/image.jpg store_yuhuan 备餐废弃区 http://127.0.0.1:8098
```
