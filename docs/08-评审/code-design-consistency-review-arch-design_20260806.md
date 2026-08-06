# 火瞳 hotpot_smart_ops · 代码与设计一致性审查报告

> **审查分支**：`feature/arch-design`（最新提交 `e654f6a`）  
> **审查日期**：2026-08-06  
> **对照基线**：
> - `docs/04-技术设计/PRD_V5_3i_CODE_ALIGNMENT.md`（v5.3i-rev1，基于 `feature/d1-expo-sprint @467253b`）
> - `docs/01-核心权威/火瞳_详细架构设计_v1.0.md`（v1.6）
> - 实际代码路径：`edge/kitchen/inference/`、`edge/front_hall/inference/`、`hotpot_platform/cloud/`、`edge/edge-ui/`、`tests/`、`deploy/`

---

## 一、总体评估

| 维度 | 评估 | 说明 |
|------|:----:|------|
| PRD功能代码覆盖率 | ⚠️ 32-36% | 对齐表声明 36.3%（基于 `d1-expo-sprint`），本分支偏低 |
| 模块间接口一致性 | ⚠️ 中 | 存在端口分裂、接口名不匹配等多个问题 |
| 数据库 Schema 一致性 | ⚠️ 中 | 仅 SQLite DDL，PG 版未覆盖；架构文档引用部分代码路径不存在 |
| 测试覆盖率 | ⚠️ 不均衡 | 700+ 测试函数但核心推理路径覆盖极薄 |
| 部署脚本可执行性 | ❌ 低 | 硬编码 IP/分支，端口不一致，本地不可验证 |
| 配置路径/端口一致性 | ❌ 低 | Hub 端口 8088 vs 8098 分裂，多处路径引用不一致 |

---

## 二、代码-设计偏差清单

### 2.1 对齐表与分支不匹配（P0）

| 问题 | 详细 |
|------|------|
| **对齐表基线不同** | 对齐表基于 `feature/d1-expo-sprint @467253b` 审计，本审查分支是 `feature/arch-design @e654f6a`，对齐表覆盖率数据不可直接套用 |
| **架构文档版本偏差** | 详细架构设计 v1.6 引用的功能 ID 编号（如 K03=剩余率估算、K05=加汤提醒）与对齐表（K01=后厨废料、K05=翻台率分析）完全不同，是两套编号体系 |

### 2.2 桩文件 / 空壳函数（P1）

| 文件 | 行数 | 问题 |
|------|:----:|------|
| `hotpot_platform/cloud/event_hub/routers/analytics.py` | 3 行 | 仅桥接导入，无实际路由逻辑 |
| `hotpot_platform/cloud/vlm_review/server.py` | 内含 | `legacy rule stub` 模式 |
| `hotpot_platform/cloud/event_hub/org_registry.py` | 内含 | 明确标注 "Phase 2 stub · DEV-501" |
| `hotpot_platform/cloud/event_hub/iot_readings_store.py` | 内含 | 标注 "DEV-412 stub / BL-02" |
| `hotpot_platform/cloud/event_hub/device_stub.py` | 内含 | 全量 stub 注入，无真实硬件数据通路 |
| `hotpot_platform/cloud/event_hub/routers/cost.py` | 255 行 | 自述为 "minimal stub" |

### 2.3 TODO 标记未完成功能（P1）

全仓 58 处 TODO/FIXME/stub/placeholder，集中在：

| 位置 | 数量 | 典型问题 |
|------|:----:|----------|
| `supply_chain.py` | 12 | 大量 `# TODO: PG SELECT/INSERT/UPDATE` — 采购闭环未接入 PG |
| `purchase_cycle.py` | 5 | `# TODO Phase 2` — 审批任务和收货记录未持久化 |
| `warehouse/iot_monitor.py` | 1 | `# TODO: 从 iot_thresholds 表查询自定义配置` |
| `rfid_tracker.py` | 1 | `# TODO: 当 EPC 级别追踪表就位后改为精确查询` |
| `inventory_book.py` | 1 | `in_transit_qty=0.0 # TODO: 后续从 transfer 事件追踪在途` |
| `middleware/gateway.py` | 1 | `# TODO: 实现 PG 批量插入` |

