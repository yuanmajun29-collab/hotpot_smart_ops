# Edge UI 运维操作手册 v1.0

> **版本**: v1.0
> **日期**: 2026-08-01
> **适用环境**: 椒江店 Jetson + 腾讯云 Dashboard
> **目标读者**: 门店运维人员 / 开发者

---

## 1. 环境概览

### 1.1 部署拓扑

```
┌─────────────────────────────────────────────────────┐
│                   互联网 (公网)                      │
└──────────────────────┬──────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────┐
│              腾讯云服务器 (43.139.143.12)            │
│              ───────────────────────               │
│  ┌─────────────────────────────────────────┐       │
│  │  平台端 Dashboard (:8098)                │       │
│  │  - 多门店数据汇总                        │       │
│  │  - 用户管理 / 权限控制                    │       │
│  │  - 数据可视化大屏                        │       │
│  └─────────────────────────────────────────┘       │
└──────────────────────┬──────────────────────────────┘
                       │ VPN / 内网穿透
                       ▼
┌─────────────────────────────────────────────────────┐
│           椒江店内网 (192.168.x.x)                  │
│  ┌─────────────────────────────────────────┐       │
│  │  Jetson Edge Box (172.16.1.60)          │       │
│  │  ─────────────────────────────          │       │
│  │  Edge UI (:9080) ← L2 PIN认证           │       │
│  │    - 货品主数据管理                     │       │
│  │    - 收货质检 (VLM)                     │       │
│  │    - SOP合规检查                        │       │
│  │    - AI知识问答                         │       │
│  │                                        │       │
│  │  Demo Web UI (:8080)                    │       │
│  │    - 5大场景展示页                       │       │
│  │    - 展会演示专用                        │       │
│  │                                        │       │
│  │  海康NVR (192.168.6.21)                │       │
│  │    - HTTP抓拍 ✅                        │       │
│  │    - RTSP ❌ (554端口关闭)              │       │
│  └─────────────────────────────────────────┘       │
└─────────────────────────────────────────────────────┘
```

### 1.2 端口分配

| 服务 | 端口 | 协议 | 访问范围 | 用途 |
|------|------|------|----------|------|
| Edge UI API | 9080 | HTTP | 局域内网 | 主业务接口 |
| Demo Web UI | 8080 | HTTP | 局域内网 | 展示页面 |
| 平台Dashboard | 8098 | HTTP | 公网可访问 | 云端管理 |
| SSH | 22 | TCP | 局域内网 | 远程管理 |
| 向日葵VNC | - | TCP | 公网可访问 | 远程桌面 |

### 1.3 服务依赖关系

```
Edge UI (:9080)
  ├── Python 3.9.5
  ├── FastAPI + Uvicorn
  ├── Pydantic 2.x
  ├── supply_chain (models.py, manager.py)
  └── data/product_master.json (持久化)

Demo Web (:8080)
  ├── Python http.server (静态文件)
  └── demo/web/ (HTML/CSS/JS)

平台Dashboard (:8098)
  ├── Python 3.x (OpenCloudOS)
  ├── FastAPI + Uvicorn
  └── hotpot_platform/dashboard/
```

---

## 2. 日常操作

### 2.1 启动服务

#### 方式一：一键启动脚本（推荐）

```bash
# SSH到Jetson
ssh root@172.16.1.60

# 执行一键启动脚本
cd /opt/hotpot-smart-ops
bash deploy/edge/start-all.sh
```

**start-all.sh 功能**:
- 检查端口占用
- 启动 Edge UI (:9080)
- 启动 Demo Web (:8080)
- 健康检查
- 输出访问地址

#### 方式二：手动启动 Edge UI

```bash
# 进入项目目录
cd /opt/hotpot-smart-ops

# 启动Edge UI (前台运行，日志直接输出)
no_proxy='*' python3 -m edge.edge-ui.main

# 或后台运行
nohup no_proxy='*' python3 -m edge.edge-ui.main > /var/log/hotpot/edge-ui.log 2>&1 &

# 验证启动成功
sleep 3
curl --noproxy '*' http://127.0.0.1:9080/api/v1/ping
# 预期返回: {"status": "ok", "version": "..."}
```

#### 方式三：启动 Demo Web UI

```bash
# 启动Demo静态文件服务器
cd /opt/hotpot-smart-ops
no_proxy='*' python3 demo/web/server.py &

# 访问: http://172.16.1.60:8080
```

#### 快捷启动别名（已配置）

```bash
# 使用便捷脚本
bash start-expo.sh        # 启动Demo展示
bash start-edge-ui.sh     # 启动Edge UI管理界面
```

---

### 2.2 停止服务

