# K01 白盒审查报告 — 小抠代码

> **审查人**: Hermes (独立 Verifier)
> **日期**: 2026-07-16
> **规格**: [spec-K01-kitchen-waste-detection.md](./spec-K01-kitchen-waste-detection.md)
> **测试用例**: [test_cases-K01-kitchen-waste-detection.md](./test_cases-K01-kitchen-waste-detection.md)
> **Gap参考**: [gap-analysis-v2.md](./gap-analysis-v2.md)

---

## 一、变更文件清单

| # | 任务要求文件 | 实际状态 | 说明 |
|---|------------|---------|------|
| 1 | `count-anything/count_server.py` | ❌ **不存在** | Jetson :8100 Count Server 完全缺失 |
| 2 | `edge/kitchen/inference/stages/count.py` | ⚠️ 名称偏差 | 实际为 `stages/stage_count.py`（符合 __init__.py 的 `stage_*.py` 注册约定） |
| 3 | `edge/kitchen/inference/stage_count.py` | ❌ **不存在** | 任务提到的「薄兼容层」未创建 |
| 4 | `edge/kitchen/inference/pipeline.py` | ✅ **已修改** | 确认4-stage注册，Count集成可用 |
| 5 | `hub/schema/waste_daily_stats.sql` | ❌ **不存在** | Spec §6 引用的 DDL 文件完全缺失 |
| 6 | `hub/api/hub_waste_api.py` | ❌ **不存在** | 任务要求的新API文件未创建；功能已合并到现有 `routers/kitchen.py` + `routers/vlm.py` + `db.py` |

**实际变更覆盖**: Edge端基本可用，Hub端功能内嵌在现有文件中，但 Count Server、DDL、兼容层3个文件缺失。

---

## 二、逐文件审查

### 2.1 `edge/kitchen/inference/stages/stage_count.py` (149行)

**功能**: Stage 4 废料计数 — 对每个ROI调用Jetson :8100 /count API

#### ✅ 正确实现

| 项目 | 状态 | 对应测试 |
|------|:---:|---------|
| ROI收集（YOLO+VLM去重） | ✅ | TC-W1, TC-W5 |
| 空ROI → skipped | ✅ | TC-W2 |
| 计数注入 clip_results / vlm_results | ✅ | TC-W6 |
| 非整数 count → int() 转换 | ✅ | TC-W7 |
| ctx 写入 count_results | ✅ | — |

#### 🔴 P0 问题

| ID | 问题 | 位置 | 对应规范 | 说明 |
|----|------|------|---------|------|
| **P0-1** | 首次调用超时未区分 | L36 `timeout=10.0` | Spec §5.2 | Spec 要求首次 `/count` 超时 120s（模型下载），后续 10s。当前所有调用统一 10s，首次调用可能超时失败。 |
| **P0-2** | count 值未截断 (0-200) | L102-106 | Spec §2.1 边界约束 | Spec 明确 `count ∈ [0, 200]`，超限值应截断为 200 并标记 `status="capped"`。当前代码透传任意值，999 会污染聚合结果。 |

#### 🟡 P1 问题

| ID | 问题 | 位置 | 说明 |
|----|------|------|------|
| **P1-1** | 串行阻塞调用 | L97-121 | 所有 ROI 逐个串行调用 `/count`。10个ROI × 50-200ms = 0.5-2s，远超 Spec §3 的 200ms Count 预算。应使用 `httpx.AsyncClient` 并发。 |
| **P1-2** | 无重试机制 | L39-56 | Count API 5xx 错误直接标记为 error。对比 `pipeline.post_to_hub` 有3次重试，计数阶段也应至少重试1次。 |
| **P1-3** | 图片MIME类型硬编码 | L42 `"image/jpeg"` | ROI 可能是 PNG 或其他格式，应从文件扩展名动态判断。 |

#### 🟢 P2 问题

