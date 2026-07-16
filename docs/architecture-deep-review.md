# 火瞳 (hotpot_smart_ops) — 五维架构深度评审报告

> 评审日期: 2026-07-16 | 评审范围: 全量代码(200+源文件) + 全部产品文档(20+份)
> 评审维度: 可扩展 · 健壮 · 高并发 · 可用 · 易用
> 代码根: `~/company/products/to-b/hotpot_smart_ops/`

---

## 执行摘要

火瞳架构在三阶段开发中展现出**良好的工程素养**：可插拔管线（stages/丢文件注册）、自动路由发现（routers/丢文件注册）、模块化配置下发链路已成型。但在**规模化扩展路径**上存在5个P0级隐患：SQLite单点写入瓶颈、Dashboard IP硬编码、离线数据丢失、Hub无HA、API碎片化。本报告给出逐维诊断+TOP10修复清单+12个月演进路线图。

| 维度 | 评分 | 一句话判定 |
|------|:---:|------|
| 可扩展性 | 🟡 6/10 | 模块热插拔优秀，但DB+网络层未做规模化准备 |
| 健壮性 | 🟡 5.5/10 | 管线降级完善，但离线缓冲只覆盖IoT未覆盖推理 |
| 高并发 | 🔴 4.5/10 | SQLite单锁+同步推理阻塞，100店场景下有瓶颈 |
| 可用性 | 🟡 5/10 | 看门狗保活到位，但Hub单点无HA、部署靠手动 |
| 易用性 | 🟡 5.5/10 | 丢文件注册优雅，但API不一致+IP硬编码伤体验 |

---

## 一、可扩展性 (Scalability) — 评分: 6/10

### 1.1 现状评估

**✅ 优秀设计**

| 机制 | 位置 | 效果 |
|------|------|------|
| **Stage 热插拔** | `edge/kitchen/inference/stages/__init__.py` | 丢 `stage_xxx.py` → 自动注册到管线，pipeline.py 无需修改 |
| **Router 自动发现** | `routers/__init__.py` → `auto_include_routers()` | 丢 `.py` 文件导出 `router` → Hub 启动时自动挂载，18 routes 零手动 |
| **模块注册表** | `edge/agent/server.py:47-51` `_MODULE_REGISTRY` | 新模块 = 注册表加一行 + 丢 module 文件 |
| **多租户从 Day 1** | `MultiTenantHub` + `EventStore` per store | 内存隔离、DB 隔离、权限隔离 |
| **组织层级** | Zone→Region→Store→Device 四级 | `org_registry.py` + `stores.json` 持久化 |

```
# 新增门店: 只需在 demo/data/stores.json 加一条 → 重启 Hub
# 新增推理模块: edge/agent/server.py 加一行注册 → 配置下发激活
# 新增管线阶段: stages/ 丢文件 → 自动挂载
# 新增 API: routers/ 丢文件 → 自动挂载
```

### 1.2 问题清单

| ID | 问题 | 严重度 | 根因 | 影响 |
|----|------|:---:|------|------|
| **SC-001** | **SQLite 单锁写瓶颈** | 🔴 P0 | `db.py:44` `self._lock = threading.Lock()` 一把锁覆盖所有 store 的所有表写入。100 店 × 30s heartbeat = 200 QPS write contention | 单店→3店无感，10店+开始明显锁等待，100店不可用 |
| **SC-002** | **Dashboard IP 硬编码** | 🔴 P0 | `front-hall.html:56` `const HUB = 'http://192.168.2.240:8098'`，`admin.html:80`、`kitchen-vision.html:194`、`vlm-demo.html:173` 同样硬编码 | 新增门店需重新部署 Dashboard HTML，无法跨网络访问 |
| **SC-003** | **Events 无索引查询** | 🟡 P1 | `db.py:276-284` 用 `json_extract(payload, '$.event_type')` 做过滤，无计算列/索引。500 events × 100 stores = 50K 行全表扫描 | 趋势查询在 100 店时 O(n) 退化 |
| **SC-004** | **MAX_EVENTS_PER_STORE=500 硬上限** | 🟡 P1 | `db.py:24` `MAX_EVENTS_PER_STORE = 500` 无分页、无归档策略 | 高流量场景一天就满，丢失历史数据 |
| **SC-005** | **Device Registry 内存字典** | 🟡 P1 | `routers/devices.py:32` `_devices: Dict[str, dict] = {}` 全局内存字典，无分区 | 1000 设备时内存膨胀 + 重启全丢需重注册 |
| **SC-006** | **无 API 版本策略** | 🟢 P2 | `/v1/` 和 `/api/` 混用但无 v2 迁移计划 | 未来 breaking change 时 Dashboard 和 Edge 同步升级困难 |