```bash
# 查找占用端口的进程
lsof -i :9080 -t

# 停止Edge UI
kill $(lsof -i :9080 -t)

# 强制停止（如果普通kill无效）
kill -9 $(lsof -i :9080 -t)

# 停止所有Python服务
pkill -f "edge.edge-ui.main"
pkill -f "demo/web/server"
```

---

### 2.3 重启服务

```bash
# 完整重启流程
cd /opt/hotpot-smart-ops

# 1. 停止旧进程
pkill -f "edge.edge-ui.main" || true
sleep 2

# 2. 确认端口释放
lsof -i :9080 || echo "Port 9080 is free"

# 3. 启动新进程
nohup no_proxy='*' python3 -m edge.edge-ui.main > /var/log/hotpot/edge-ui.log 2>&1 &

# 4. 验证
sleep 3
curl --noproxy '*' http://127.0.0.1:9080/api/v1/ping
```

---

### 2.4 服务健康检查

#### 快速检查命令

```bash
#!/bin/bash
# health_check.sh — Edge UI 健康检查

HOST="127.0.0.1:9080"
PASS=0
FAIL=0

check() {
  local name="$1" url="$2" expected="$3"
  local code=$(curl -s --noproxy '*' -o /dev/null -w "%{http_code}" "http://$HOST$url")
  if [ "$code" = "$expected" ]; then
    echo "✅ $name ($code)"
    PASS=$((PASS+1))
  else
    echo "❌ $name (expected:$expected actual:$code)"
    FAIL=$((FAIL+1))
  fi
}

echo "=== Edge UI Health Check ==="
echo "Time: $(date '+%Y-%m-%d %H:%M:%S')"
echo ""

check "Ping" "/api/v1/ping" "200"
check "Stats" "/api/v1/products/stats" "200"
check "Categories" "/api/v1/categories" "200"
check "Frontend" "/products.html" "200"

echo ""
echo "Result: $PASS passed, $FAIL failed"
exit $FAIL
```

**执行**:
```bash
bash health_check.sh
```

**预期输出**:
```
=== Edge UI Health Check ===
Time: 2026-08-01 16:30:00

✅ Ping (200)
✅ Stats (200)
✅ Categories (200)
✅ Frontend (200)

Result: 4 passed, 0 failed
```

---

## 3. 备份策略

### 3.1 数据备份

#### 备份内容

| 数据 | 路径 | 重要性 | 备份频率 |
|------|------|--------|----------|
| 货品主数据 | `edge/edge-ui/data/product_master.json` | 🔴 高 | 每日 |
| 配置文件 | `edge/common/config/*.yml` | 🟡 中 | 变更时 |
| 日志文件 | `/var/log/hotpot/*.log` | 🟢 低 | 每周（轮转） |

#### 手动备份脚本

```bash
#!/bin/bash
# backup_data.sh — 数据备份

BACKUP_DIR="/opt/hotpot-smart-ops/backups/$(date +%Y%m%d_%H%M%S)"
mkdir -p "$BACKUP_DIR"

echo "Backing up to $BACKUP_DIR..."

# 1. 货品主数据
cp -a edge/edge-ui/data/product_master.json "$BACKUP_DIR/"
echo "✅ product_master.json"

# 2. 配置文件
mkdir -p "$BACKUP_DIR/config"
cp -a edge/common/config/*.yml "$BACKUP_DIR/config/"
echo "✅ config files"

# 3. 压缩备份
tar -czf "$BACKUP_DIR.tar.gz" -C "$(dirname $BACKUP_DIR)" "$(basename $BACKUP_DIR)"
rm -rf "$BACKUP_DIR"
echo "✅ Compressed: $BACKUP_DIR.tar.gz"

# 4. 清理7天前的备份
find /opt/hotpot-smart-ops/backups/ -mtime +7 -name "*.tar.gz" -delete
echo "🧹 Cleaned old backups (>7 days)"

echo "Done! Backup: $BACKUP_DIR.tar.gz"
```

**定时备份 (crontab)**:

```bash
# 编辑定时任务
crontab -e

# 添加每日凌晨3点备份
0 3 * * * /opt/hotpot-smart-ops/deploy/edge/backup_data.sh >> /var/log/hotpot/backup.log 2>&1
```

### 3.2 配置备份

```bash
# 导出全部配置
tar -czf config_backup_$(date +%Y%m%d).tar.gz \
  edge/common/config/ \
  deploy/edge/start-all.sh

# 恢复配置
tar -xzvf config_backup_YYYYMMDD.tar.gz -C /
```

---

## 4. 监控指标

### 4.1 关键指标