| ID | 问题 | 位置 | 说明 |
|----|------|------|------|
| **P2-1** | httpx 客户端未复用 | L43-48 | 每个 ROI 创建新的 httpx session，应复用连接池。 |
| **P2-2** | `zone` 未校验 | L62 | zone 字段传入 API 但无长度/字符校验。 |

---

### 2.2 `edge/kitchen/inference/pipeline.py` (204行)

**功能**: 4-stage 管线调度 + Hub 推送

#### ✅ 正确实现

| 项目 | 状态 | 对应测试 |
|------|:---:|---------|
| 4-stage 自动注册 | ✅ | TC-W9 |
| VLM skip 模式 | ✅ | TC-W10 |
| YOLO 无检测 → 提前终止 | ✅ | TC-W11 |
| YOLO 故障 → degraded | ✅ | TC-W12 |
| total_waste_count 聚合 | ✅ | TC-W14 |
| ctx 传递 count_api_url | ✅ | TC-W13 |
| post_to_hub 重试 | ✅ | — |

#### 🔴 P0 问题

| ID | 问题 | 位置 | 说明 |
|----|------|------|------|
| **P0-3** | Pipeline status 无条件覆盖 | L137 `pipeline_result["status"] = "ok"` | 无论 count stage 返回 `partial`（部分ROI失败）还是其他降级状态，最终都被覆写为 `ok`。Hub/Dashboard 无法感知计数降级。 |

#### 🟡 P1 问题

| ID | 问题 | 位置 | 说明 |
|----|------|------|------|
| **P1-4** | post_to_hub 不含图片 base64 | L143-163 | 对比 `waste_vision.py` 的 `submit_to_hub` 会编码 base64 图片，pipeline 的 `post_to_hub` 不传图片数据。Dashboard 后续可能无法渲染原始帧。 |
| **P1-5** | API Key 空值无警告 | L155 `os.environ.get("HOTPOT_API_KEY", "")` | 若环境变量未设置，请求以空 key 发送。demo 模式下可工作（auth fallback），但生产环境会 401。应至少 log warning。 |
| **P1-6** | items 中 source 字段语义混淆 | L112 `item["source"] = clip.get("top_class", "unknown")` | Spec 中 `source` 是事件来源标识（`vlm-shadow`/`mock`），但这里被赋值为分类名（如 `food_waste`）。后续 Hub 处理逻辑依赖 `source` 判断 mock vs edge 路径，可能被污染。 |

#### 🟢 P2 问题

| ID | 问题 | 位置 | 说明 |
|----|------|------|------|
| **P2-3** | Hub URL 和 Count API URL 默认值硬编码 | L36-39 | 虽有环境变量覆盖，但 fallback 值写死 IP。应统一到配置文件。 |

---

### 2.3 `hotpot_platform/cloud/event_hub/routers/kitchen.py` (82行)

**功能**: `GET /api/kitchen/waste/stats` — 废料趋势查询

#### ✅ 正确实现

| 项目 | 状态 | 对应测试 |
|------|:---:|---------|
| days 参数校验 (1-90) | ✅ | TC-W22, TC-B17, TC-B18 |
| Auth 校验 | ✅ | TC-W19, TC-B19 |
| store_id 默认值 | ✅ | TC-W19 |
| live_count 补充 | ✅ | TC-W24 |

#### 🟡 P1 问题

| ID | 问题 | 位置 | 说明 |
|----|------|------|------|
| **P1-7** | live_count 可能重复计算 | L62-78 | `query_waste_count_stats` 从 DB 查事件，`live_events` 从内存查事件。如果某个事件已写入 DB 但未从内存清除，会被计两次。应跳过已持久化的事件。 |
| **P1-8** | live_count 遗漏 total_waste_count | L75-78 | 仅累加 `items[].count`，忽略 `total_waste_count` 顶层字段。部分事件可能只有 total_waste_count 无 per-item count。 |
| **P1-9** | 读接口用了写权限检查 | L56 `enforce_store_write(auth, sid)` | GET 端点应使用 `enforce_store_read`。当前在 strict 模式下，只读角色（如财务审计）无法查看废料统计。 |

