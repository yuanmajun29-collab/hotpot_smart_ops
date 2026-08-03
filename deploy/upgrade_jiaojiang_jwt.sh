#!/bin/bash
# ============================================================
#  椒江店 Edge UI JWT 升级脚本 v1.0
#  将Phase 2+3的JWT认证体系部署到椒江店Jetson
#
#  前置条件:
#    1. 本机已配置SSH密钥到 root@172.16.1.60
#    2. 或使用 sshpass: apt install sshpass
#
#  用法:
#    ./upgrade_jiaojiang_jwt.sh          # 完整升级
#    ./upgrade_jiaojiang_jwt.sh dry-run   # 仅检查不执行
#    ./upgrade_jiaojiang_jwt.sh rollback  # 回滚到PIN版本
# ============================================================

set -euo pipefail

# ── 配置 ──
JETSON_HOST="${JETSON_HOST:-172.16.1.60}"
JETSON_USER="${JETSON_USER:-root}"
JETSON_PASS="${JETSON_PASS:-123456}"  # 椒江店默认密码
JETSON_DIR="/opt/hotpot-smart-ops"
EDGE_UI_DIR="${JETSON_DIR}/edge/edge-ui"
BACKUP_DIR="${JETSON_DIR}/backups/jwt-upgrade-$(date +%Y%m%d_%H%M%S)"

