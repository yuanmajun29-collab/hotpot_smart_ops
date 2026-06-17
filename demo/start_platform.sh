#!/usr/bin/env bash
# 启动看板 + Hub（nginx 双端口 + Event Hub）
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

HUB_PORT="${HUB_PORT:-8088}"
NGINX_PREFIX="/tmp/hotpot-nginx"
NGINX_CONF="$ROOT/deploy/nginx/local-test-main.conf"

mkdir -p "$NGINX_PREFIX"

echo "[1/4] Event Hub :${HUB_PORT}..."
if curl -sf "http://127.0.0.1:${HUB_PORT}/health" >/dev/null 2>&1; then
  echo "  已在运行"
else
  pkill -f "cloud/event_hub/server.py --port ${HUB_PORT}" 2>/dev/null || true
  sleep 1
  nohup python3 cloud/event_hub/server.py --port "$HUB_PORT" --seed-dir demo/data/stores \
    > /tmp/hotpot-hub.log 2>&1 &
  for i in $(seq 1 15); do
    curl -sf "http://127.0.0.1:${HUB_PORT}/health" >/dev/null && break
    sleep 1
  done
fi

echo "[2/4] Nginx 看板 :80 / :3000 / :3001..."
nginx -t -c "$NGINX_CONF" -p "$NGINX_PREFIX" 2>/dev/null || true
if [[ -f "$NGINX_PREFIX/nginx.pid" ]] && kill -0 "$(cat "$NGINX_PREFIX/nginx.pid")" 2>/dev/null; then
  nginx -s reload -c "$NGINX_CONF" -p "$NGINX_PREFIX" 2>/dev/null || true
else
  nginx -c "$NGINX_CONF" -p "$NGINX_PREFIX"
fi

echo "[3/4] 视觉 worker..."
if ! pgrep -f "vision_worker.py --store-id store_yuhuan" >/dev/null 2>&1; then
  bash demo/run_vision_daemon.sh "http://127.0.0.1:${HUB_PORT}" "${VISION_INTERVAL:-5}" || true
fi

PRIV_IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
PUB_IP="$(curl -sf --connect-timeout 2 ifconfig.me 2>/dev/null || true)"

echo "[4/4] 就绪"
echo "----------------------------------------------"
echo " 本机:     http://127.0.0.1/login.html"
echo " 内网 IP:  http://${PRIV_IP:-<内网IP>}/login.html"
echo " 内网:3000 http://${PRIV_IP:-<内网IP>}:3000/login.html"
echo " 运营后台: http://${PRIV_IP:-<内网IP>}:3001/admin/login.html"
if [[ -n "$PUB_IP" ]]; then
  echo " 公网:     http://${PUB_IP}/login.html  (需云安全组放行 80/3000/3001)"
fi
echo " Hub API:  http://127.0.0.1:${HUB_PORT}/health"
echo "----------------------------------------------"
echo "若外网仍无法访问，请在云控制台安全组入站规则放行 TCP 80、3000、3001"
