# 火锅智能系统 — 部署

## 目录

| 目录 | 用途 | 入口 |
|------|------|------|
| `jetson/` | Jetson Orin 板端部署 | `deploy.sh`（日常）/ `build.sh`（首次） |
| `cloud/` | 云端 Hub + Dashboard | `docker compose up` |
| `edge/` | 边缘端容器编排（前厅+Agent） | `docker compose up` |
| `bridge/` | VLM→Hub 图像桥接 | `./bridge.sh` |

## 板端部署（Jetson）

### 首次部署
```bash
cd deploy/jetson
JETSON_HOST=192.168.2.240 ./build.sh     # 编译 llama.cpp + 下载模型
```
产出：`/opt/hotpot-infer/bin/llama-server-cuda` + `/opt/hotpot-infer/models/`

### 日常增量部署（无编译，模型缺失自动下载）
```bash
cd deploy/jetson
JETSON_HOST=192.168.2.240 ./deploy.sh    # 检查模型 → 同步代码 → 重启 → 验证
```
- 自动检测模型是否存在，缺失则从 HuggingFace 下载
- 只同步变更的代码（pipeline/detector/jetson_server）
- 部署完自动跑 health + infer 验证

### 流程
```
deploy.sh:
  [0/4] 检查前置 (llama-server 二进制 + 模型文件)
  [1/4] 停止旧服务
  [2/4] 同步代码 (tar 管道直传)
  [3/4] 启动 llama-server + 重启容器
  [4/4] 验证 (health + infer)
```

## 云端部署
```bash
cd deploy/cloud && docker compose up -d
```

## 桥接
```bash
deploy/bridge/bridge.sh /path/to/image.jpg store_yuhuan 备餐废弃区 http://127.0.0.1:8098
```