### 1.3 改进方案

#### SC-001: SQLite → PostgreSQL + 连接池 (P0)
```
方案: 已有 pg_db.py PostgresHubDatabase 骨架，补齐迁移工具
步骤:
  1. 完善 pg_db.py 的 upsert/query 实现
  2. 增加 alembic migration
  3. HOTPOT_DATABASE_URL=postgresql://... → 自动切换
  4. SQLite 保留为单店开发/测试模式
估时: 3-5天
```

#### SC-002: Dashboard 集中配置 (P0)
```
方案: dashboard/js/config.js 或 index.html meta tag
  <meta name="hotpot-hub-url" content="__HUB_URL__">
  serve.py 启动时注入真实 Hub 地址
估时: 0.5天
```

#### SC-003: Events 表加计算列+索引 (P1)
```sql
ALTER TABLE events ADD COLUMN event_type TEXT GENERATED ALWAYS AS (json_extract(payload, '$.event_type')) STORED;
CREATE INDEX idx_events_type_store ON events(event_type, store_id, created_at DESC);
```
估时: 0.5天

---

## 二、健壮性 (Robustness) — 评分: 5.5/10

### 2.1 现状评估

**✅ 优秀设计**

| 机制 | 位置 | 效果 |
|------|------|------|
| **管线降级矩阵** | `edge/kitchen/inference/rules.py` `DEGRADATION_MATRIX` | YOLO 失败 → 链路终止（不抛异常），VLM 失败 → 跳过（CLIP 结果仍可用） |
| **Store & Forward** | `edge/front_hall/bridge/store_forward.py` | 磁盘持久化、原子替换(`os.replace`)、有序重放、失败停止保序 |
| **Post to Hub 重试** | `pipeline.py:149-169` `post_to_hub()` max_retries=3 + sleep 1s | 瞬时网络抖动不丢事件 |
| **VLM 输出解析降级** | `waste_vision.py:152-173` `parse_vlm_output()` | 直接解析 → 正则提取 → 抛异常，3层兜底 |
| **看门狗自动重启** | `deploy/watchdog.sh` | 每30s检测 hub/edge/vlm，挂了自动重启 + 推 Mac 告警 |

### 2.2 问题清单

| ID | 问题 | 严重度 | 根因 | 影响 |
|----|------|:---:|------|------|
| **RB-001** | **推理结果无离线缓冲** | 🔴 P0 | `kitchen_infer.py:256-273` POST 到 Hub 仅内存重试 3 次，无 StoreAndForward。对比: front_hall IoT 有 `store_forward.py` 磁盘缓冲 | Jetson 断网期间所有推理结果永久丢失 |
| **RB-002** | **注册失败静默降级** | 🔴 P0 | `edge/agent/server.py:318-319` `except Exception: logger.error("注册失败，将以无配置模式运行")` 然后不重试 | 盒子启动时 Hub 暂时不可达 → 永久无配置运行 |
| **RB-003** | **Hub 输入校验缺失** | 🟡 P1 | `routers/vlm.py` 接收 `waste-estimate` 但不校验 `items[].count` 为负数、`confidence` 超范围、`sku` 为空 | 脏数据直接入库，后续查询报错或展示异常 |
| **RB-004** | **Hub Client 无熔断** | 🟡 P1 | `edge/agent/server.py:63-67` httpx timeout=10s 但无 circuit breaker | Hub 慢响应时每次心跳等 10s，阻塞其他请求 |
| **RB-005** | **看门狗不检测僵尸服务** | 🟢 P2 | `watchdog.sh:31` 只检测 `/health` 返回 ok，不验证功能 | CUDA 缺失等场景下 health=200 但推理 500，看门狗不知道 |
| **RB-006** | **VLM 临时文件泄漏** | 🟢 P2 | `waste_vision.py:119` `prompt_file = Path("/tmp/vlm_bridge_prompt.txt")` 写入后 `unlink(missing_ok=True)` | 异常退出时残留 |