### 2.4 未提交变更（P2）

| 文件 | 状态 | 影响 |
|------|:----:|------|
| `edge/common/scoreboard.py` | 新增（untracked） | 记分牌模块：YOLO+VLM 交叉验证，被 `kitchen/pipeline.py` 引用但未合入 |
| `edge/kitchen/inference/pipeline.py` | 已修改 | 引入了 Scoreboard 调用，依赖未提交的 scoreboard.py |

---

## 三、模块间接口不一致

### 3.1 端口分裂（P0）

| 服务 | 架构设计(v1.6) | docker-compose.yml | deploy_cloud.sh | watchdog.sh | Edge Agent config |
|------|:-------------:|:-----------------:|:--------------:|:-----------:|:-----------------:|
| **Event Hub** | **8088** | **8088** | **8098** | 8098 | 8098 |
| Edge Agent | 9100 | 9100 | — | 9100 | 9100 |
| Edge UI | — | — | — | — | 9080 |
| Dashboard | 3000 | 3000 | — | — | — |
| VLM Review | 8089 | 8089 | — | 8084 | 8080 |
| Demo Web UI | — | — | — | — | 8080 |

**核心冲突**：Hub 端口在架构设计/docker-compose 中为 **8088**，但在实际部署脚本和边缘设备通信中为 **8098**。这是分裂性不一致。

### 3.2 路径引用不一致（P1）

| 组件 | 硬编码路径 | 问题 |
|------|-----------|------|
| `edge/agent/config.py` | `HUB_URL = http://192.168.2.85:8098` | 硬编码内网 IP |
| `deploy/jetson/docker-compose.yml` | `HUB_URL = http://192.168.2.85:8098` | 同上 |
| `deploy/deploy_cloud.sh` | `CLOUD_HOST=43.139.143.12` | 硬编码云服务器 IP |
| `deploy/deploy-hotpot.sh` | `JETSON_HOST=192.168.2.240` | 硬编码盒子 IP |
| `deploy/watchdog.sh` | `ALERT_URL=http://192.168.2.85:7890` | 硬编码 Mac 告警回调 |
| `edge/agent/config.py` | `LLAMA_MODEL=/opt/hotpot-infer/models/ostrakon-vl-8b/...` | 硬编码模型路径 |
| `deploy/cloud/docker-compose.yml` | `command: python hotpot_platform/cloud/event_hub/server.py --port 8088` | server.py 入口可能不存在（实际用 app.py） |

### 3.3 架构设计 §8 映射表中的幽灵文件（P1）

架构设计 §8 PRD→代码全映射表引用了以下代码位置，但实际**文件不存在**：

| 声称位置 | 实际状态 |
|----------|----------|
| `member/recognizer.py` | ❌ 不存在 |
| `member/service.py` | ❌ 不存在 |
| `member/loyalty.py` | ❌ 不存在 |
| `member/marketing.py` | ❌ 不存在 |
| `data_engine/inventory_transfer.py` | ❌ 不存在 |
| `data_engine/location_mgr.py` | ❌ 不存在 |
| `data_engine/dish_recommender.py` | ❌ 不存在 |
| `event_hub/routers/staff_behavior.py` | ❌ 不存在 |
| `event_hub/routers/turnover.py` | ❌ 不存在（实际在 domain/turnover.py） |
| `event_hub/routers/waste_trend.py` | ❌ 不存在 |
| `event_hub/core/task_router.py` | ❌ 不存在 |

### 3.4 CLI 入口不一致

- `CLAUDE.md` 说启动命令：`python3 -m uvicorn edge.agent.server:app --port 9100`
- `deploy/edge/start-all.sh` 说：`python3 -m edge.agent.server --port 9100`（server.py 主入口不支持 --port CLI 参数，使用 uvicorn.run 硬编码）

---

## 四、数据库 Schema 与数据字典一致性

### 4.1 Schema 定义缺口（P0）

