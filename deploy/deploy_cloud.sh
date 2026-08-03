#!/bin/bash
# ============================================================
#  火瞳 · 云端部署自动化脚本 v1.0
#  腾讯云服务器 (43.139.143.12) 一键部署 + 验证
#
#  用法:
#    ./deploy_cloud.sh              # 完整部署（默认）
#    ./deploy_cloud.sh code         # 仅更新代码
#    ./deploy_cloud.sh db           # 仅初始化数据库
#    ./deploy_cloud.sh restart      # 仅重启服务
#    ./deploy_cloud.sh rollback     # 回滚到上一版本
#    ./deploy_cloud.sh status       # 查看服务状态
# ============================================================

set -euo pipefail

# ── 配置 ──
CLOUD_HOST="${CLOUD_HOST:-43.139.143.12}"
CLOUD_USER="${CLOUD_USER:-root}"
CLOUD_DIR="${CLOUD_DIR:-/opt/hotpot-platform}"
BRANCH="${BRANCH:-feature/d1-expo-sprint}"
LOG_FILE="/tmp/hotpot-cloud-deploy-$(date +%Y%m%d-%H%M%S).log"
BACKUP_DIR="/opt/hotpot-platform/backups"

# 颜色输出
GREEN='\033[0;32m'; RED='\033[0;31m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; CYAN='\033[0;36m'; NC='\033[0m'

log()   { echo -e "${GREEN}[$(date +%H:%M:%S)]${NC} $*" | tee -a "$LOG_FILE"; }
warn()  { echo -e "${YELLOW}[$(date +%H:%M:%S)] WARN:${NC} $*" | tee -a "$LOG_FILE"; }
err()   { echo -e "${RED}[$(date +%H:%M:%S)] ERR:${NC} $*" | tee -a "$LOG_FILE"; }
check() { echo -e "  ${GREEN}✓${NC} $*"; }
fail()  { echo -e "  ${RED}✗${NC} $*"; }
info()  { echo -e "  ${BLUE}ℹ${NC} $*"; }

# ── SSH辅助函数 ──
cloud() {
    ssh -o ConnectTimeout=10 -o StrictHostKeyChecking=no ${CLOUD_USER}@${CLOUD_HOST} "$@"
}

# ════════════════════════════════════════════════════════
# Phase 0: 环境预检
# ════════════════════════════════════════════════════════
phase0_check() {
    log "Phase 0: 云端环境预检"

    # 检查SSH连接
    if cloud "echo ok" >/dev/null 2>&1; then
        check "SSH连接: ${CLOUD_USER}@${CLOUD_HOST}"
    else
        fail "云端服务器不可达 (${CLOUD_HOST})"
        exit 1
    fi

    # 检查目录存在
    if cloud "[ -d ${CLOUD_DIR} ]"; then
        check "部署目录: ${CLOUD_DIR}"
    else
        warn "部署目录不存在，将自动创建"
    fi

    # 检查Git仓库
    if cloud "cd ${CLOUD_DIR} && git remote -v | grep -q origin"; then
        check "Git仓库已配置"
    else
        fail "Git仓库未初始化"
        exit 1
    fi

    # 检查Python环境
    PYTHON_VERSION=$(cloud "python3 --version 2>&1 | awk '{print \$2}'" || echo "N/A")
    check "Python版本: ${PYTHON_VERSION}"

    # 检查PostgreSQL客户端
    if cloud "which psql >/dev/null 2>&1"; then
        PG_VERSION=$(cloud "psql --version | awk '{print \$3}'" || echo "?")
        check "PostgreSQL客户端: ${PG_VERSION}"
    else
        warn "PostgreSQL客户端未安装（数据库操作将跳过）"
    fi
}

# ════════════════════════════════════════════════════════
# Phase 1: 代码更新
# ════════════════════════════════════════════════════════
phase1_code() {
    log "Phase 1: 拉取最新代码 [分支: ${BRANCH}]"

    # 备份当前版本（用于回滚）
    cloud "
        mkdir -p ${BACKUP_DIR}
        cd ${CLOUD_DIR}
        CURRENT_COMMIT=\$(git rev-parse --short HEAD)
        BACKUP_NAME=\"backup_\$(date +%Y%m%d_%H%M%S)_\${CURRENT_COMMIT}\"
        tar -czf ${BACKUP_DIR}/\${BACKUP_NAME}.tar.gz \
            --exclude='.git' \
            --exclude='__pycache__' \
            --exclude='*.pyc' \
            --exclude='node_modules' \
            --exclude='*.db' \
            --exclude='data/*.db' \
            . 2>/dev/null && echo \"✅ 已备份: \${BACKUP_NAME}\" || echo \"⚠️ 备份失败\"
    "

    # 拉取最新代码
    cloud "
        cd ${CLOUD_DIR}
        git stash || true
        git fetch origin ${BRANCH}
        git checkout ${BRANCH}
        git reset --hard origin/${BRANCH}
        git submodule update --init --recursive 2>/dev/null || true
        NEW_COMMIT=\$(git rev-parse --short HEAD)
        echo \"📦 已更新至: \${NEW_COMMIT}\"
    " 2>&1 | tee -a "$LOG_FILE"

    check "代码更新完成"
}

# ════════════════════════════════════════════════════════
# Phase 2: 数据库初始化
# ════════════════════════════════════════════════════════
phase2_database() {
    log "Phase 2: 数据库初始化与迁移"

    # 检查是否配置了PG连接
    HAS_PG=$(cloud "
        if [ -n \"\${HOTPOT_DATABASE_URL:-}\" ]; then
            echo 'PG'
        else
            echo 'SQLITE'
        fi
    " 2>/dev/null || echo "UNKNOWN")

    info "数据库模式: ${HAS_PG}"

    case "$HAS_PG" in
        PG)
            log "  使用PostgreSQL模式..."

            # 执行audit_schema.sql
            SCHEMA_FILE="${CLOUD_DIR}/hotpot_platform/cloud/event_hub/middleware/audit_schema.sql"
            if cloud "[ -f ${SCHEMA_FILE} ]"; then
                cloud "
                    export HOTPOT_DATABASE_URL=\"\${HOTPOT_DATABASE_URL}\"
                    cd ${CLOUD_DIR}
                    python3 -c \"
from hotpot_platform.cloud.event_hub.middleware.db_init import init_all_schemas
init_all_schemas()
print('✅ Schema初始化完成')
\" 2>&1
                " | tee -a "$LOG_FILE"
                check "Audit Schema初始化完成 (PG)"
            else
                warn "audit_schema.sql不存在，跳过Schema初始化"
            fi

            # 迁移product_master.json
            PRODUCT_JSON="${CLOUD_DIR}/hotpot_platform/cloud/event_hub/middleware/product_master.json"
            if cloud "[ -f ${PRODUCT_JSON} ]"; then
                cloud "
                    export HOTPOT_DATABASE_URL=\"\${HOTPOT_DATABASE_URL}\"
                    cd ${CLOUD_DIR}
                    python3 -c \"
from hotpot_platform.cloud.event_hub.middleware.db_init import migrate_product_master_json
count = migrate_product_master_json()
print(f'✅ 产品数据迁移完成: {count}条')
\" 2>&1
                " | tee -a "$LOG_FILE"
                check "Product Master迁移完成 (PG)"
            else
                warn "product_master.json不存在，跳过产品迁移"
            fi
            ;;

        SQLITE)
            log "  使用SQLite验证模式..."
            cloud "
                cd ${CLOUD_DIR}
                unset HOTPOT_DATABASE_URL
                python3 -c \"
from hotpot_platform.cloud.event_hub.middleware.db_init import init_all_schemas
init_all_schemas()
print('✅ SQLite Schema初始化完成')
\" 2>&1
            " | tee -a "$LOG_FILE"
            check "SQLite验证模式初始化完成"
            ;;
    esac

    # 填充Demo数据（可选）
    SEED_SCRIPT="${CLOUD_DIR}/scripts/seed_demo_data.py"
    if cloud "[ -f ${SEED_SCRIPT} ]" && [ "${SKIP_SEED:-0}" != "1" ]; then
        log "  填充Demo数据..."
        cloud "
            cd ${CLOUD_DIR}
            python3 ${SEED_SCRIPT} --all 2>&1 | tail -20
        " | tee -a "$LOG_FILE"
        check "Demo数据填充完成"
    else
        info "跳过Demo数据填充 (SKIP_SEED=1 或脚本不存在)"
    fi
}

# ════════════════════════════════════════════════════════
# Phase 3: 服务重启
# ════════════════════════════════════════════════════════
phase3_restart() {
    log "Phase 3: 重启Edge UI / Event Hub服务"

    cloud "
        # 停止旧服务
        pkill -f 'uvicorn.*hotpot_platform.cloud.event_hub.app' 2>/dev/null && echo '  ⏹️  旧Event Hub已停止' || echo '  ℹ️ 无旧Event Hub运行'
        pkill -f 'uvicorn.*edge.ui.server' 2>/dev/null && echo '  ⏹️  旧Edge UI已停止' || echo '  ℹ️ 无旧Edge UI运行'
        sleep 2

        # 清理旧日志（保留最近7天）
        find /tmp -name 'hotpot-*.log' -mtime +7 -delete 2>/dev/null || true

        # 启动Event Hub (:8098)
        cd ${CLOUD_DIR}
        nohup python3 -m uvicorn hotpot_platform.cloud.event_hub.app:app \\
            --host 0.0.0.0 --port 8098 \\
            --workers 1 \\
            > /tmp/hotpot-hub.log 2>&1 &
        HUB_PID=\$!
        echo \"  🚀 Event Hub启动中... PID:\${HUB_PID}\"

        sleep 4

        # 验证启动
        if kill -0 \$HUB_PID 2>/dev/null; then
            if curl -s --max-time 3 http://localhost:8098/health | grep -q 'ok'; then
                echo '  ✅ Event Hub :8098 启动成功'
            else
                echo '  ❌ Event Hub健康检查失败'
                tail -30 /tmp/hotpot-hub.log
            fi
        else
            echo '  ❌ Event Hub进程异常退出'
            tail -30 /tmp/hotpot-hub.log
        fi
    " 2>&1 | tee -a "$LOG_FILE"

    check "服务重启流程执行完毕"
}

# ════════════════════════════════════════════════════════
# Phase 4: 健康检查
# ════════════════════════════════════════════════════════
phase4_verify() {
    log "Phase 4: 健康检查与端点验证"

    # 1. Event Hub健康检查
    log "  [1/5] Event Hub :8098 ..."
    HUB_STATUS=$(curl -s --max-time 5 "http://${CLOUD_HOST}:8098/health" 2>/dev/null || echo '{"status":"DOWN"}')
    if echo "$HUB_STATUS" | grep -q '"ok"'; then
        check "Event Hub :8098 正常"
    else
        fail "Event Hub :8098 异常: ${HUB_STATUS}"
    fi

    # 2. API根路径检查
    log "  [2/5] API文档 ..."
    API_DOCS=$(curl -s -o /dev/null -w "%{http_code}" "http://${CLOUD_HOST}:8098/docs" 2>/dev/null || echo "000")
    if [ "$API_DOCS" = "200" ]; then
        check "API文档可访问 (HTTP ${API_DOCS})"
    else
        warn "API文档不可访问 (HTTP ${API_DOCS})"
    fi

    # 3. 数据库连接检查（如果有PG配置）
    log "  [3/5] 数据库连接 ..."
    DB_CHECK=$(cloud "
        cd ${CLOUD_DIR}
        python3 -c \"
import os
url = os.environ.get('HOTPOT_DATABASE_URL', '')
if url:
    try:
        from hotpot_platform.cloud.event_hub.middleware.db_init import _get_pg_connection
        conn = _get_pg_connection()
        conn.close()
        print('PG_OK')
    except Exception as e:
        print(f'PG_ERR:{str(e)[:50]}')
else:
    try:
        from hotpot_platform.cloud.event_hub.middleware.db_init import _get_sqlite_path
        import sqlite3
        db = sqlite3.connect(str(_get_sqlite_path()))
        cursor = db.cursor()
        cursor.execute('SELECT count(*) FROM sqlite_master WHERE type=\\\"table\\\"')
        count = cursor.fetchone()[0]
        db.close()
        print(f'SQLITE_OK:{count}tables')
    except Exception as e:
        print(f'SQLITE_ERR:{str(e)[:50]}')
\" 2>&1
    " 2>/dev/null || echo "DB_CHECK_FAILED")

    if echo "$DB_CHECK" | grep -q "_OK"; then
        check "数据库连接正常: ${DB_CHECK}"
    else
        warn "数据库检查异常: ${DB_CHECK}"
    fi

    # 4. Gateway审计端点检查
    log "  [4/5] Agent Gateway ..."
    GW_CHECK=$(curl -s --max-time 5 "http://${CLOUD_HOST}:8098/v1/gateway/audit-log?limit=1" 2>/dev/null | head -c 200 || echo "{}")
    if echo "$GW_CHECK" | grep -q '"audit_log"\|"actions"\|[\[]'; then
        check "Gateway审计端点可用"
    else
        info "Gateway端点返回: ${GW_CHECK} (可能尚未有审计记录)"
    fi

    # 5. Demo页面检查（如果存在）
    log "  [5/5] 前端资源 ..."
    TRACE_CHECK=$(curl -s -o /dev/null -w "%{http_code}" "http://${CLOUD_HOST}:8098/static/trace.html" 2>/dev/null || echo "000")
    if [ "$TRACE_CHECK" = "200" ]; then
        check "trace.html前端可访问 (HTTP ${TRACE_CHECK})"
    else
        info "trace.html暂不可用 (HTTP ${TRACE_CHECK})，可能需要单独构建"
    fi
}

# ════════════════════════════════════════════════════════
# Phase 5: 部署报告
# ════════════════════════════════════════════════════════
phase5_report() {
    echo ""
    echo "╔══════════════════════════════════════════════════╗"
    echo "║       🔥 火瞳 · 云端部署完成                      ║"
    echo "╠══════════════════════════════════════════════════╣"
    printf "║  服务器   %-37s ║\n" "${CLOUD_HOST}"
    printf "║  目录     %-37s ║\n" "${CLOUD_DIR}"
    printf "║  分支     %-37s ║\n" "${BRANCH}"
    printf "║  日志     %-37s ║\n" "${LOG_FILE}"
    echo "╠══════════════════════════════════════════════════╣"
    printf "║  Event Hub   http://%s:8098           ║\n" "${CLOUD_HOST}"
    printf "║  API Docs    http://%s:8098/docs       ║\n" "${CLOUD_HOST}"
    printf "║  Health      http://%s:8098/health     ║\n" "${CLOUD_HOST}"
    echo "╠══════════════════════════════════════════════════╣"
    echo "║  常用命令:                                    ║"
    echo "║    查看日志: ssh ${CLOUD_HOST} tail -f /tmp/hotpot-hub.log ║"
    echo "║    服务状态: ./deploy_cloud.sh status             ║"
    echo "║    回滚操作: ./deploy_cloud.sh rollback            ║"
    echo "╚══════════════════════════════════════════════════╝"
}

# ════════════════════════════════════════════════════════
# 回滚功能
# ════════════════════════════════════════════════════════
do_rollback() {
    log "开始回滚操作..."

    # 查找最新备份
    LATEST_BACKUP=$(cloud "ls -t ${BACKUP_DIR}/backup_*.tar.gz 2>/dev/null | head -1" || echo "")

    if [ -z "$LATEST_BACKUP" ]; then
        err "没有找到可用的备份文件!"
        exit 1
    fi

    warn "即将回滚到: $(basename $LATEST_BACKUP)"
    read -p "确认回滚? (y/N): " CONFIRM
    [ "$CONFIRM" != "y" ] && { info "回滚已取消"; exit 0; }

    cloud "
        cd ${CLOUD_DIR}
        # 停止服务
        pkill -f 'uvicorn.*hotpot_platform.cloud.event_hub.app' 2>/dev/null || true
        sleep 2

        # 清空当前目录（排除.git和backups）
        find . -maxdepth 1 ! -name '.' ! -name '.git' ! -name 'backups' -exec rm -rf {} \; 2>/dev/null || true

        # 解压备份
        tar -xzf ${LATEST_BACKUP} -C .
        echo '✅ 回滚完成'
    "

    # 重启服务
    phase3_restart
    phase4_verify
    phase5_report
}

# ════════════════════════════════════════════════════════
# 状态查看
# ════════════════════════════════════════════════════════
do_status() {
    echo ""
    echo "╔══════════════════════════════════════════════════╗"
    echo "║       🔥 火瞳 · 云端服务状态                     ║"
    echo "╚══════════════════════════════════════════════════╝"
    echo ""

    # Git信息
    echo "📦 代码版本:"
    cloud "cd ${CLOUD_DIR} && git log -1 --oneline && git branch --show-current" 2>/dev/null || echo "  (无法获取)"
    echo ""

    # 服务状态
    echo "🖥️  服务进程:"
    cloud "
        ps aux | grep -E '(uvicorn|hotpot)' | grep -v grep | while read line; do
            echo \"  \$line\"
        done
        [ \$(ps aux | grep -E 'uvicorn.*event_hub' | grep -v grep | wc -l) -eq 0 ] && echo '  (无Event Hub进程)'
    " 2>/dev/null
    echo ""

    # 端口监听
    echo "🔌 端口监听:"
    cloud "ss -tlnp | grep -E ':(8098|8080|9080|9100)\b' || echo '  (无相关端口监听)'" 2>/dev/null
    echo ""

    # 健康检查
    echo "❤️  健康检查:"
    if curl -s --max-time 3 "http://${CLOUD_HOST}:8098/health" | grep -q 'ok'; then
        echo "  ✅ Event Hub :8098 正常"
    else
        echo "  ❌ Event Hub :8098 异常"
    fi
    echo ""

    # 备份列表
    echo "💾 最近备份:"
    cloud "ls -lh ${BACKUP_DIR}/backup_*.tar.gz 2>/dev/null | tail -3 || echo '  (无备份)'" 2>/dev/null
}

# ════════════════════════════════════════════════════════
# 主流程
# ════════════════════════════════════════════════════════
main() {
    echo ""
    echo "╔══════════════════════════════════════════════════╗"
    echo "║  🔥 火瞳 · 云端部署工具 v1.0                     ║"
    echo "╠══════════════════════════════════════════════════╣"
    echo "║  目标: ${CLOUD_HOST}                              ║"
    echo "║  分支: ${BRANCH}                                  ║"
    echo "║  时间: $(date '+%Y-%m-%d %H:%M:%S')                ║"
    echo "╚══════════════════════════════════════════════════╝"
    echo ""

    phase0_check
    phase1_code
    phase2_database
    phase3_restart
    phase4_verify
    phase5_report

    log "部署完成! 日志文件: ${LOG_FILE}"
}

# ── 命令路由 ──
case "${1:-}" in
    code)    phase0_check; phase1_code; log "代码更新完成" ;;
    db)      phase0_check; phase2_database; log "数据库初始化完成" ;;
    restart) phase0_check; phase3_restart; phase4_verify; log "服务重启完成" ;;
    rollback) do_rollback ;;
    status)  do_status ;;
    *)       main ;;
esac