### 2.3 改进方案

#### RB-001: 推理管线接入 StoreAndForward (P0)
```
方案: kitchen pipeline.py 的结果先写 StoreAndForwardBuffer，
      由独立 replay worker 异步推 Hub
步骤:
  1. pipeline.py post_to_hub() 改为 enqueue to StoreAndForwardBuffer
  2. Agent 启动时为 kitchen 创建 replay worker (asyncio task)
  3. replay: 每30s尝试将缓冲的 results POST Hub
估时: 1-2天
```

#### RB-002: 注册失败指数退避重试 (P0)
```python
# edge/agent/server.py startup() 修改
retry_delays = [1, 2, 4, 8, 16, 32]  # ~1分钟总时间
for delay in retry_delays:
    try:
        resp = await register()
        break
    except Exception:
        await asyncio.sleep(delay)
else:
    logger.critical("注册失败，进入离线模式（本地推理+缓冲，不上报Hub）")
```
估时: 0.5天

---

## 三、高并发 (High Concurrency) — 评分: 4.5/10

### 3.1 现状评估

**✅ 优秀设计**

| 机制 | 位置 | 效果 |
|------|------|------|
| **FastAPI Async** | uvicorn + async/await | I/O 不阻塞事件循环 |
| **httpx 连接池** | `edge/agent/server.py:63-67` max_keepalive=5, max_connections=10 | 复用 TCP 连接 |
| **Per-Store 锁** | `hub_core.py` `EventStore._lock` per store | 店间不互斥 |

### 3.2 问题清单

| ID | 问题 | 严重度 | 根因 | 影响 |
|----|------|:---:|------|------|
| **CC-001** | **SQLite 全局写锁** | 🔴 P0 | `db.py:44` 所有 store 的 persist_event/persist_snapshot/update_devices 共享一把 `threading.Lock()` | 10 店 × 30s heartbeat = 20 QPS 互相等待；100 店不可用 |
| **CC-002** | **Hub In-Memory 全局锁** | 🔴 P0 | `hub_core.py:221` `MultiTenantHub._lock` 覆盖所有 store 的 get/create | get_store() 高频操作被全局锁串行化 |
| **CC-003** | **同步 YOLO 检测阻塞事件循环** | 🟡 P1 | `kitchen_infer.py:201-202` `img = cv2.imread(...)` + `detector.detect(img)` 在 async handler 中同步调用 | 大图推理(100ms+)阻塞 FastAPI worker，降低并发容量 |
| **CC-004** | **Dashboard 无差别轮询** | 🟡 P1 | 9 页面各自 `setInterval(refresh, 5000-30000)`，无智能退避 | 100 店 × 20 Dashboard 同时刷新 = 60+ QPS 纯轮询负载 |
| **CC-005** | **Bridge 无连接复用** | 🟡 P1 | `waste_vision.py:65-84` 每次请求 `urllib.request.urlopen()` 新建 TCP 连接 | 高吞吐时 TIME_WAIT 堆积 |

### 3.3 改进方案

#### CC-001+002: 数据库层并发重构 (P0)
```
方案: PostgreSQL (已有 pg_db.py 骨架) + asyncpg 异步驱动
  - 写操作去全局锁，依赖 PG MVCC
  - Hub In-Memory 改为 per-store 无锁读 + 写时复制
  - SQLite 仅开发/单店使用

短期 (1店): SQLite 完全够用，无需改
中期 (3-10店): 评估 PG 迁移成本
长期 (100店): 必须 PG
```

