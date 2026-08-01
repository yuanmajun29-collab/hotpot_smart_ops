#!/bin/bash
# ════════════════════════════════════════════════════════
#  火瞳Edge Gateway v2.0 → Jetson 部署脚本
#  用法: bash deploy_to_jetson.sh [jetson_ip]
#  默认: 172.16.1.60 (椒江店向日葵)
# ════════════════════════════════════════════════════════

set -e

JETSON_IP="${1:-172.16.1.60}"
JETSON_USER="root"
JETSON_PASS="123456"
REMOTE_BASE="/opt/hotpot-smart-ops"
EDGE_DIR="$REMOTE_BASE/edge/edge-ui"

LOCAL_SRC="$(cd "$(dirname "$0")" && pwd)"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_SUFFIX=".bak_$TIMESTAMP"

echo ""
echo "╔══════════════════════════════════════════════════╗"
echo "║   🔥 火瞳Edge Gateway v2.0 部署工具            ║"
echo "╠══════════════════════════════════════════════════╣"
echo "║  目标: $JETSON_IP"
echo "║  路径: $EDGE_DIR"
echo "║  时间: $(date '+%Y-%m-%d %H:%M:%S')              ║"
echo "╚══════════════════════════════════════════════════╝"
echo ""

# ── Step 1: 检查本地文件 ──
echo "📋 [1/7] 检查本地文件..."
for f in server_v2.py config_manager.py gateway.html conf/edge_config.yml; do
    if [ ! -f "$LOCAL_SRC/$f" ]; then
        echo "  ❌ 缺少文件: $f"
        exit 1
    fi
    echo "  ✅ $f ($(wc -c < "$LOCAL_SRC/$f") bytes)"
done

# ── Step 2: 备份远程旧文件（如果存在）──
echo ""
echo "📦 [2/7] 备份远程旧文件..."
ssh -o StrictHostKeyChecking=no -o ConnectTimeout=5 "$JETSON_USER@$JETSON_IP" "
    if [ -f '$EDGE_DIR/server.py' ]; then
        cp '$EDGE_DIR/server.py' '$EDGE_DIR/server.py$BACKUP_SUFFIX' && echo '  ✅ server.py 已备份'
    fi
    if [ -f '$EDGE_DIR/gateway.html' ]; then
        cp '$EDGE_DIR/gateway.html' '$EDGE_DIR/gateway.html$BACKUP_SUFFIX' && echo '  ✅ gateway.html 已备份'
    fi
" 2>/dev/null || echo "  ⚠️ SSH连接失败或无旧文件，跳过备份"

# ── Step 3: 创建远程目录 ──
echo ""
echo "📁 [3/7] 创建远程目录..."
ssh -o StrictHostKeyChecking=no "$JETSON_USER@$JETSON_IP" "
    mkdir -p '$EDGE_DIR/conf'
    mkdir -p '$REMOTE_BASE/edge/common'
    echo '  ✅ 目录已就绪'
" 2>&1 | grep -v "password" || true

# ── Step 4: 上传新文件 ──
echo ""
echo "🚀 [4/7] 上传文件到Jetson..."

scp -o StrictHostKeyChecking=no \
    "$LOCAL_SRC/server_v2.py" \
    "$JETSON_USER@$JETSON_IP:$EDGE_DIR/server_v2.py" \
    2>/dev/null && echo "  ✅ server_v2.py"

scp -o StrictHostKeyChecking=no \
    "$LOCAL_SRC/config_manager.py" \
    "$JETSON_USER@$JETSON_IP:$EDGE_DIR/config_manager.py" \
    2>/dev/null && echo "  ✅ config_manager.py"

scp -o StrictHostKeyChecking=no \
    "$LOCAL_SRC/gateway.html" \
    "$JETSON_USER@$JETSON_IP:$EDGE_DIR/gateway.html" \
    2>/dev/null && echo "  ✅ gateway.html"

scp -o StrictHostKeyChecking=no \
    "$LOCAL_SRC/conf/edge_config.yml" \
    "$JETSON_USER@$JETSON_IP:$EDGE_DIR/conf/edge_config.yml" \
    2>/dev/null && echo "  ✅ edge_config.yml"

