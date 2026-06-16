# Phase 1 部署架构

**玉环 / 椒江试点 · 物理与软件拓扑**

| 项目 | 内容 |
|------|------|
| 版本 | V1.0 |
| 关联 | [solution.md §11](solution.md) · [pilot_deployment_checklist_direct.md](pilot_deployment_checklist_direct.md) |
| 更新 | 2026-06-15 |

---

## 1. 部署模式（Phase 1）

| 模式 | 场景 | 说明 |
|------|------|------|
| **A. PoC 单机** | 研发/评审演示 | `demo/run_poc.sh`，Hub+看板同机 |
| **B. docker-compose** | staging UAT | hub + dashboard + 可选 postgres/mqtt/vlm |
| **C. 现场边缘盒** | 试点生产 | RK3588 systemd + 区域 Hub VM |

Phase 1 试点目标：**B 验证 → C 上线**。

---

## 2. docker-compose 拓扑（staging）

```mermaid
flowchart LR
    subgraph host [试点/staging 主机]
        HUB[hub :8088]
        DASH[dashboard :3000]
        PG[(postgres :5432 profile)]
        MQTT[mosquitto :1883 profile]
        VLM[vlm :8089 profile]
    end
    DASH --> HUB
    HUB --> PG
    EDGE[边缘 RK3588] -->|HTTP| HUB
    EDGE -->|MQTT| MQTT
```

**启动**：

```bash
# 基础
docker compose up -d

# + PostgreSQL
docker compose --profile postgres up -d
export HOTPOT_DATABASE_URL=postgresql://hotpot:hotpot_dev@localhost:5432/hotpot_ops

# + MQTT（IoT 联调）
docker compose --profile iot up -d

# + VLM
docker compose --profile vlm up -d
```

---

## 3. 单店现场拓扑（模式 C）

```
                    [弱电间 / 机房]
                    ┌─────────────────┐
   POE交换机 ───────│  RK3588 边缘盒   │
   ├ 前厅摄像头×N   │  vision_worker  │
   ├ 后厨摄像头×N   │  mqtt_bridge    │
   └ 网关           │  offline_queue  │
                    └────────┬────────┘
                             │ 有线/4G
                    ┌────────▼────────┐
                    │ 区域 Hub VM      │
                    │  event_hub :8088 │
                    │  postgres        │
                    └────────┬────────┘
                             │
              ┌──────────────┼──────────────┐
              │              │              │
         [看板浏览器]    [企微 webhook]   [POS/ERP]
```

| 设备 | 数量/店 | 接入 |
|------|---------|------|
| RK3588 16G | 1 | systemd 守护 |
| POE 摄像头 | 4~8+4~6 | RTSP → edge |
| MQTT 网关 | 1 | 温湿度/门磁/秤 |
| 收货秤 | 1 | MQTT/串口 |
| 探针/门磁 | 若干 | MQTT |

---

## 4. systemd 服务（边缘 + Hub）

| 单元 | 路径 | 说明 |
|------|------|------|
| `hotpot-hub.service` | `deploy/systemd/` | Hub 守护 |
| `hotpot-dashboard.service` | 同上 | 看板 |
| `hotpot-vision@.service` | 同上 | 每店 vision_worker |
| `hotpot-erp@.service` | 同上 | ERP 周期同步 |
| `hotpot-pos@.service` | 同上 | POS sim/webhook |

```bash
# 健康检查
python3 scripts/edge_health.py --store-id store_yuhuan --hub-url http://127.0.0.1:8088
```

---

## 5. 网络与端口

| 端口 | 服务 | 暴露 |
|------|------|------|
| 8088 | Event Hub | 内网/ VPN |
| 3000 | 看板 | 内网 |
| 8089 | VLM | 内网 |
| 5432 | PostgreSQL | 仅 Hub 可达 |
| 1883 | MQTT | 店内局域网 |
| 443 | HTTPS 反代 | staging 对外 |

防火墙：RTSP 内网、出站 443（企微/LLM API）。

---

## 6. 两店配置差异

| 项 | 玉环 store_yuhuan | 椒江 store_jiaojiang |
|----|-------------------|----------------------|
| store_id | store_yuhuan | store_jiaojiang |
| 桌数 | seed 配置 | seed 配置 |
| ROI | DEV-408 标定 | DEV-408 标定 |
| MQTT topic | `store/yuhuan/sensors/#` | `store/jiaojiang/sensors/#` |
| hub_url | 区域 Hub 同一实例 | 同左，tenant 隔离 |

数据目录：`demo/data/stores/<store_id>/` → 生产迁移至 `/var/lib/hotpot/stores/`。

---

## 7. 环境变量

| 变量 | 说明 | 示例 |
|------|------|------|
| `HOTPOT_DATABASE_URL` | PG 连接串 | `postgresql://hotpot:***@localhost:5432/hotpot_ops` |
| `HOTPOT_AUTH_MODE` | demo / strict | `demo` |
| `HOTPOT_WECHAT_WEBHOOK` | 企微机器人 | `https://qyapi.weixin.qq.com/...` |
| `HOTPOT_PUSH_WARN` | warn 是否推手机 | `0` |
| `HOTPOT_DETECTOR_BACKEND` | mock/yolo/rknn | `yolo` |
| `HOTPOT_RTSP_ENABLED` | 启用 RTSP | `1` |

模板：`deploy/.env.postgres.example`

---

## 8. 部署检查清单（架构视角）

| # | 项 | staging | 现场 |
|---|-----|:-------:|:----:|
| 1 | Hub `/health` ok | ☐ | ☐ |
| 2 | 看板登录 JWT | ☐ | ☐ |
| 3 | vision_worker 5s 周期 | ☐ | ☐ |
| 4 | postgres profile 24h | ☐ | ☐ |
| 5 | MQTT 传感器读数入 Hub | ☐ | ☐ |
| 6 | 企微 webhook 测试 | ☐ | ☐ |
| 7 | systemd 崩溃自启 | ☐ | ☐ |
| 8 | 4G/外网备份（可选） | — | ☐ |

---

## 9. 与 DEV 任务映射

| 部署项 | DEV |
|--------|-----|
| 边缘镜像一键刷机 | DEV-404 |
| 两店 UAT 配置包 | DEV-407 |
| HTTPS staging | DEV-103 |
| Prometheus 监控 | DEV-405 |
| 现场施工 | IMP-401 |