#### CC-003: YOLO 推理丢线程池 (P1)
```python
# 改为
loop = asyncio.get_running_loop()
result = await loop.run_in_executor(_infer_executor, detector.detect, img, "kitchen")
```
估时: 0.5天

#### CC-004: Dashboard 智能轮询 (P1)
```
方案: Server-Sent Events (SSE) 替代轮询
  GET /v1/events/stream?store_id=xxx → text/event-stream
  新事件到达 → 推送到已连接 Dashboard
  兼容: 保留 setInterval 作为 fallback
  
估时: 2天
```

---

## 四、可用性 (Availability) — 评分: 5/10

### 4.1 现状评估

**✅ 优秀设计**

| 机制 | 位置 | 效果 |
|------|------|------|
| **看门狗保活** | `deploy/watchdog.sh` | hub/edge/vlm 挂了 30s 内自动拉起 |
| **一键部署脚本** | `deploy/deploy-hotpot.sh` | 10 个 Phase 从 rsync→pip→启动→验证 |
| **Systemd 单元** | `deploy/edge/systemd/` | IPC grabber + pipeline 的 systemd 管理 |
| **Docker Compose** | `deploy/cloud/docker-compose.yml` | Hub + Dashboard + 可选 PG/MQTT |
| **DB 持久化 + 启动恢复** | `db.py:hydrate_hub()` + `devices.py:_load_devices()` | Hub 重启从 SQLite 恢复全部状态 |

### 4.2 问题清单

| ID | 问题 | 严重度 | 根因 | 影响 |
|----|------|:---:|------|------|
| **AV-001** | **Hub 单点故障** | 🔴 P0 | 单进程 FastAPI + 单 SQLite 文件。无 replica、无 load balancer | Hub 挂了 → 所有 Dashboard 白屏 + 所有设备失联 + 日报停摆 |
| **AV-002** | **Jetson 无 Docker/容器化** | 🔴 P0 | `jetson-edge-deployment` skill 明确 "Docker 避坑：Jetson 上不要用 Docker"。纯 nohup 启动 | 部署靠手动 SSH，回滚无原子操作，依赖冲突难排查 |
| **AV-003** | **Hub 挂了盒子仍可推理但数据丢失** | 🔴 P0 | 见 RB-001。推理结果推 Hub 失败 → 丢弃。盒子本地推理不依赖 Hub | 断网期间有推理能力但无数据留存（与"离线存活>24h"的 PRD 需求冲突） |
| **AV-004** | **无配置热推送** | 🟡 P1 | 配置下发依赖设备 60s poll。管理员 PUT config → 设备最多等 60s | 紧急关停某摄像头需等 60s |
| **AV-005** | **无 DB 迁移机制** | 🟢 P2 | `db.py:52-118` `_init_schema()` 用 `CREATE TABLE IF NOT EXISTS` 但无版本号 | 表结构变更靠人工 SQL，生产环境危险 |
| **AV-006** | **无优雅关闭** | 🟢 P2 | 无 signal handler、无 `graceful_shutdown` | kill -9 丢未落盘数据 |

### 4.3 改进方案

#### AV-001: Hub 高可用 (P0, 3-6个月)
```
方案 (渐进):
  短期 (1店): 当前够用
  中期 (3-10店): PostgreSQL + systemd auto-restart + Mac 定时备份 SQLite
  长期 (100店): PostgreSQL primary-standby + Nginx upstream + health check
```

#### AV-002: Jetson 部署标准化 (P0)
```
方案: 不追求 Docker，建立标准化部署脚本体系
  1. deploy/jetson/install.sh — 一键装机 (CUDA + Python + models)
  2. deploy/jetson/start.sh — 启动全部服务
  3. deploy/jetson/stop.sh — 优雅停止
  4. deploy/jetson/rollback.sh — 回滚到上一版本 (tar 备份)
估时: 1天
```