| 指标 | 正常值 | 告警阈值 | 检查方式 |
|------|--------|----------|----------|
| **API响应时间(P50)** | <200ms | >500ms | curl -w "%{time_total}" |
| **API可用性** | 100% | <99% | 健康检查脚本 |
| **内存使用率** | <70% | >85% | `free -m` |
| **磁盘使用率** | <80% | >95% | `df -h` |
| **进程状态** | Running | Zombie/Stopped | `ps aux \| grep` |
| **数据文件大小** | <10MB | >50MB | `ls -lh data/` |

### 4.2 监控命令

```bash
#!/bin/bash
# monitor.sh — 系统监控

echo "=== System Monitor ==="
echo "Time: $(date)"
echo ""

# 1. CPU和内存
echo "--- CPU & Memory ---"
free -h
echo ""
top -bn1 | head -5

# 2. 磁盘空间
echo "--- Disk Usage ---"
df -h / /opt

# 3. Edge UI 进程
echo "--- Edge UI Process ---"
ps aux | grep "edge.edge-ui" | grep -v grep

# 4. 端口监听
echo "--- Listening Ports ---"
ss -tlnp | grep -E "9080|8080"

# 5. 最近日志错误
echo "--- Recent Errors ---"
tail -20 /var/log/hotpot/edge-ui.log 2>/dev/null | grep -i "error\|exception\|traceback" || echo "No recent errors"

# 6. API响应时间测试
echo "--- API Latency ---"
for i in {1..5}; do
  time=$(curl -s --noproxy '*' -o /dev/null -w "%{time_total}" http://127.0.0.1:9080/api/v1/ping)
  echo "  Request $i: ${time}s"
done
```

### 4.3 日志查看

```bash
# 实时查看日志
tail -f /var/log/hotpot/edge-ui.log

# 查看最近100行
tail -100 /var/log/hotpot/edge-ui.log

# 只看错误日志
grep -i "error\|exception" /var/log/hotpot/edge-ui.log | tail -20

# 按日期筛选
grep "2026-08-01" /var/log/hotpot/edge-ui.log
```

**日志格式**:
```
[2026-08-01 16:30:00] INFO     [edge.edge-ui.main] Edge UI v1.1 starting on port 9080
[2026-08-01 16:30:01] INFO     [edge.edge-ui.product_master_api] 货品模块已初始化: 23 products
[2026-08-01 16:30:05] WARNING  [supply_chain.manager] SKU重复警告: FP-TEST-001
[2026-08-01 16:30:10] ERROR    [supply_chain.manager] JSON保存失败: Permission denied
```

---

## 5. 故障排查指南

### 5.1 常见问题

#### 问题1: 服务无法启动

**症状**: 执行启动命令后无响应或报错

**排查步骤**:
```bash
# 1. 检查端口是否被占用
lsof -i :9080
# 如果有输出，说明端口被占用 → 先 kill 再启动

# 2. 手动运行查看详细报错
python3 -m edge.edge-ui.main
# 观察终端输出的错误信息

# 3. 检查Python依赖
python3 -c "from fastapi import FastAPI; from pydantic import BaseModel; print('OK')"
# 如果报错 → pip install 缺失的包

# 4. 检查文件权限
ls -la edge/edge-ui/data/
# 确保 data 目录可写
chmod 755 edge/edge-ui/data/
```

**常见原因及解决**:

| 原因 | 解决方法 |
|------|----------|
| 端口被占用 | `kill $(lsof -i :9080 -t)` |
| 依赖缺失 | `pip install fastapi uvicorn pydantic` |
| 权限不足 | `chmod 755 data/` 或 `sudo` 运行 |
| JSON数据损坏 | 删除 `data/product_master.json` 重启(会重新初始化空库) |

---

#### 问题2: API返回500错误

**症状**: 浏览器/Postman调用API返回500 Internal Server Error

**排查步骤**:
```bash
# 1. 查看服务端日志
tail -50 /var/log/hotpot/edge-ui.log | grep -A5 "ERROR\|Traceback"

# 2. 直接用curl测试获取详细错误
curl -v --noproxy '*' http://127.0.0.1:9080/api/v1/products/stats

# 3. 检查数据文件完整性
python3 -c "
import json
with open('edge/edge-ui/data/product_master.json') as f:
    d = json.load(f)
print('Products:', len(d.get('products', {})))
print('Categories:', len(d.get('categories', [])))
"

# 4. 检查模型导入
python3 -c "from hotpot_platform.cloud.supply_chain.models import ProductMaster; print('OK')"
```

---

#### 问题3: 登录失败（PIN码错误）

**症状**: 输入正确PIN但仍提示认证失败