# 颜色输出
GREEN='\033[0;32m'; RED='\033[0;31m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; CYAN='\033[0;36m'; NC='\033[0m'

log()   { echo -e "${GREEN}[$(date +%H:%M:%S)]${NC} $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $*"; }
err()   { echo -e "${RED}[ERR]${NC} $*"; }
info()  { echo -e "${BLUE}[INFO]${NC} $*"; }

# ── SSH辅助函数 ──
jetson() {
    if command -v sshpass &>/dev/null; then
        sshpass -p "${JETSON_PASS}" ssh -o ConnectTimeout=10 -o StrictHostKeyChecking=no ${JETSON_USER}@${JETSON_HOST} "$@"
    else
        ssh -o ConnectTimeout=10 -o StrictHostKeyChecking=no ${JETSON_USER}@${JETSON_HOST} "$@"
    fi
}

jetson_scp() {
    local src=$1 dst=$2
    if command -v sshpass &>/dev/null; then
        sshpass -p "${JETSON_PASS}" scp -o StrictHostKeyChecking=no "$src" ${JETSON_USER}@${JETSON_HOST}:"$dst"
    else
        scp -o StrictHostKeyChecking=no "$src" ${JETSON_USER}@${JETSON_HOST}:"$dst"
    fi
}

# ════════════════════════════════════════════════════════
# Phase 0: 环境预检
# ════════════════════════════════════════════════════════
phase0_check() {
    log "Phase 0: 椒江店环境预检"

    # SSH连接测试
    if jetson "echo 'OK'" >/dev/null 2>&1; then
        log "✓ SSH连接: ${JETSON_USER}@${JETSON_HOST}"
    else
        err "椒江店Jetson不可达 (${JETSON_HOST})"
        err "请确认:"
        echo "  1. Jetson设备已开机且网络可达"
        echo "  2. SSH服务已启动 (systemctl status sshd)"
        echo "  3. 已配置SSH密钥或安装sshpass (apt install sshpass)"
        exit 1
    fi

    # Edge UI目录检查
    if jetson "[ -d ${EDGE_UI_DIR} ]"; then
        log "✓ Edge UI目录: ${EDGE_UI_DIR}"
    else
        err "Edge UI目录不存在: ${EDGE_UI_DIR}"
        exit 1
    fi

    # 当前login.html版本检测
    CURRENT_VERSION=$(jetson "head -5 ${EDGE_UI_DIR}/login.html | grep -o 'v[0-9]\.[0-9]' || echo 'unknown'")
    log "✓ 当前版本: ${CURRENT_VERSION}"

    # Edge UI运行状态
    if jetson "curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:9080/login.html | grep -q '200'"; then
        log "✓ Edge UI运行中 (:9080)"
    else
        warn "Edge UI未运行或端口非9080"
    fi
}

# ════════════════════════════════════════════════════════
# Phase 1: 备份当前版本
# ════════════════════════════════════════════════════════
phase1_backup() {
    log "Phase 1: 备份当前PIN版本"

    jetson "
        mkdir -p ${BACKUP_DIR}
        
        # 备份关键文件
        cp ${EDGE_UI_DIR}/login.html ${BACKUP_DIR}/login_v1_pin.html 2>/dev/null || true
        cp ${EDGE_UI_DIR}/assets/auth.js ${BACKUP_DIR}/auth_v1_pin.js 2>/dev/null || true
        
        # 记录备份信息
        cat > ${BACKUP_DIR}/backup_info.txt << EOF
备份时间: $(date)
备份原因: JWT认证体系升级
原始版本: ${CURRENT_VERSION}
恢复命令: bash -c 'cp ${BACKUP_DIR}/*.html ${EDGE_UI_DIR}/ && cp ${BACKUP_DIR}/*.js ${EDGE_UI_DIR}/assets/'
EOF
        echo '✅ 备份完成'
    "

    log "✓ 备份目录: ${BACKUP_DIR}"
}

# ════════════════════════════════════════════════════════
# Phase 2: 传输JWT版本文件
# ════════════════════════════════════════════════════════
phase2_deploy() {
    log "Phase 2: 部署JWT版本文件"

    # 传输login.html (Phase 2+3版本, 隐藏了PIN选项卡)
    if [ -f "edge/edge-ui/login.html" ]; then
        jetson_scp "edge/edge-ui/login.html" "${EDGE_UI_DIR}/login.html"
        log "✓ login.html 已部署 (JWT版本)"
    else
        err "本地文件不存在: edge/edge-ui/login.html"
        exit 1
    fi

    # 传输auth.js (Phase 2+3版本, 禁用PIN引导弹窗)
    if [ -f "edge/edge-ui/assets/auth.js" ]; then
        jetson_scp "edge/edge-ui/assets/auth.js" "${EDGE_UI_DIR}/assets/auth.js"
        log "✓ auth.js 已部署 (JWT版本)"
    else
        err "本地文件不存在: edge/edge-ui/assets/auth.js"
        exit 1
    fi

    # 可选: 传输备份文件 (用于回滚)
    if [ -f "edge/edge-ui/login_v1_pin_backup.html" ]; then
        jetson_scp "edge/edge-ui/login_v1_pin_backup.html" "${EDGE_UI_DIR}/"
        log "✓ PIN备份文件已传输"
    fi

    if [ -f "edge/edge-ui/assets/auth_v1_pin_backup.js" ]; then
        jetson_scp "edge/edge-ui/assets/auth_v1_pin_backup.js" "${EDGE_UI_DIR}/assets/"
        log "✓ auth PIN备份已传输"
    fi
}

# ════════════════════════════════════════════════════════
# Phase 3: 重启Edge UI服务
# ════════════════════════════════════════════════════════
phase3_restart() {
    log "Phase 3: 重启Edge UI服务"

    jetson "
        # 停止现有Edge UI进程
        pkill -f 'server_v2.py' || true
        sleep 2

        # 启动Edge UI (后台运行)
        cd ${JETSON_DIR}
        nohup python3 edge/edge-ui/server_v2.py > /tmp/edge-ui.log 2>&1 &
        echo \$! > /tmp/edge-ui.pid
        sleep 3

        # 验证启动成功
        if curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:9080/login.html | grep -q '200'; then
            echo '✅ Edge UI重启成功'
        else
            echo '❌ Edge UI启动失败，查看日志:'
            tail -20 /tmp/edge-ui.log
            exit 1
        fi
    "

    log "✓ Edge UI已重启"
}

# ════════════════════════════════════════════════════════
# Phase 4: 验证升级结果
# ════════════════════════════════════════════════════════
phase4_verify() {
    log "Phase 4: 验证JWT升级结果"

    # 4.1 页面可访问性
    HTTP_CODE=$(jetson "curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:9080/login.html")
    if [ "$HTTP_CODE" = "200" ]; then
        log "✓ 登录页可访问 (HTTP ${HTTP_CODE})"
    else
        err "登录页不可访问 (HTTP ${HTTP_CODE})"
        return 1
    fi

    # 4.2 版本验证 (检查是否包含JWT关键字)
    HAS_JWT=$(jetson "grep -c 'jwt-login\|TokenManager' ${EDGE_UI_DIR}/login.html ${EDGE_UI_DIR}/assets/auth.js 2>/dev/null | awk -F: '{s+=\$2} END{print s}'")
    if [ "$HAS_JWT" -gt "5" ]; then
        log "✓ JWT组件已集成 (${HAS_JWT}个引用)"
    else
        warn "JWT组件引用较少 (${HAS_JWT}个)，可能未完全升级"
    fi

    # 4.3 PIN隐藏验证 (检查选项卡是否display:none)
    HIDDEN_PIN=$(jetson "grep -c 'display.*none.*tab-container\|pin-degrade-notice' ${EDGE_UI_DIR}/login.html 2>/dev/null")
    if [ "$HIDDEN_PIN" -gt "0" ]; then
        log "✓ PIN选项卡已隐藏 (纯JWT模式)"
    else
        warn "PIN选项卡仍可见 (双模式)"
    fi

    # 4.4 文件完整性
    LOGIN_SIZE=$(jetson "wc -c < ${EDGE_UI_DIR}/login.html")
    AUTH_SIZE=$(jetson "wc -c < ${EDGE_UI_DIR}/assets/auth.js")
    log "✓ 文件大小: login.html (${LOGIN_SIZE}B) + auth.js (${AUTH_SIZE}B)"

    echo ""
    info "═════════════════════════════════════════"
    info "  🎉 椒江店JWT升级完成!"
    info "═════════════════════════════════════════"
    info ""
    info "访问地址: http://${JETSON_HOST}:9080/login.html"
    info "测试账号: zhangdian / demo"
    info ""
    info "回滚命令: $0 rollback"
}

# ════════════════════════════════════════════════════════
# 回滚功能
# ════════════════════════════════════════════════════════
do_rollback() {
    log "执行回滚: 恢复到PIN版本"

    # 查找最新备份
    LATEST_BACKUP=$(jetson "ls -dt ${JETSON_DIR}/backups/jwt-upgrade-* 2>/dev/null | head -1")

    if [ -z "$LATEST_BACKUP" ]; then
        err "未找到备份目录，无法回滚"
        exit 1
    fi

    log "使用备份: ${LATEST_BACKUP}"

    jetson "
        # 恢复文件
        cp ${LATEST_BACKUP}/login_v1_pin.html ${EDGE_UI_DIR}/login.html 2>/dev/null || true
        cp ${LATEST_BACKUP}/auth_v1_pin.js ${EDGE_UI_DIR}/assets/auth.js 2>/dev/null || true

        # 重启服务
        pkill -f 'server_v2.py' || true
        sleep 2
        cd ${JETSON_DIR}
        nohup python3 edge/edge-ui/server_v2.py > /tmp/edge-ui.log 2>&1 &
        sleep 3

        echo '✅ 回滚完成，已恢复PIN版本'
    "

    log "✓ 回滚完成"
}

# ════════════════════════════════════════════════════════
# Dry Run模式
# ════════════════════════════════════════════════════════
do_dry_run() {
    info "====== Dry Run 模式 (仅检查不执行) ======"
    echo ""

    info "[检查] 本地JWT版本文件"
    ls -lh edge/edge-ui/login.html edge/edge-ui/assets/auth.js 2>/dev/null || err "❌ 缺少JWT版本文件"

    echo ""
    info "[检查] SSH连接性"
    timeout 5 bash -c "jetson 'echo OK'" 2>/dev/null && log "✓ SSH可用" || warn "❌ SSH需要配置"

    echo ""
    info "[将要执行的步骤]"
    echo "  1. 备份当前login.html + auth.js → ${BACKUP_DIR}"
    echo "  2. 传输JWT版本: login.html (10.8KB) + auth.js (11.9KB)"
    echo "  3. 重启Edge UI服务 (:9080)"
    echo "  4. 验证: 页面可访问 + JWT组件集成 + PIN隐藏"

    echo ""
    info "准备好后执行: $0"
}

# ════════════════════════════════════════════════════════
# 主流程
# ════════════════════════════════════════════════════════
case "${1:-}" in
    dry-run|dryrun|--dry-run)
        do_dry_run
        ;;
    rollback)
        phase0_check
        do_rollback
        ;;
    "")
        echo "╔══════════════════════════════════════════════╗"
        echo "║  🔐 椒江店 Edge UI JWT 升级工具 v1.0       ║"
        echo "╚══════════════════════════════════════════════╝"
        echo ""

        phase0_check
        phase1_backup
        phase2_deploy
        phase3_restart
        phase4_verify
        ;;
    *)
        echo "用法: $0 [dry-run|rollback]"
        echo ""
        echo "命令:"
        echo "  (无参数)   执行完整JWT升级流程"
        echo "  dry-run    仅检查环境，不执行升级"
        echo "  rollback   回滚到PIN版本"
        exit 1
        ;;
esac