#### AV-003: 离线数据缓冲 (P0)
```
见 RB-001 方案。推理结果写 StoreAndForwardBuffer → Hub 恢复后自动回放
```

---

## 五、易用性 (Usability) — 评分: 5.5/10

### 5.1 现状评估

**✅ 优秀设计**

| 机制 | 位置 | 效果 |
|------|------|------|
| **丢文件注册** | 管线级: `stages/` · 路由: `routers/` · 推理: `strategies/` `engines/` | 开发者体验极好，新增功能零模板代码 |
| **Pydantic 模型** | `_deps.py` 全套 Body 模型 | 自动校验 + OpenAPI 文档 |
| **环境变量配置** | 全部 12 个可配参数 | 12-factor app 风格 |
| **CLI 参数** | 全部 server 支持 `--host --port --db` | 本地调试友好 |
| **API Key 校验** | `edge/agent/config.py:12-28` | DEV_MODE 下自动跳过，生产强制校验 |

### 5.2 问题清单

| ID | 问题 | 严重度 | 根因 | 影响 |
|----|------|:---:|------|------|
| **US-001** | **API 路由碎片化** | 🔴 P0 | `/v1/devices/`, `/api/kitchen/`, `/infer/kitchen/`, `/v1/vlm/`, `/auth/token` 5 种前缀混用，无统一规范 | 调用方需要记忆不同前缀规则；自动发现难 |
| **US-002** | **错误响应格式不统一** | 🔴 P0 | `{"ok": True}` vs `{"status": "ok"}` vs `{"error": "..."}` vs `raise HTTPException` | 客户端需要适配多种错误格式 |
| **US-003** | **Dashboard IP 硬编码** | 🔴 P0 | 见 SC-002。7 个页面硬编码 `192.168.2.240` 或 `192.168.2.85` | 部署到新环境必须逐文件修改 |
| **US-004** | **Store ID 解析路径碎片化** | 🟡 P1 | `_deps.py:13-26` `resolve_store_id()` 从 query/body/header/env 5 个地方取，但各 router 有的用有的不用 | 同一个 API 用不同的 store_id 传参方式 |
| **US-005** | **无 API 文档暴露** | 🟡 P1 | FastAPI 自带 `/docs` 但在 DEV_MODE 外可能被禁 | 第三方集成时无文档可查 |
| **US-006** | **无统一分页** | 🟢 P2 | `GET /v1/events?limit=50` 无 offset/total/cursor | 大量事件时前端只能拿前 50 条 |
| **US-007** | **新店部署无向导** | 🟢 P2 | 从拆箱到上线需要手动: SSH→装驱动→传代码→pip→启动→配置 | 非技术人员(店长)无法自助部署 |

### 5.3 改进方案

#### US-001: API 路由统一 (P0)
```
规范:
  /api/v1/devices/*      设备管理
  /api/v1/kitchen/*      后厨
  /api/v1/front-hall/*   前厅
  /api/v1/receiving/*    食材
  /api/v1/staff/*        员工
  /api/v1/cockpit/*      管理总览
  /auth/*                认证

统一前缀 /api/v1/，废弃 /v1/、/infer/ 等旧路径
旧路径保留 Deprecation header 6个月后移除
估时: 1天
```

#### US-002: 统一错误响应 (P0)
```json
{
  "error": {
    "code": "DEVICE_NOT_FOUND",
    "message": "设备不存在: jetson-yuhuan-01",
    "details": {"device_id": "jetson-yuhuan-01"}
  }
}
```
新增 `common/errors.py` ErrorResponse 模型 + 全局 exception handler
估时: 0.5天

---

## 六、综合: TOP10 优先修复清单

