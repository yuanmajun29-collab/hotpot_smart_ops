#!/usr/bin/env bash
# 本地验证 deploy/nginx/split-ports.conf（:3000 业务 / :3001 运营后台）
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PREFIX=/tmp/hotpot-nginx
CONF="$ROOT/deploy/nginx/local-test-main.conf"

echo "[1] 停止 Python 看板（释放 3000）"
pkill -f "dashboard/serve.py" 2>/dev/null || true
sleep 1

echo "[2] 启动 nginx（prefix=$PREFIX）"
mkdir -p "$PREFIX"
touch "$PREFIX/error.log" "$PREFIX/access.log"
nginx -s stop -c "$CONF" -p "$PREFIX" 2>/dev/null || true
nginx -t -c "$CONF" -p "$PREFIX"
nginx -c "$CONF" -p "$PREFIX"

echo "[3] 检查端口"
ss -tlnp | grep -E ':3000|:3001' || { echo "nginx 未监听"; exit 1; }

echo ""
echo "[4] :3000 业务平台"
curl -sf -o /dev/null -w "  login.html     %{http_code}\n" http://127.0.0.1:3000/login.html
curl -s -o /dev/null -w "  admin/         %{http_code} (expect 403)\n" http://127.0.0.1:3000/admin/index.html
curl -sf http://127.0.0.1:3000/api/health | python3 -c "import sys,json; print('  api/health     ', json.load(sys.stdin)['status'])"

echo ""
echo "[5] :3001 运营后台"
curl -sI http://127.0.0.1:3001/ | awk '/HTTP|Location/{print "  "$0}'
curl -sf -o /dev/null -w "  admin/index    %{http_code}\n" http://127.0.0.1:3001/admin/index.html
curl -sf -o /dev/null -w "  assets/css     %{http_code}\n" http://127.0.0.1:3001/assets/theme.css
curl -s -o /dev/null -w "  home.html      %{http_code} (expect 403)\n" http://127.0.0.1:3001/home.html

echo ""
echo "[OK] 本地双端口验证通过"
echo "  业务平台: http://127.0.0.1:3000/login.html"
echo "  运营后台: http://127.0.0.1:3001/admin/index.html"
echo ""
echo "停止 nginx: nginx -s stop -c $CONF -p $PREFIX"
echo "恢复 Python 看板: python3 dashboard/serve.py --port 3000"
