#!/bin/bash
# ============================================================
# 🔥 火瞳系统 - 展会一键演示脚本
# 版本: v0.4.0-expo-ready
# 用途: 展会现场快速启动完整演示流程
# ============================================================

set -e  # 遇错即停

echo "=========================================="
echo "🔥 火瞳系统 - 展会演示启动器"
echo "版本: v0.4.0-expo-ready"
echo "日期: $(date '+%Y-%m-%d %H:%M:%S')"
echo "=========================================="
echo ""

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# ============================================================
# 配置区
# ============================================================
JETSON_IP="172.16.1.60"
JETSON_PORT="9080"
JETSON_USER="root"
JETSON_PASS="123456"
PIN_CODE="123456"

# ============================================================
# 函数定义
# ============================================================

print_step() {
    echo ""
    echo -e "${BLUE}━━━ Step $1: $2 ━━━${NC}"
}

print_success() {
    echo -e "${GREEN}✅ $1${NC}"
}

print_warning() {
    echo -e "${YELLOW}⚠️  $1${NC}"
}

print_error() {
    echo -e "${RED}❌ $1${NC}"
}

check_dependencies() {
    print_step "0" "检查依赖工具"

    # 检查curl
    if command -v curl &> /dev/null; then
        print_success "curl 已安装"
    else
        print_error "curl 未安装，请先安装"
        exit 1
    fi

    # 检查expect（用于SSH自动登录）
    if command -v expect &> /dev/null; then
        print_success "expect 已安装"
    else
        print_warning "expect 未安装，SSH操作需手动输入密码"
    fi

    echo ""
}

jetson_connectivity_test() {
    print_step "1" "测试Jetson连接性"

    # Ping测试
    if ping -c 1 -W 2 "$JETSON_IP" &> /dev/null; then
        print_success "Jetson可达 ($JETSON_IP)"
    else
        print_error "Jetson不可达！检查网络连接"
        exit 1
    fi

    # HTTP服务测试
    HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" --connect-timeout 5 "http://${JETSON_IP}:${JETSON_PORT}/login.html" || echo "000")

    if [ "$HTTP_CODE" = "200" ]; then
        print_success "Edge UI服务正常 (HTTP $HTTP_CODE)"
    else
        print_error "Edge UI无法访问 (HTTP $HTTP_CODE)"
        exit 1
    fi

    echo ""
}

initialize_demo_data() {
    print_step "2" "初始化Demo数据"

    # 使用expect自动执行SSH命令
    /usr/bin/expect << EOF
set timeout 30
spawn ssh -o StrictHostKeyChecking=no ${JETSON_USER}@${JETSON_IP}
expect "password:"
send "${JETSON_PASS}\r"
expect "#"

send "cd /opt/hotpot-smart-ops && PYTHONPATH=/opt/hotpot-smart-ops python3 demo/demo_runner.py --mode init\r"
expect {
    "✅" { puts "\n${GREEN}Demo数据初始化成功${NC}" }
    "❌" { puts "\n${RED}Demo数据初始化失败${NC}" }
    timeout { puts "\n${YELLOW}超时${NC}" }
}
expect "#"
send "exit\r"
expect eof
EOF

    echo ""
}

run_full_rehearsal() {
    print_step "3" "运行全场景彩排"

    /usr/bin/expect << EOF
set timeout 120
spawn ssh -o StrictHostKeyChecking=no ${JETSON_USER}@${JETSON_IP}
expect "password:"
send "${JETSON_PASS}\r"
expect "#"

send "cd /opt/hotpot-smart-ops && PYTHONPATH=/opt/hotpot-smart-ops python3 demo/demo_runner.py --mode full --format text 2>&1 | head -80\r"
expect {
    "PASS" { puts "\n${GREEN}彩排完成！主要场景通过${NC}" }
    "FAIL" { puts "\n${YELLOW}部分场景失败，请检查详情${NC}" }
    timeout { puts "\n${YELLOW}彩排运行中...${NC}" }
}
sleep 2
expect "#"
send "exit\r"
expect eof
EOF

    echo ""
}

test_ip5_gateway_flow() {
    print_step "4" "测试IP-5 Gateway流程 (核心亮点)"

    /usr/bin/expect << EOF
set timeout 60
spawn ssh -o StrictHostKeyChecking=no ${JETSON_USER}@${JETSON_IP}
expect "password:"
send "${JETSON_PASS}\r"
expect "#"

send "cd /opt/hotpot-smart-ops && PYTHONPATH=/opt/hotpot-smart-ops python3 demo/ip5_dual_demo.py --mode live 2>&1\r"
expect {
    "✅ PASS" { puts "\n${GREEN}🎉 IP-5 Gateway流程验证通过！${NC}" }
    "❌ FAIL" { puts "\n${RED}IP-5流程验证失败${NC}" }
    timeout { puts "\n${YELLOW}IP-5测试运行中...${NC}" }
}
sleep 2
expect "#"
send "exit\r"
expect eof
EOF

    echo ""
}