| 排名 | ID | 维度 | 问题 | 严重度 | 估时 | 依赖 |
|:---:|------|------|------|:---:|:---:|------|
| 1 | **SC-001** | 可扩展 | SQLite 全局锁 → 100店瓶颈 | 🔴 P0 | 3-5天 | 需要PostgreSQL |
| 2 | **AV-001** | 可用 | Hub 单点故障 | 🔴 P0 | 5-7天 | 依赖#1 PG |
| 3 | **RB-001** | 健壮 | 推理结果无离线缓冲 | 🔴 P0 | 1-2天 | — |
| 4 | **US-001** | 易用 | API 路由碎片化 5种前缀 | 🔴 P0 | 1天 | — |
| 5 | **SC-002** | 可扩展 | Dashboard IP硬编码 | 🔴 P0 | 0.5天 | — |
| 6 | **US-003** | 易用 | Dashboard IP硬编码 (同SC-002) | 🔴 P0 | — | 并案修复 |
| 7 | **RB-002** | 健壮 | 注册失败静默降级 | 🔴 P0 | 0.5天 | — |
| 8 | **CC-001** | 并发 | SQLite 全局写锁 (同SC-001) | 🔴 P0 | — | 并案修复 |
| 9 | **AV-003** | 可用 | Hub挂了推理结果丢失 (同RB-001) | 🔴 P0 | — | 并案修复 |
| 10 | **US-002** | 易用 | 错误格式不统一 | 🔴 P0 | 0.5天 | — |

**P0 总计 (去重合并):**
1. 数据库瓶颈 (SQLite → PG，含并发+可扩展) — 3-5天
2. Hub 高可用 — 5-7天
3. 离线缓冲 + 注册重试 — 2天
4. API 规范化 (路由统一+错误统一+IP集中配置) — 2天

**P0 总估时: 12-16天** (可在 2-3 周内完成)

---

## 七、架构演进路线图 (3/6/12个月)

### 第一阶段: 稳固试点 (0-3个月, 1 店)

```
目标: 试点店(玉环/椒江)稳定运行 30 天, 数据驱动 ROI 验证
架构状态: 单 Jetson + 单 Mac Hub, 无高可用需求

必做:
  ✅ RB-001 离线缓冲 — 盒子断网不丢数据
  ✅ RB-002 注册重试 — 盒子自愈
  ✅ US-002 统一错误格式 — API 规范化
  ✅ US-001 API 前缀统一 (保留旧路径 Deprecation)
  ✅ SC-002 Dashboard 集中配置
  📋 30天试点数据采集 → ROI报告

技术债可暂缓:
  ⏸ PostgreSQL 迁移 (单店 SQLite 够用)
  ⏸ Hub HA (单点可接受)
  ⏸ SSE 推送 (轮询 5s 在单店无压力)
```

### 第二阶段: 冯校长全门店 (3-6个月, 3-10店)

```
目标: 浙江区域门店全覆盖, 功能扩展(SOP+食材+员工), 多店对比Dashboard

必做:
  ✅ SC-001 PostgreSQL 迁移 — 10店 SQLite 锁竞争明显
  ✅ CC-004 Dashboard SSE 推送 — 替代无差别轮询
  ✅ CC-003 YOLO 异步推理 — 提升单盒并发容量
  ✅ AV-004 WebSocket 配置推送 — 替代 60s 轮询
  ✅ US-007 新店部署向导 — 店长自助部署
  📋 K-002 趋势预警上线
  📋 S-001 7工位状态机激活
  📋 I-001 食材监管Edge模块
  📋 M-001 多店对比真实数据

技术债可暂缓:
  ⏸ Hub HA (单 Mac + watchdog 可接受 99% 可用率)
  ⏸ 分页标准化 (10店 events 量可控)
```

### 第三阶段: 标品全国 (6-12个月, 50-100店)

```
目标: 火锅→通用后厨AI, 全国餐饮客户, SaaS化运营

必做:
  ✅ AV-001 Hub 高可用 — PG primary-standby + Nginx LB
  ✅ SC-005 Device Registry 分区 — 按 zone 分片
  ✅ SC-003 Events 索引优化 — 计算列+分区表
  ✅ US-005 统一分页 — cursor-based pagination
  ✅ AV-005 DB migration 框架 — alembic
  ✅ 监控体系 — Prometheus metrics + Grafana
  ✅ 自动扩缩 — Hub 水平扩展 (stateless + PG)
  📋 移动端完善
  📋 POS/ERP 桥接真实对接

技术演进:
  ⏸ Edge 端模型 OTA 更新
  ⏸ 联邦学习 (本地数据不出店, 全局模型聚合)
  ⏸ TimescaleDB 时序专用 (废料/桌态/传感器)
```