**排查步骤**:
```bash
# 1. 确认默认PIN码
# 当前默认: 123456 (6位数字)

# 2. 检查Session存储
ls -la /tmp/edge_sessions/
# Session文件是否存在

# 3. 清除过期Session后重试
rm -f /tmp/edge_sessions/*
# 重启服务
pkill -f "edge.edge-ui.main"
sleep 2
python3 -m edge.edge-ui.main
```

---

#### 问题4: 页面加载慢或超时

**症状**: 浏览器访问 :9080 或 :8080 很慢

**排查步骤**:
```bash
# 1. 检查网络连通性
ping 172.16.1.60

# 2. 检查系统资源
top -bn1 | head -5
# 如果CPU或内存使用率高 → 可能是推理任务占用

# 3. 检查是否有大量请求
ss -tn | grep ":9080" | wc -l
# 如果连接数异常 → 可能有循环请求

# 4. 检查磁盘IO
iostat -x 1 3
# 如果await高 → 磁盘瓶颈
```

---

#### 问题5: 数据丢失或损坏

**症状**: 货品数据为空或格式错误

**排查步骤**:
```bash
# 1. 检查数据文件是否存在
ls -lh edge/edge-ui/data/product_master.json

# 2. 验证JSON格式
python3 -c "
import json
try:
    with open('edge/edge-ui/data/product_master.json') as f:
        json.load(f)
    print('✅ JSON format valid')
except Exception as e:
    print('❌ JSON error:', e)
"

# 3. 从备份恢复
ls -lt /opt/hotpot-smart-ops/backups/ | head -5
# 找到最近的备份文件恢复
cp /opt/hotpot-smart-ops/backups/YYYYMMDD_HHMMSS/product_master.json edge/edge-ui/data/

# 4. 重启服务使恢复生效
pkill -f "edge.edge-ui.main"
sleep 2
python3 -m edge.edge-ui.main
```

---

### 5.2 应急处理流程

```
发现问题
    │
    ▼
┌─────────────────┐
│ 影响用户使用?   │
└────┬──────────┘
     │
   Yes│         No│
     ▼           ▼
重启服务    记录日志
     │           │
     ▼           ▼
问题解决?   定期排查
     │
   Yes└─→ No┘
     │
     ▼
 回滚到备份
     │
     ▼
 通知开发团队
```

---

## 6. 安全注意事项

### 6.1 访问控制

| 措施 | 说明 |
|------|------|
| L2 PIN认证 | 所有API需要6位数字PIN |
| 内网限制 | Edge UI仅暴露在内网(:9080)，不对外 |
| 向日葵远程 | 需要密码+验证码双重验证 |
| SSH密钥登录 | 禁用密码登录（生产环境） |

### 6.2 敏感信息管理

| 信息类型 | 存储位置 | 保护措施 |
|----------|----------|----------|
| PIN码 | 代码硬编码 | 🔴 迁移到环境变量或配置文件 |
| Session ID | 服务端文件(/tmp/) | 自动过期(2小时) |
| 供应商联系方式 | product_master.json | 仅内网可访问 |
| NVR密码 | ipc_config.yml | 文件权限600 |

### 6.3 安全加固建议

```bash
# 1. 修改默认PIN码
# 编辑 edge/edge-ui/auth_config.py (待实现)

# 2. 限制SSH访问
# 编辑 /etc/ssh/sshd_config
# AllowUsers root@特定IP

# 3. 设置防火墙规则
iptables -A INPUT -p tcp --dport 9080 -s 192.168.0.0/16 -j ACCEPT
iptables -A INPUT -p tcp --dport 9080 -j DROP

# 4. 定期更新系统包
apt update && apt upgrade -y
```

---

## 7. 版本与更新

### 7.1 当前版本

| 组件 | 版本 | 最后更新 | Commit |
|------|------|----------|--------|
| Edge UI | v1.1 | 2026-08-01 | `48ad0bd` |
| 货品主数据模块 | v1.0 | 2026-08-01 | `52b089b` |
| Python | 3.9.5 | 安装时 | - |
| FastAPI | 0.x | 安装时 | - |
| Pydantic | 2.13.x | 安装时 | - |

### 7.2 更新流程

```bash
# 从GitHub拉取最新代码
cd /opt/hotpot-smart-ops
git pull origin feature/d1-expo-sprint

# 备份数据
bash deploy/edge/backup_data.sh

# 重启服务
pkill -f "edge.edge-ui.main"
sleep 2
no_proxy='*' python3 -m edge.edge-ui.main &

# 验证更新
curl --noproxy '*' http://127.0.0.1:9080/api/v1/ping
```

---

> **下次更新**: D1-S02 开发完成后补充 VLM 相关运维内容。