| 项目 | 状态 |
|------|:----:|
| `data_engine_schema.py` | ✅ 6 张表（sales_daily, inventory_ledger, inventory_snapshot, sales_forecast, order_suggestion, +1）— 仅 SQLite |
| `audit_schema.sql`（5 表） | ✅ purchase_suggestions, approval_tasks, purchase_orders, receiving_records, audit_events |
| **PG 版 Schema** | ❌ 不存在 —— 所有 DDL 均为 SQLite，无 PG migration 脚本 |
| **架构设计 §2 核心表 DDL** | ⚠️ 设计文档中有完整 DDL，但与 `data_engine_schema.py` 字段存在差异 |

### 4.2 数据字典不一致

| 架构设计 §8 声称的表 | 实际 SQLite DDL 表名 | 状态 |
|------|------|:----:|
| `supplier_scorecard` | 不存在 | ❌ |
| `receiving_batches` | 不存在（用 receiving_records 替代） | ⚠️ |
| `sop_templates` | 不存在 | ❌ |
| `sop_violations` | 不存在 | ❌ |
| `knowledge_base` | 不存在 | ❌ |
| `members` | 不存在 | ❌ |
| `points_transactions` | 不存在 | ❌ |

---

## 五、测试覆盖率和关键路径测试

### 5.1 测试规模

- **66 个测试文件**，约 **700+ 测试函数**（grep "def test_" 统计）
- 测试框架：pytest，配置在 `pytest.ini`（仅 `testpaths = tests`，无 marker/fixture 配置）
- conftest.py 使用 MagicMock mock 了 YOLO detector 和 sources

### 5.2 覆盖率极度不均衡

| 测试领域 | 测试函数数 | 评价 |
|----------|:----------:|------|
| alert_fatigue（告警疲劳） | 80 | ⚠️ 过度覆盖 |
| edge_events（边缘事件） | 75 | ⚠️ 过度覆盖 |
| edge_ui_apis（UI API） | 60 | ✅ 适中 |
| message_bus（消息总线） | 57 | ⚠️ 过度覆盖 |
| frame_evidence（帧证据） | 51 | ⚠️ 过度覆盖 |
| agent_gateway（Agent 网关） | 30 | ✅ 适中 |
| **kitchen_yolo（后厨 YOLO 推理）** | **7** | ❌ 严重不足 |
| **vlm_api（VLM API）** | **4** | ❌ 严重不足 |
| **analytics（分析）** | **4** | ❌ 严重不足 |
| **turnover（翻台率）** | **3** | ❌ 严重不足 |
| **scene_analyzer（前厅场景分析）** | **0** | ❌ 无测试 |
| **soup_detector（加汤检测）** | **0** | ❌ 无测试 |
| **data_engine（数据引擎 N01-N06）** | **0** | ❌ 无专测 |

### 5.3 关键路径测试缺口

| 关键路径 | 测试状态 | 影响 |
|----------|:--------:|------|
| 后厨 YOLO→VLM 三级过滤管线 | 🔴 仅 7 个测试 | 核心推理路径几乎未覆盖 |
| 前厅桌态识别→翻台分析→清台任务闭环 | 🔴 间接测试 | vision_worker 无专测 |
| SOP 合规检测 | 🟡 有测试 | test_task1_2_sop_staff.py (9) |
| 冻品收货质检 | 🟡 有测试 | test_g3_s02_receiving_pg.py (18) |
| Agent Framework 消息总线 | 🟢 充足 | test_message_bus.py (57) |
| JWT/RBAC 认证 | 🟡 有测试 | test_p1b_auth_unified.py (28) |
| 采购闭环 (S01-S04) | 🟡 部分 | test_p0c_purchase_cycle.py (24) |

---

## 六、部署脚本可行性评估

### 6.1 部署脚本清单

