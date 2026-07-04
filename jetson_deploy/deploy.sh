#!/bin/bash
# deploy.sh — 一键部署推理流水线到 Jetson
# 用法: bash deploy.sh [jetson_ip] [--rebuild]

set -euo pipefail

JETSON_IP="${1:-192.168.2.240}"
JETSON_USER="root"
TARGET_DIR="/opt/hotpot-infer"
REBUILD="${2:-}"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

echo "========================================"
echo "  Hotpot Inference Pipeline Deploy"
echo "========================================"
echo "  Target: ${JETSON_USER}@${JETSON_IP}:${TARGET_DIR}"
echo ""

# ── Step 1: 创建目标目录 ──
echo "=== Step 1: 创建目录 ==="
ssh ${JETSON_USER}@${JETSON_IP} "
    mkdir -p ${TARGET_DIR}/{pipeline,models,config,docker/yolo-jetson,bin}
    mkdir -p /tmp/ipc_frames
"

# ── Step 2: 部署代码 ──
echo "=== Step 2: 部署代码 ==="
scp -r pipeline/* ${JETSON_USER}@${JETSON_IP}:${TARGET_DIR}/pipeline/
scp -r config/* ${JETSON_USER}@${JETSON_IP}:${TARGET_DIR}/config/
scp -r docker/yolo-jetson/* ${JETSON_USER}@${JETSON_IP}:${TARGET_DIR}/docker/yolo-jetson/

# ── Step 3: 部署 systemd ──
echo "=== Step 3: 部署 systemd ==="
scp systemd/*.service ${JETSON_USER}@${JETSON_IP}:/tmp/
ssh ${JETSON_USER}@${JETSON_IP} "
    cp /tmp/ipc-grabber.service /etc/systemd/system/
    cp /tmp/hotpot-pipeline.service /etc/systemd/system/
    systemctl daemon-reload
"

# ── Step 4: 部署模型(如本地存在) ──
echo "=== Step 4: 部署模型 ==="
if [ -f "../hotpot_smart_ops/jetson_deploy/models/adapter_weights.pt" ]; then
    # Actually use the local path
    echo "  Skipping (model deployment is manual via scp)"
fi
echo "  💡 模型部署: 手动 scp adapter_weights.pt / yolo26l.* 到 ${TARGET_DIR}/models/"

# ── Step 5: 同步 IPC grabber 配置(保留 Jetson 上的 stream_url) ──
echo "=== Step 5: 配置同步 ==="
ssh ${JETSON_USER}@${JETSON_IP} "
    # 如果 Jetson 上已有 ipc_config.yml, 保留 stream_url
    if [ -f ${TARGET_DIR}/config/ipc_config.yml ]; then
        echo '  Jetson 配置已存在, 保留'
    fi
"

# ── Step 6: 重启服务 ──
echo "=== Step 6: 重启服务 ==="
ssh ${JETSON_USER}@${JETSON_IP} "
    systemctl enable ipc-grabber
    systemctl restart ipc-grabber
    sleep 2
    systemctl status ipc-grabber --no-pager | head -10
"

# ── Rebuild Docker (optional) ──
if [ "$REBUILD" = "--rebuild" ]; then
    echo ""
    echo "=== Step 7: 重建 Docker 镜像 ==="
    ssh ${JETSON_USER}@${JETSON_IP} "
        cd ${TARGET_DIR}/docker/yolo-jetson
        docker build -t yolo-jetson-infer:local .
        docker pull nvcr.io/nvidia/l4t-pytorch:r34.1.1-pth1.12-py3 || echo '⚠️  l4t-pytorch pull failed, check network'
    "
fi

echo ""
echo "========================================"
echo "  ✅ 部署完成"
echo "========================================"
echo ""
echo "  验证:"
echo "    ssh ${JETSON_USER}@${JETSON_IP} 'ls -la ${TARGET_DIR}/pipeline/'"
echo "    ssh ${JETSON_USER}@${JETSON_IP} 'systemctl status ipc-grabber'"
echo ""
echo "  手动部署模型:"
echo "    scp adapter_weights.pt ${JETSON_USER}@${JETSON_IP}:${TARGET_DIR}/models/"
echo "    scp yolo26l.onnx yolo26l.pt ${JETSON_USER}@${JETSON_IP}:${TARGET_DIR}/models/"
echo ""
echo "  测试推理:"
echo "    ssh ${JETSON_USER}@${JETSON_IP} 'python3 ${TARGET_DIR}/pipeline/inference_pipeline.py --frame /tmp/ipc_frames/latest.jpg'"