#### 🟢 P2 问题

| ID | 问题 | 位置 | 说明 |
|----|------|------|------|
| **P2-4** | `live_count` 仅追加到响应，不参与 trend/daily | L80 `stats["live_count"] = live_total` | live_count 作为独立字段，但今日的 `daily[-1].total_count` 不含 live_count。Dashboard 看到的"今日总数"和"实时计数"是两个不同数字，可能困惑。 |

---

### 2.4 `hotpot_platform/cloud/event_hub/db.py` — `query_waste_count_stats` (312行中的 L207-311)

**功能**: 从 events 表按天聚合废料计数

#### 🔴 P0 问题

| ID | 问题 | 位置 | 说明 |
|----|------|------|------|
| **P0-4** | 缺失日期未填充 0 值 | L299-302 | 只返回有事件的日期，不填充无事件日。Spec 示例 `trend: [153, 128, 172, 0, 145, 168, 190]` 中第4天为 0。当前代码若某天无事件，该天会从 daily/trend/dates 中完全消失，导致前端柱状图错位。TC-B20 要求空数据时 `trend=[0]`。 |

#### 🟡 P1 问题

| ID | 问题 | 位置 | 说明 |
|----|------|------|------|
| **P1-10** | items 未按 SKU 聚合 | L287-295 | 同一天多个事件的同一SKU会生成多条 items 记录，而非如 Spec 所示的聚合 `{"sku": "毛肚", "count": 45}`。前端需自行二次聚合。 |
| **P1-11** | `total_waste_count` 只在 metadata 查找 | L262 | 虽然当前事件结构下 `total_waste_count` 在 metadata 中（vlm.py L108 → L121），但若未来 payload 结构调整（直接放在顶层），此查询会漏数据。 |

#### 🟢 P2 问题

| ID | 问题 | 位置 | 说明 |
|----|------|------|------|
| **P2-5** | items 列表无界增长 | L290-295 | 每天所有 item 都追加到列表，高流量日可能产生数千条 items 记录。应限制或截断。 |
| **P2-6** | `created_at` 格式假设 | L272 `row["created_at"][:10]` | 假设 created_at 前10字符为日期。若格式变化（如无连字符的紧凑格式），切片会出错。 |

---

### 2.5 缺失文件影响分析

#### `count-anything/count_server.py` (Jetson Count Server)

- **影响**: P0 阻塞。Stage 4 需要该服务在 Jetson :8100 运行。当前无服务端实现，整个 K01 计数链路无法端到端验证。
- **Spec 要求**: `GET /health`, `POST /count` (multipart/form-data), YOLOv5s 模型
- **建议**: 基于现有 `count-anything` 项目或从零实现 FastAPI 服务

#### `hub/schema/waste_daily_stats.sql` (DDL)

- **影响**: P1。Spec §6 规划的 `waste_daily_stats` 时序表未创建。当前 `query_waste_count_stats` 直接从 events 表实时聚合，查询效率随数据量增长而下降。
- **建议**: 创建预聚合表 + 定时 job（cron/调度器）写入，减轻 events 表查询压力

#### `edge/kitchen/inference/stage_count.py` (薄兼容层)

- **影响**: P2。若外部代码直接 `import stage_count`（不带 stages. 前缀），会 import 失败。
- **建议**: 创建该文件作为 `from .stages.stage_count import run, STAGE_NAME, STAGE_ORDER` 的 re-export。

---

## 三、安全检查