| 脚本 | 路径 | 本地可执行 | 评估 |
|------|------|:----------:|------|
| `deploy_cloud.sh` | deploy/ | ❌ | 硬编码 IP `43.139.143.12`，分支 `feature/d1-expo-sprint` |
| `deploy-hotpot.sh` | deploy/ | ❌ | 硬编码 IP `192.168.2.240`，需 SSH 到 Jetson |
| `jetson/deploy.sh` | deploy/jetson/ | ❌ | 依赖远程 Docker 容器 |
| `bridge/bridge.sh` | deploy/bridge/ | ❌ | API key 为占位符 `edge_y...key`，依赖外部 VLM 二进制 |
| `watchdog.sh` | deploy/ | ❌ | 需在 Jetson 上运行 |
| `edge/start-all.sh` | deploy/edge/ | ❌ | 路径 `JETSON_DIR=/opt/hotpot-smart-ops` 在 Mac 上不存在 |
| `deploy/cloud/docker-compose.yml` | deploy/cloud/ | ✅ | 可本地 `docker compose up`，但 server.py 入口需验证 |

### 6.2 docker-compose 可执行性

| compose 文件 | 关键问题 |
|-------------|----------|
| `deploy/cloud/docker-compose.yml` | `--port 8088` 与 deploy_cloud.sh 的 8098 冲突；`server.py` 路径待验证（实际可能是 `app.py`） |
| `deploy/edge/docker-compose.yml` | `runtime: nvidia` + L4T 基础镜像 — 仅 Jetson 可执行 |
| `deploy/jetson/docker-compose.yml` | 同上 |

### 6.3 部署可行性总评：❌ **不可一键部署**

**硬阻塞项**：
1. Hub 端口不统一（8088/8098），部署后边缘设备无法连接
2. 部署脚本全部硬编码 IP 地址，无环境变量抽象层
3. 云端 `server.py` 入口可能不存在（实际为 `app.py`）
4. API Key 为占位符
5. VLM bridge 依赖外部编译二进制（llama-server），无 fallback

---

## 七、审查结论与建议

### P0（阻塞性·必须修）

| # | 问题 | 建议 |
|---|------|------|
| 1 | **Hub 端口分裂 8088 vs 8098** | 统一为 8098（与生产脚本一致），更新架构设计文档和 docker-compose |
| 2 | **部署脚本全部硬编码 IP/分支** | 抽象为环境变量 + `.env` 文件，支持多环境切换 |
| 3 | **架构设计 §8 映射表包含 11 个幽灵文件** | 删除不存在代码的映射行，标注 `⬜ 待实现` |

### P1（高风险·展前修）

| # | 问题 | 建议 |
|---|------|------|
| 4 | **58 处 TODO/桩标记**（supply_chain 12 处 PG 未接入） | 采购闭环 PG 接入优先完成，其他按 Phase 分级处理 |
| 5 | **data_engine_schema.py 仅 SQLite，无 PG migration** | 补充 PG DDL 或 Alembic migration |
| 6 | **scoreboard.py 未提交但被 pipeline.py 依赖** | 合入 scoreboard.py 或回退 pipeline.py 修改 |
| 7 | **核心推理路径测试严重不足**（kitchen/yolo 7 个、vlm 4 个） | 编写：YOLO+VLM 管线端到端测试、scene_analyzer 单元测试 |

### P2（改善性·展会后可修）

| # | 问题 | 建议 |
|---|------|------|
| 8 | 测试分布极度不均衡（alert_fatigue 80 vs kitchen_yolo 7） | 梳理测试策略，按模块风险分配测试资源 |
| 9 | conftest.py 用 MagicMock 绕过真实 detector — 无法测真实推理 | 增加带 mock 数据的集成测试 |
| 10 | analytics.py 仅有 3 行桥接代码 | 补充 analytics 路由的实际实现 |
| 11 | VERSION 文件仍为 `v5.3i 20260729` | 更新为当前版本号 |
| 12 | deploy/cloud/docker-compose 引用 server.py 而非 app.py | 修正启动命令 |

---

## 八、审查数据来源

| 来源 | 说明 |
|------|------|
| 代码文件扫描 | `find` + `wc -l` 检查空文件 |
| TODO/桩标记搜索 | `grep -r "TODO\|FIXME\|stub\|NotImplementedError"` 58 处 |
| 测试统计 | `grep -r "def test_"` 66 文件 700+ 函数 |
| 端口引用交叉比对 | 全仓 grep 8088/8098/8080/8084/8089/3000/9080/9100 |
| 架构映射验证 | 逐一确认 §8 表中代码路径是否存在 |