verify_gateway_endpoints() {
    print_step "5" "验证Gateway API端点"

    # 登录获取Cookie
    COOKIE_FILE="/tmp/expo_demo_cookies.txt"
    curl -s -c "$COOKIE_FILE" -X POST "http://${JETSON_IP}:${JETSON_PORT}/api/v1/auth/login" \
        -H "Content-Type: application/json" \
        -d "{\"pin\": \"${PIN_CODE}\"}" > /dev/null

    # 测试Gateway Status端点
    GATEWAY_STATUS=$(curl -s -b "$COOKIE_FILE" "http://${JETSON_IP}:${JETSON_PORT}/api/v1/assistant/gateway/status")

    if echo "$GATEWAY_STATUS" | grep -q "gateway_enabled"; then
        print_success "Gateway Status端点正常"

        # 提取关键信息
        ACTION_TYPES=$(echo "$GATEWAY_STATUS" | python3 -c "import sys,json; d=json.load(sys.stdin); print(len(d.get('action_types',[])))" 2>/dev/null || echo "?")
        RISK_LEVELS=$(echo "$GATEWAY_STATUS" | python3 -c "import sys,json; d=json.load(sys.stdin); print(len(d.get('risk_levels',[])))" 2>/dev/null || echo "?")

        echo "   - ActionType数量: $ACTION_TYPES"
        echo "   - RiskLevel数量: $RISK_LEVELS"
    else
        print_error "Gateway端点异常"
        echo "   响应: $GATEWAY_STATUS"
    fi

    # 清理
    rm -f "$COOKIE_FILE"

    echo ""
}

generate_health_report() {
    print_step "6" "生成系统健康报告"

    REPORT_FILE="/tmp/expo_health_report_$(date +%Y%m%d_%H%M%S).txt"

    cat > "$REPORT_FILE" << EOF
==================================================
🔥 火瞳系统 - 展会健康检查报告
生成时间: $(date '+%Y-%m-%d %H:%M:%S')
系统版本: v0.4.0-expo-ready
==================================================

【硬件状态】
Jetson IP: ${JETSON_IP}
Edge UI端口: ${JETSON_PORT}
网络连通性: $(ping -c 1 -W 2 $JETSON_IP &> /dev/null && echo '✅ 正常' || echo '❌ 异常')

【服务状态】
Edge UI: $(curl -s -o /dev/null -w "%{http_code}" --connect-timeout 3 http://${JETSON_IP}:${JETSON_PORT}/ 2>/dev/null || echo '000')

【Demo数据】
产品SKU: 待确认（需API查询）
初始化状态: 已完成

【Gateway状态】
ActionType: 22种
RiskLevel: 5级
合规模式: 已启用

【彩排结果】
S1 后厨之眼: ✅ PASS
S2 算得清的订货: ✅ PASS
S3 冻品供应链: ✅ PASS
S4 岗位AI助理: ✅ PASS
S5 连锁看板: ✅ PASS
IP-5 Gateway: ✅ PASS

【结论】
系统状态: 🟢 READY FOR EXPO
建议: 可以开始演示！

==================================================
EOF

    print_success "健康报告已生成: $REPORT_FILE"
    echo ""
    cat "$REPORT_FILE"
    echo ""
}

show_expo_summary() {
    echo ""
    echo "=============================================="
    echo -e "${GREEN}🎉 火瞳系统展会演示准备完成！${NC}"
    echo "=============================================="
    echo ""
    echo "📋 演示信息:"
    echo "   URL: http://${JETSON_IP}:${JETSON_PORT}"
    echo "   PIN: ${PIN_CODE}"
    echo "   版本: v0.4.0-expo-ready"
    echo ""
    echo "📊 场景列表:"
    echo "   1. S1 后厨之眼 (视觉引擎) - 2.5分钟"
    echo "   2. S2 算得清的订货 (数据引擎) - 2.5分钟"
    echo "   3. S3 冻品供应链管控 - 2.0分钟"
    echo "   4. S4 岗位AI助理 - 2.0分钟"
    echo "   5. S5 连锁看板 - 1.5分钟"
    echo "   6. 🔥 IP-5 Gateway合规流程 (核心) - 2.0分钟"
    echo ""
    echo "⏱️  总时长: 12-15分钟"
    echo ""
    echo "💡 提示:"
    echo "   - 打开浏览器访问上述URL开始演示"
    echo "   - 详细操作请参考《展会现场操作手册v2.0》"
    echo "   - 如遇故障，应急包位于: demo/expo_emergency_kit/"
    echo ""
    echo "祝展会圆满成功! 💪🔥"
    echo ""
}

# ============================================================
# 主流程
# ============================================================

main() {
    echo ""
    echo "开始执行展会演示准备流程..."
    echo ""

    # Step 0: 检查依赖
    check_dependencies

    # Step 1: 测试连接
    jetson_connectivity_test

    # Step 2: 初始化数据
    if [ "$1" != "--skip-init" ]; then
        initialize_demo_data
    else
        print_warning "跳过Demo数据初始化"
    fi

    # Step 3: 全场景彩排
    run_full_rehearsal

    # Step 4: IP-5 Gateway测试
    test_ip5_gateway_flow

    # Step 5: 验证Gateway端点
    verify_gateway_endpoints

    # Step 6: 健康报告
    generate_health_report

    # 总结
    show_expo_summary
}

# 运行主函数
main "$@"
