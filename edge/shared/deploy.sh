#!/bin/bash
# edge/deploy.sh
# 火锅边缘端增量部署
#
# 流程：Mac 准备代码+模型 → rsync 增量下发 Jetson → Docker build → 运行
#
# 用法:
#   ./edge/deploy.sh                    # 完整部署
#   ./edge/deploy.sh --code-only        # 只同步代码（模型不变）
#   ./edge/deploy.sh --dry-run          # 预览

set -euo pipefail

JETSON_IP="${JETSON_IP:-192.168.2.240}"
JETSON_USER="root"
EDGE_TARGET="/opt/hotpot-infer"
MODEL_CACHE="./edge/models"
DRY_RUN=false
CODE_ONLY=false

for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=true ;;
    --code-only) CODE_ONLY=true ;;
  esac
done

echo "========================================="
echo "  火锅边缘端增量部署"
echo "  Target: $JETSON_USER@$JETSON_IP:$EDGE_TARGET"
echo "  Mode: ${DRY_RUN:+🔍 DRY RUN}${DRY_RUN:-🚀 LIVE} ${CODE_ONLY:+(仅代码)}"
echo "========================================="

# ===== Step 1: 本地检查 =====
echo ""
echo "[1/5] 本地代码语法检查..."
python3 -m py_compile edge/pipeline/*.py edge/detector/*.py 2>/dev/null && echo "  ✅ OK" || { echo "  ❌ 语法错误"; exit 1; }

# ===== Step 2: 下载模型到本地缓存（Mac 端统一管理） =====
if [ "$CODE_ONLY" = false ]; then
  echo ""
  echo "[2/5] 准备模型文件（Mac → 本地缓存）..."
  mkdir -p "$MODEL_CACHE"

  declare -A MODEL_URLS=(
    ["yolov8n.pt"]="https://github.com/ultralytics/assets/releases/download/v8.2.0/yolov8n.pt"
    ["yolov8s.pt"]="https://github.com/ultralytics/assets/releases/download/v8.2.0/yolov8s.pt"
  )

  for name in "${!MODEL_URLS[@]}"; do
    target="$MODEL_CACHE/$name"
    url="${MODEL_URLS[$name]}"
    if [ -f "$target" ]; then
      echo "  ✅ $name (已缓存)"
    else
      echo "  ⬇️  下载 $name ..."
      [ "$DRY_RUN" = false ] && curl -fSL --connect-timeout 30 --max-time 300 -o "$target" "$url"
      echo "  ✅ $name 下载完成"
    fi
  done

  # adapter_weights.pt 已在 Git 中，检查存在
  if [ -f "$MODEL_CACHE/adapter_weights.pt" ]; then
    echo "  ✅ adapter_weights.pt"
  else
    echo "  ⚠️  adapter_weights.pt 缺失，请从 Git 拉取"
  fi
else
  echo ""
  echo "[2/5] 跳过模型准备（--code-only）"
fi

# ===== Step 3: 同步到 Jetson =====
echo ""
echo "[3/5] 增量同步 → Jetson..."

# 同步边缘端目录结构
SYNC_ITEMS=(
  "edge/pipeline"
  "edge/detector"
  "edge/stream"
  "edge/iot_mock"
  "edge/config"
  "edge/scripts"
  "edge/docker"
  "shared"
)

if [ "$CODE_ONLY" = false ]; then
  SYNC_ITEMS+=("edge/models")
fi

for item in "${SYNC_ITEMS[@]}"; do
  # 跳过不存在的路径
  [ -e "$item" ] || continue
  echo "  📁 $item → $EDGE_TARGET/"

  if [ "$DRY_RUN" = false ]; then
    # 确保 Jetson 目标目录存在
    ssh "$JETSON_USER@$JETSON_IP" "mkdir -p $EDGE_TARGET/ 2>/dev/null" || true

    if [ -d "$item" ]; then
      rsync -avz --delete \
        --exclude='__pycache__' --exclude='*.pyc' --exclude='.DS_Store' \
        "$item/" "$JETSON_USER@$JETSON_IP:$EDGE_TARGET/${item#edge/}/"
    else
      scp "$item" "$JETSON_USER@$JETSON_IP:$EDGE_TARGET/${item#edge/}"
    fi
  fi
done

# ===== Step 4: Docker 构建 =====
echo ""
echo "[4/5] Docker 构建（Jetson 端）..."

if [ "$DRY_RUN" = false ]; then
  ssh "$JETSON_USER@$JETSON_IP" "
    cd $EDGE_TARGET/docker/yolo-jetson && \
    docker build -t yolo-jetson-infer:latest . 2>&1 | tail -5 && \
    echo 'BUILD_OK'
  "
else
  echo "  [dry-run] docker build on Jetson"
fi

# ===== Step 5: 重启容器 =====
echo ""
echo "[5/5] 重启容器..."

if [ "$DRY_RUN" = false ]; then
  ssh "$JETSON_USER@$JETSON_IP" "
    cd $EDGE_TARGET/docker/yolo-jetson && \
    docker-compose down 2>/dev/null || true && \
    docker-compose up -d && \
    sleep 3 && \
    echo '--- Container Status ---' && \
    docker-compose ps
  "
else
  echo "  [dry-run] docker-compose down && up -d"
fi

echo ""
echo "========================================="
echo "  ✅ 部署完成"
echo "  Target: $JETSON_USER@$JETSON_IP"
echo "  状态:  ssh $JETSON_USER@$JETSON_IP 'docker ps --filter name=yolo'"
echo "========================================="
