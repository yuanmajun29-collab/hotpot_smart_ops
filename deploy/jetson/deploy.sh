#!/bin/bash
# ──────────────────────────────────────────────
# Jetson 增量部署：同步代码 → 重启 → 验证
# 统一 agent server (:9100) 含前厅+后厨推理
#
# 用法：./deploy.sh
# ──────────────────────────────────────────────
set -euo pipefail

JETSON_HOST="${JETSON_HOST:-jetson}"
CONTAINER="${CONTAINER:-hotpot-edge}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
PORT="${PORT:-9100}"

echo "============================================"
echo " Jetson 增量部署"
echo " Target: ${JETSON_HOST}  Container: ${CONTAINER}"
echo " Port: ${PORT}"
echo "============================================"

# ── Step 0: 检查前置条件 ──
echo ""
echo "[0/4] 检查前置条件 ..."

if ! ssh "$JETSON_HOST" "docker ps --format '{{.Names}}' | grep -qx '$CONTAINER'" 2>/dev/null; then
  echo "  ⚠️  容器 $CONTAINER 未运行，尝试 docker compose up..."
  ssh "$JETSON_HOST" "cd /opt/hotpot-infer && docker compose up -d" || {
    echo "  ❌ 容器启动失败，请检查 /opt/hotpot-infer/docker-compose.yml"
    exit 1
  }
else
  echo "  ✅ 容器 $CONTAINER 运行中"
fi

# ── Step 1: 同步代码 ──
echo ""
echo "[1/4] 同步代码 ..."

# 整个 edge/ 目录
ssh "$JETSON_HOST" "docker exec $CONTAINER mkdir -p /workspace/edge"
tar czf - -C "$PROJECT_ROOT" edge/ 2>/dev/null | \
  ssh "$JETSON_HOST" "docker exec -i $CONTAINER tar xzf - -C /workspace/"

# 共用层
if [ -d "$PROJECT_ROOT/common" ]; then
  tar czf - -C "$PROJECT_ROOT" common/ 2>/dev/null | \
    ssh "$JETSON_HOST" "docker exec -i $CONTAINER tar xzf - -C /workspace/"
fi

echo "  ✅ 代码同步完成"

# ── Step 2: 重启服务 ──
echo ""
echo "[2/4] 重启服务 ..."
ssh "$JETSON_HOST" "docker restart $CONTAINER"
echo "  ✅ 已发送重启指令"

# ── Step 3: 等待就绪 ──
echo ""
echo "[3/4] 等待 agent 就绪 ..."
for i in $(seq 1 30); do
  if curl -s --connect-timeout 2 "http://${JETSON_HOST}:${PORT}/health" > /dev/null 2>&1; then
    echo "  ✅ Agent 就绪 (${i}s)"
    break
  fi
  sleep 2
done

# ── Step 4: 验证 ──
echo ""
echo "[4/4] 验证 ..."

HEALTH=$(curl -s "http://${JETSON_HOST}:${PORT}/health" 2>/dev/null || echo '{"status":"unreachable"}')
echo "$HEALTH" | python3 -m json.tool 2>/dev/null || echo "$HEALTH"

echo ""
echo "============================================"
echo " ✅ 部署完成"
echo " Health: http://${JETSON_HOST}:${PORT}/health"
echo "============================================"