| 检查项 | 结果 |
|--------|:---:|
| 密钥泄露 | ✅ 无。所有密钥通过环境变量，未硬编码明文 |
| SQL 注入 | ✅ 无。所有查询使用参数化绑定 (`?` 占位符) |
| 未授权访问 | ✅ 所有 Hub 端点均通过 `get_auth_context` 鉴权 |
| X-Api-Key 认证链路 | ✅ 兼容。Auth 系统同时支持 JWT Bearer 和 X-Api-Key |
| base64 图片注入 | ✅ `image_data` 存入文件系统，非内联执行 |

---

## 四、性能分析

| 检查项 | 结果 |
|--------|:---:|
| 死循环风险 | ✅ 无 |
| 内存泄漏 | ⚠️ `db.query_waste_count_stats` 的 items 列表无界增长 (P2-5) |
| 阻塞调用 | ⚠️ `stage_count.py` 串行 httpx 调用 (P1-1) |
| 连接池复用 | ⚠️ httpx 未复用连接 (P2-1) |
| 并发安全 | ⚠️ `db.py` 使用 `_lock` 保护 SQLite，但 `kitchen.py` 的 live_count 和 DB 查询无事务一致性 |

---

## 五、与现有代码冲突分析

| 冲突点 | 严重度 | 说明 |
|--------|:---:|------|
| `pipeline.py` items[].source 语义冲突 (P1-6) | 🟡 | 将 CLIP 分类名写入 `source` 字段，可能与 Hub 的 source 判断逻辑冲突 |
| `kitchen.py` `enforce_store_write` vs 读接口 (P1-9) | 🟡 | GET 端点使用了写权限检查，与 rbac 模块的读写分离设计不一致 |
| gap-analysis K-001 数据表 | 🟡 | gap-analysis 规划了专用 `waste_events` 表，实际实现走 events 表聚合，两者方向一致但细节不同 |
| gap-analysis K-002 趋势预警 | 🟢 | 未涉及。K01 聚焦计数存储，趋势预警留待后续 |

---

## 六、问题汇总

| 严重度 | 数量 | ID 列表 |
|:---:|:---:|------|
| 🔴 P0 | 4 | P0-1 (首次超时), P0-2 (count截断), P0-3 (status覆写), P0-4 (缺失日期) |
| 🟡 P1 | 11 | P1-1~P1-11 |
| 🟢 P2 | 6 | P2-1~P2-6 |

### 按文件分布

| 文件 | P0 | P1 | P2 |
|------|:---:|:---:|:---:|
| `stages/stage_count.py` | 2 | 3 | 2 |
| `pipeline.py` | 1 | 3 | 1 |
| `routers/kitchen.py` | 0 | 3 | 1 |
| `db.py` | 1 | 2 | 2 |
| 缺失文件 | 1 (count_server) | 1 (DDL) | 1 (兼容层) |

---

## 七、修复建议优先级

### 第一轮修复（P0，阻塞 MVP）

1. **P0-1**: `stage_count.py` — 实现首次调用 120s 超时逻辑。可用 `ctx.get("count_first_call", True)` 标记，首次后置 `False`
2. **P0-2**: `stage_count.py` — L102-106 后增加 `if count > 200: count = 200; detail["status"] = "capped"`
3. **P0-3**: `pipeline.py` — L134-137 改为 `if pipeline_result.get("status") != "degraded": pipeline_result["status"] = count_results.get("status", "ok")`
4. **P0-4**: `db.py` — `query_waste_count_stats` 返回前填充缺失日期，生成完整的 trend/dates 数组
5. **缺失**: 创建 `count-anything/count_server.py`（Jetson Count Server，阻塞整个K01链路）

### 第二轮修复（P1）

- P1-1: 改用 `httpx.AsyncClient` 并发调用
- P1-6: 重命名 items 中的 `source` 字段为 `detected_class` 避免与事件级 source 混淆
- P1-7/8: `kitchen.py` live_count 去重 + 包含 total_waste_count
- P1-10: `db.py` items 按 SKU 聚合
- 缺失: 创建 `hub/schema/waste_daily_stats.sql`

---

*审查完成。不修代码，仅输出报告。*