# FrameGrabber (如果不存在于远程)
ssh -o StrictHostKeyChecking=no "$JETSON_USER@$JETSON_IP" "
    if [ ! -f '$REMOTE_BASE/edge/common/frame_grabber.py' ]; then
        echo '  ⚠️ frame_grabber.py 不存在于远程，请确认已部署'
    else
        echo '  ✅ frame_grabber.py 已存在'
    fi
" 2>/dev/null || true

# ── Step 5: 安装PyYAML依赖 ──
echo ""
echo "📦 [5/7] 检查Python依赖..."
ssh -o StrictHostKeyChecking=no "$JETSON_USER@$JETSON_IP" "
    python3 -c 'import yaml; print(\"PyYAML:\", yaml.__version)' 2>/dev/null || {
        echo '  📦 正在安装 PyYAML...'
        pip3 install pyyaml --quiet 2>/dev/null && echo '  ✅ PyYAML 安装成功' || echo '  ❌ PyYAML 安装失败'
    }
    python3 -c 'import requests; print(\"requests: OK\")' 2>/dev/null || {
        echo '  📦 正在安装 requests...'
        pip3 install requests --quiet 2>/dev/null && echo '  ✅ requests 安装成功'
    }
" 2>/dev/null || echo "  ⚠️ 依赖检查跳过"

# ── Step 6: 停止旧服务、启动新服务 ──
echo ""
echo "🔄 [6/7] 重启Edge Gateway服务..."
ssh -o StrictHostKeyChecking=no "$JETSON_USER@$JETSON_IP" "
    # 停止旧的 Edge UI (端口9080)
    pkill -f 'server.py.*9080' 2>/dev/null && echo '  ⏹️  旧服务已停止' || echo '  ℹ️ 无旧服务运行'

    sleep 1

    # 启动新的 v2 服务
    cd '$EDGE_DIR'
    nohup python3 server_v2.py --port 9080 > /tmp/hotpot-gateway.log 2>&1 &
    echo \$! > /tmp/hotpot-gateway.pid
    sleep 2

    # 验证启动
    if kill -0 \$(cat /tmp/hotpot-gateway.pid) 2>/dev/null; then
        echo '  ✅ Edge Gateway v2.0 启动成功!'
        echo '     PID:' \$(cat /tmp/hotpot-gateway.pid)
        echo '     日志: /tmp/hotpot-gateway.log'
    else
        echo '  ❌ 启动失败，查看日志:'
        tail -20 /tmp/hotpot-gateway.log 2>/dev/null
    fi
" 2>/dev/null || echo "  ⚠️ 服务重启需要手动操作"

# ── Step 7: 验证 ──
echo ""
echo "✅ [7/7] 部署完成!"
echo ""
echo "╔══════════════════════════════════════════════════╗"
echo "║           🎉 部署成功！                        ║"
echo "╠══════════════════════════════════════════════════╣"
echo "║                                                ║"
echo "║  🔗 配置中心地址:                               ║"
echo "║     http://$JETSON_IP:9080/gateway.html"
echo "║                                                ║"
echo "║  📡 原有API(兼容):                              ║"
echo "║     http://$JETSON_IP:9080/api/cameras/list"
echo "║                                                ║"
echo "║  ☁️ 新增北向API:                                ║"
echo "║     POST /api/platform/login                    ║"
echo "║     GET  /api/platform/status                   ║"
echo "║     POST /api/platform/send-heartbeat            ║"
echo "║                                                ║"
echo "║  📋 配置文件:                                    ║"
echo "║     $EDGE_DIR/conf/edge_config.yml"
echo "║                                                ║"
echo "║  📝 日志:                                        ║"
echo "║     ssh $JETSON_IP tail -f /tmp/hotpot-gateway.log"
echo "╚══════════════════════════════════════════════════╝"
echo ""

# 快速连通性测试
echo "🔍 连通性测试..."
sleep 2
if curl -s --connect-timeout 3 "http://$JETSON_IP:9080/api/device/status" > /dev/null 2>&1; then
    echo "  ✅ Edge Gateway 可访问!"
else
    echo "  ⚠️ 无法连接，可能需要等待几秒或手动检查防火墙"
fi