---

## 八、架构亮点 (值得保留的设计模式)

| 模式 | 位置 | 为什么好 |
|------|------|------|
| **丢文件注册** | `stages/__init__.py` + `routers/__init__.py` | 零耦合、零模板代码、新人不看文档也能加功能 |
| **Context 传递管线** | `pipeline.py:49-58` `ctx` dict 在 stage 间传递 | 可插拔、可观测、降级状态清晰 |
| **Store & Forward** | `store_forward.py` | 原子写入(`os.replace`)、有序重放、失败保序——教科书级实现 |
| **Runtime 依赖注入** | `runtime.py` + `_deps.py` | 测试友好、无循环导入、组件可替换 |
| **三级过滤** | YOLO→VLM (ADR-014) | 省 80-95% VLM 调用，已验证有效 |
| **配置下发链路** | `devices.py` register→heartbeat→pull-config→pending flag | 推拉结合、幂等、原子应用 |
| **部署脚本 Phase 化** | `deploy-hotpot.sh` 10个Phase | 可断点续传、可单独执行、带验证 |

---

## 九、附录: 数据流审计

### 9.1 设备启动流程
```
Jetson开机
  → Agent.startup()
    → ① POST /v1/devices/register → Hub 登记 + 返回已有 config
    → ② apply_device_config(config) → 按 enabled 激活模块 + 写 IPC 配置
    → ③ asyncio.create_task(heartbeat_loop) → 每30s POST heartbeat + 接收待下发config
    → ④ asyncio.create_task(config_poll_loop) → 每60s POST pull-config

正常运行时:
  admin PUT /v1/devices/{id}/config → Hub 标记 config_pending=True
    → 下次 heartbeat (≤30s) 或 pull-config (≤60s) → 设备拿到新config
    → apply_device_config() → 模块热重载
```

### 9.2 推理数据流
```
摄像头(RTSP) → IPC抓帧 → pipeline.run_pipeline(frame)
  → Stage1: YOLO 检测 (8ms)
  → Stage2: CLIP 分类 (50ms, 可选)
  → Stage3: VLM 语义 (320ms+, 仅可疑帧)
  → Stage4: Count 计数
  → post_to_hub(result) → POST /v1/vlm/waste-estimate → Hub
    → Hub: event → SQLite persist → in-memory EventStore
    → Dashboard: setInterval(5000) → GET /v1/events?store_id=xxx → 渲染
```

### 9.3 离线场景覆盖度
| 场景 | 现状 | 目标 |
|------|:---:|:---:|
| 盒子断网 < 1分钟 | 重试3次 → 可能丢失 | ✅ 重试3次后入 StoreAndForward 磁盘缓冲 |
| 盒子断网 1分钟-1小时 | ❌ 推理结果全部丢失 | ✅ 缓冲 + Hub恢复后自动回放 |
| 盒子断网 > 1小时 | ❌ 同上 | ✅ 磁盘缓冲 + 上限后 FIFO 丢弃(保留最新) |
| Hub 挂了盒子仍推理 | ✅ 模块独立运行 | ✅ + 缓冲兜底 |
| Hub 重启恢复 | ✅ hydrate 从 SQLite | ✅ 无变化 |
| 盒子重启 | 注册→拿配置→自恢复 | ✅ 加注册重试后更可靠 |

---

*评审人: Hermes (小马) | 审查工具: 全量代码扫描 (200+源文件) + 文档交叉验证 (20+份)*
*关联: [gap-analysis-v2.md](./gap-analysis-v2.md) · [架构设计](./火锅AI-架构设计.md) · [PRD](./火锅AI-PRD-产品需求文档.md)*
