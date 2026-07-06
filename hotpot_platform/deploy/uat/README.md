# UAT 配置包（Phase 1 · 玉环 + 椒江）

**DEV-407** · 每店一份 edge config + MQTT topic + ROI 标定

| 门店 | store_id | 配置目录 |
|------|----------|----------|
| 玉环店 | `store_yuhuan` | [store_yuhuan/](store_yuhuan/) |
| 椒江店 | `store_jiaojiang` | [store_jiaojiang/](store_jiaojiang/) |

## 文件说明

| 文件 | 用途 |
|------|------|
| `config.json` | 边缘盒主配置（Hub URL、摄像头、IoT、模型版本） |
| `mqtt_topics.json` | MQTT topic 与传感器映射 |
| `roi_tables.json` | 前厅桌位 ROI 标定（8 桌） |
| `accounts.json` | 看板/PDA 演示账号（PoC 用，生产换 JWT） |
| `alert.json` | 企微 webhook 路由（DEV-414） |

## 企微 Webhook（DEV-414 · BL-03）

店级配置优先级：`alert.json` 内 `webhook_url` → 店级 env → 全局 `HOTPOT_WECHAT_WEBHOOK`。

| 门店 | 环境变量 |
|------|----------|
| 玉环 | `HOTPOT_WECHAT_WEBHOOK_STORE_YUHUAN` |
| 椒江 | `HOTPOT_WECHAT_WEBHOOK_STORE_JIAOJIANG` |
| 全局兜底 | `HOTPOT_WECHAT_WEBHOOK` |

```bash
# 1. 配置（见 deploy/.env.wechat.example）
export HOTPOT_WECHAT_WEBHOOK_STORE_YUHUAN='https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=...'

# 2. 检查路由状态
curl -s 'http://127.0.0.1:8088/alerts/routes?store_id=store_yuhuan' | python3 -m json.tool

# 3. 发送测试卡片（店长手机应收到）
python3 scripts/send_test_wechat_alert.py --store-id store_yuhuan

# 4. SLA 探针（critical 30s 内送达）
python3 scripts/test_wechat_push_sla.py --store-id store_yuhuan
```

warn 级默认不推手机；开启：`export HOTPOT_PUSH_WARN=1`

## 鉴权（DEV-102）

| 通道 | 方式 | 说明 |
|------|------|------|
| 看板/PDA | `POST /auth/token` → JWT | 登录页自动换取 Bearer Token |
| 边缘盒 | `X-Api-Key` | 见各店 `config.json` 的 `edge_api_key` |
| 演示模式 | `HOTPOT_ENV=dev` + `HOTPOT_AUTH_MODE=demo` | 读接口可匿名，仅本机/概念演示 |
| 生产/试点模式 | `HOTPOT_ENV=pilot` + `HOTPOT_AUTH_MODE=strict` | 全部接口需 JWT 或 API Key；启动时强制校验 PG、CORS、JWT secret、edge keys |

边缘 API Key（演示，pilot+ 必须用 `HOTPOT_EDGE_API_KEYS` 替换）：
- 玉环：`edge_yuhuan_dev_key`
- 椒江：`edge_jiaojiang_dev_key`

## 视觉边缘（DEV-203 · 模拟流，无需真实摄像头）

UAT 配置中 `stream_mode: "file"` 使用演示图片；`rtsp` 字段保留供上线时切换。

```bash
# 单店视觉 worker（UAT ROI + 文件源 + 离线队列）
python3 edge/stream/vision_worker.py \
  --store-id store_yuhuan \
  --hub-url http://127.0.0.1:8088 \
  --output-dir demo/data/stores/store_yuhuan/live

# Hub 恢复后自动 flush 队列（worker 启动时默认执行）
```

离线队列 SQLite：`demo/data/stores/<store_id>/edge_queue.db`

## 部署检查

```bash
# 验证配置 JSON 合法
python3 -m json.tool deploy/uat/store_yuhuan/config.json
python3 -m json.tool deploy/uat/store_jiaojiang/config.json

# Hub 灌库后验证租户
curl "http://127.0.0.1:8088/benchmark"
```

## 关联

- [试点清单](../docs/pilot_deployment_checklist.md)
- [设计·开发·实施 §1.3.2](../docs/design_dev_implementation_plan.md)
