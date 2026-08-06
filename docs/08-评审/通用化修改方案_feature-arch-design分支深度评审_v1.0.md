# 火瞳系统设置与架构通用化修改方案 — feature/arch-design 分支深度评审

> **评审日期**: 2026-08-06 | **分支**: feature/arch-design | **工具**: Hermes (小马)
> **评审范围**: 8项整改要求 × 代码/文档/配置/DB 四层全覆盖对照

---

## 一、文档权威链实际状态

整改方案要求链: **PRD v5.3o → 总体架构 v2.1 → 详细架构 v1.6**

| 文档 | 方案要求 | 实际版本 | 偏差 |
|------|:------:|:------:|------|
| 融合 PRD | v5.3o | **v5.3o** | ✅ 一致，含 §1.11 完整通用化改造基线 |
| 总体架构 | v2.1 | **v2.1** | ✅ 一致，上游指向 PRD v5.3o |
| 详细架构 | v1.6 | **v1.8** | ⚠️ 正向演进，v1.8 已含 P0 去伪存真 + K系列修正，建议方案同步版本号 |

**结论**: 权威链完整且活跃，上下游引用全部正确。版本号差异是正向迭代，不影响适用性。

---

## 二、逐项整改要求对照评估

### 整改项 1: 多租户多门店架构 (Tenant→Brand→Region→Store→Edge→Camera)

| 层次 | 状态 | 证据 |
|------|:----:|------|
| **文档** | ✅ 完成 | PRD §1.11.1 完整定义12层对象模型，含Tenant/Brand/Region/Store/Edge/Camera/Zone/Scene/Model/Rule/Agent |
| **DB Schema** | ❌ 严重不足 | `supply_purchase_order.store_id DEFAULT 'store_jiaojiang'`, `sales_events.store_id DEFAULT 'store_jiaojiang'` — **所有核心表均无 `tenant_id`/`brand_id`/`region_id` 列** |
| **代码** | ❌ 严重不足 | `supply_chain/manager.py` 4处 `os.environ.get("HOTPOT_STORE_ID", "store_jiaojiang")`; `pg_db.py` 注释 `tenant_id = store_id`（未实现） |
| **测试** | ❌ 25+处 | 测试文件大量 `store_id="store_jiaojiang"` 硬编码 |

**偏差**: 文档层已完成，**代码/DB层几乎零实现**。当前系统本质是"单 store_id 模式"，tenant/brand/region 三层完全缺失。

---

### 整改项 2: 椒江店是真实样板实例，不是系统唯一业务逻辑

| 层次 | 状态 | 证据 |
|------|:----:|------|
| **文档** | ✅ 完成 | PRD §1.8 收敛为样板店，§1.11.1 明确"椒江店只是对象模型实例" |
| **代码** | ❌ 大量违规 | 见下方详细清单 |

**代码层硬编码椒江店清单**:

| 文件 | 违规行 | 违规模式 |
|------|--------|----------|
| `nl_router.py:31` | `store_id: str = "store_jiaojiang"` | 函数默认参数硬编码 |
| `nl_router.py:71` | `data["store_name"] = "椒江冯校长"` | 店名字符串硬编码 |
| `nl_router.py:128` | `store_id: str = "store_jiaojiang"` | 函数默认参数硬编码 |
| `nl_webhook.py:23` | `store_id: Optional[str] = "store_jiaojiang"` | Pydantic 模型默认值硬编码 |
| `nl_webhook.py:40` | `req.store_id or "store_jiaojiang"` | fallback 硬编码回退值 |
| `supply_chain/manager.py` | **10+处** `store-jiaojiang` | 函数默认值/硬编码参数 |
| `daily_scheduler.py:20` | `PILOT_STORES = ("store_yuhuan", "store_jiaojiang")` | 门店列表硬编码 |
| `daily_scheduler.py:24` | `"store_jiaojiang": "冯校长火锅·椒江店"` | 店名映射硬编码 |
| `pos_bridge.py:261` | `"store_jiaojiang": "冯校长火锅·椒江店"` | 店名映射硬编码 |
| `enable_pilot_cv.py:18` | `PILOT_STORES = ("store_yuhuan", "store_jiaojiang")` | 门店列表硬编码 |
| `pg_db.py:66,124` | `DEFAULT 'store_jiaojiang'` | **DDL 层面默认值硬编码** |
| `pipeline_config_jiaojiang.yml` | `store_id: "store_jiaojiang"` + `name: "椒江店"` | 配置文件店名/IP硬编码 |

> **关键发现**: PRD §1.11.7 文档整改清单已准确记载"测试文件仍有25+处硬编码"，但 NL MVP（`nl_router.py`/`nl_webhook.py`）**不在该计数的覆盖范围内**——这是本轮评审发现的新增缺口。

---

### 整改项 3: 配置驱动，禁止单店/固定IP/固定端口硬编码

| 层次 | 状态 | 证据 |
|------|:----:|------|
| **文档** | ✅ 完成 | PRD §1.11.3 配置分层表，4种配置禁止事项已定义 |
| **配置文件** | ⚠️ 部分违规 | 见下方清单 |

**硬编码 IP/端口残留**:

| 文件 | 硬编码 | 问题 |
|------|--------|------|
| `deploy/edge/docker-compose.yml:20` | `http://192.168.2.85:8098` | 内网IP作为默认值 |
| `deploy/jetson/docker-compose.yml:25` | `http://192.168.2.85:8098` | 同上 |
| `ipc_config_jiaojiang.yml:124` | `http://43.139.143.12:8098` | 腾讯云公网IP |
| `pipeline_config_jiaojiang.yml:17` | `http://43.139.143.12:8098` | 同上 |
| `edge_config.yml:83` | `http://43.139.143.12:8098` | 同上 |
| `edge_config.yml:134` | `port: 9100` | 端口硬编码 |
| `pipeline_config.yml:15` | `http://192.168.2.85:8098` | 默认配置IP |

**NVR 凭据**: ✅ 已通过 `{NVR_PASSWORD}` 环境变量化，文档和配置均合规。

---

### 整改项 4: 真实/桩/Demo 数据严格隔离

| 层次 | 状态 | 证据 |
|------|:----:|------|
| **文档** | ✅ 完成 | PRD §1.11.6 五级环境分类 + source_status 规范 + 5 桩接口枚举固化 |
| **代码** | ⚠️ 违规 | 见下方 |

**桩接口枚举违规**（违反 HC-8）:

| 文件 | 违规字符串 | 应使用 |
|------|-----------|--------|
| `device_stub.py:32,42,51` | `"source": "vision_stub"`, `"iot_stub"` | `"source_status": "simulated"` |
| `admin.py:90` | `"source": "demo_stub"` | `"source_status": "simulated"` |
| `waste_estimate.py:18` | `_mock_confidence()` | 应标记 source_status 而非 mock 置信度 |

**NL MVP 模拟数据严重违规**:
- `nl_router.py` 的 `query_data()` 函数（L31-73）：全量返回硬编码模拟数值（waste_count=3, waste_amount=156, sop_score=87...），**无任何 `source_status` 标记**
- 所有 NL MVP 模板输出均未标识为模拟数据
- 违反 §1.11.6 "`simulated` 仅限 dev/test/demo 环境" 要求

---

### 整改项 5: 统一事件契约（16 字段）

| 字段 | 文档定义 | 代码实现 | 偏差 |
|------|:------:|:------:|------|
| `tenant_id` | ✅ PRD §1.11.4 | ❌ 未实现 | DB 无此列 |
| `brand_id` | ✅ | ❌ 未实现 | DB 无此列 |
| `region_id` | ✅ | ⚠️ hub_core.py 有 region 概念 | 但非字段级 |
| `store_id` | ✅ | ✅ | 多数表有 |
| `edge_device_id` | ✅ | ⚠️ 概念存在 | 未在事件 schema 强制 |
| `camera_id` | ✅ | ⚠️ 部分 | IPC 配置有，非事件必填 |
| `zone_id` | ✅ | ⚠️ 概念存在 | org_registry 有 region，但无 zone 字段 |
| `event_id` | ✅ | ✅ | hub_core 使用了 event_id |
| `correlation_id` | ✅ | ✅ | Agent Gateway 实现了自动生成 |
| `event_type` | ✅ | ⚠️ | 概念存在，无枚举定义 |
| `occurred_at` | ✅ | ⚠️ | sales_events 表有，其他表不统一 |
| `model_name` | ✅ | ❌ 未实现 | 无此字段 |
| `model_version` | ✅ | ⚠️ data_engine_schema 有 | 仅预测表 |
| `confidence` | ✅ | ⚠️ hub_core/waste_estimate | 未在所有事件链路使用 |
| `evidence_ref` | ✅ | ❌ 未实现 | 无此字段 |
| `source_status` | ✅ | ❌ 未实现 | 无此字段 |

**16 字段实现率**: **3/16 完全实现，4/16 部分实现，9/16 未实现**。

---

### 整改项 6: 岗位 Agent 四维配置化（权限/订阅/推送/审批）

| 维度 | 文档定义 | 代码实现 | 偏差 |
|------|:------:|:------:|------|
| `permissions` | ✅ PRD §1.11.5: `can_query/can_advise/can_push/can_create_todo/can_approve` | ❌ AgentConfig 无此字段 | 四维字段完全缺失 |
| `subscription` | ✅ `event_types[]/kpi_metrics[]/time_window/thresholds` | ⚠️ AgentConfig 有 subscriptions | 仅 topic_pattern，无 KPI/阈值/时间窗口 |
| `push_config` | ✅ `channels[]/priority_rules/escalation_min/ack_timeout_sec` | ❌ 完全未实现 | 无推送配置模型 |
| `approval_config` | ✅ `require_approval_for[]/auto_approve_threshold/escalate_to_role` | ❌ 完全未实现 | 无审批配置模型 |

**当前 AgentConfig 模型**（models.py:84-102）:
```python
class AgentConfig(BaseModel):
    agent_id: str
    name: str
    role: AgentRole
    version: str
    capabilities: List[Capability]
    subscriptions: List[Any]
    # ❌ 缺少: permissions, push_config, approval_config
```

**结论**: 当前 Agent 框架（agent_framework/orchestrator.py + agents.py）拥有消息总线（H14）和基础 RoleAgent 基类，但 **Agent 配置维度只覆盖了 1/4**（仅有 Subscription），PRD 要求的 permissions/push_config/approval_config **三个维度完全缺失**。门店 Agent 实例（StoreManagerAgent 等）的权限规则写在类和注释中，而非从配置读取。

---

### 整改项 7: 摄像机优先，IoT 可插拔

| 层次 | 状态 | 评估 |
|------|:----:|------|
| 文档 | ✅ | IoT 已描述为"待接入的可插拔能力" |
| 代码 | ✅ | IoT 模块（`edge/front_hall/iot/`, `edge/iot_mock/`）与摄像机推理独立，可独立启停 |
| 桩接口 | ⚠️ | 见整改项4 — 枚举字段名不合规 |

**结论**: 架构层面已符合"摄像机优先，IoT 可插拔"，但桩接口细节需修正。

---

### 整改项 8: 文档权威链统一

| 检查项 | 状态 |
|--------|:----:|
| PRD 上游输入含通用化方案 | ✅ PRD 第4行: `通用化修改方案 v1.0` |
| PRD → 总体架构 | ✅ 总体架构 v2.1 第4行: `PRD v5.3o` |
| 总体架构 → 详细架构 | ✅ 详细架构 v1.8 第4行: `总体架构 v2.1` |
| 版本号一致性 | ⚠️ 整改方案写"详细架构 v1.6"，实际为 v1.8（正向演进） |
| 链接完整性 | ✅ HC-1 通过 |

---

## 三、NL MVP 专项审查 — 严重违规

`feature/arch-design` 分支最新提交 `63c289b` "feat(P0-7): Agent NL 最小MVP" 引入的代码违反了整改方案**至少 5 项核心要求**：

### 违反项清单

| # | 违规 | 方案要求 | 证据位置 |
|---|------|----------|----------|
| 1 | **硬编码椒江店名作为默认门店** | §3.1 默认值不得参与业务规则 | `nl_router.py:31,128` `store_id="store_jiaojiang"` |
| 2 | **硬编码店名到模板输出** | §2.3 椒江店只是实例，不是默认模型 | `nl_router.py:71` `"椒江冯校长"` |
| 3 | **返回未标记模拟数据** | §7.2 模拟数据必须标记 source_status | `nl_router.py:35-68` 全量硬编码模拟数字 |
| 4 | **缺少 tenant_id/brand_id/region_id** | §5.2 16字段契约 | `nl_webhook.py` 仅 from_user/text/store_id |
| 5 | **Agent 推送目标硬编码** | §6.1 Agent 不得按单店写死 | `nl_router.py:12-17` `KEYWORD_INTENTS` 固定 A01/A02 |
| 6 | **缺少 JWT 身份验证** | §3.2 权限层级 | `nl_webhook.py` 无 Auth middleware |
| 7 | **Webhook 默认 store_id** | §3.1 默认值仅用于初始化 | `nl_webhook.py:23,40` fallback=`store_jiaojiang` |

### 模拟数据列表
```python
# nl_router.py:35-68 — 全部为硬编码模拟数值，无 source_status 标记
query_waste:    waste_count=3, waste_amount=156, trend_pct=-12
query_turnover: turnover_rate="2.8", table_count=8, occupied=6
query_iot:      alert_count=1, temp="8.5°C" 
query_daily:    sop_score=87, waste_amount=156, turnover_rate="2.8"
query_inventory: items_low=["毛肚(剩2份)", "鸭肠(剩1份)"], items_ok=24
query_sop:      score=87, violations=2, top_issue="砧板未消毒"
```

### 判定
> ⚠️ **当前 NL MVP 在 7 个维度上违反了整改方案**。作为 `feature/arch-design` 分支最新提交，它是"单店/Demo/固定配置"模式的代码化身。必须在下一次提交中修复。

---

## 四、P0/P1/P2 整改清单

### P0 — 阻塞性（违反核心要求，展会前必须修复）

| # | 整改项 | 影响范围 | 方案依据 |
|---|--------|----------|----------|
| **P0-1** | NL MVP `store_jiaojiang` 硬编码 → 参数化 `store_id` | `nl_router.py` L31,L128; `nl_webhook.py` L23,L40 | §3.1, §6.1 |
| **P0-2** | NL MVP `"椒江冯校长"` 店名硬编码 → `{store_name}` 模板变量 | `nl_router.py` L71 | §2.3 |
| **P0-3** | NL MVP 模拟数据添加 `source_status: "simulated"` 标记 | `nl_router.py` L35-68 全部 | §7.2, HC-5 |
| **P0-4** | NL MVP 添加 `tenant_id` 上下文校验 | `nl_webhook.py` 请求模型 + 中间件 | §3.1, §5.2 |
| **P0-5** | DB DDL 移除 `DEFAULT 'store_jiaojiang'` | `pg_db.py` L66,L124 (2处) | §4.1 |
| **P0-6** | `supply_chain/manager.py` 移除 10+处 `store-jiaojiang`/`store_jiaojiang` 硬编码 | `supply_chain/manager.py` | §3.1, §4.1 |
| **P0-7** | `daily_scheduler.py` + `enable_pilot_cv.py` PILOT_STORES 改为配置项 | 2文件 | §4.1 |
| **P0-8** | 桩接口字段统一为 5 枚举值: `not_connected/disabled/simulated/pending_integration/error` | `device_stub.py`, `admin.py`, `waste_estimate.py` | §7.2, HC-8 |
| **P0-9** | AgentConfig 扩展四维字段: `permissions/push_config/approval_config` | `models.py` AgentConfig | §6.1, HC-9 |

### P1 — 重要（破坏通用性，展会前应力争完成）

| # | 整改项 | 影响范围 |
|---|--------|----------|
| **P1-1** | docker-compose 默认 IP `192.168.2.85` → `$\{HOTPOT_HUB_HOST\}` | `deploy/edge/`, `deploy/jetson/` |
| **P1-2** | 配置文件公网 IP `43.139.143.12` → 环境变量占位 | `ipc_config_jiaojiang.yml`, `pipeline_config_jiaojiang.yml`, `edge_config.yml` |
| **P1-3** | 测试文件 25+处 `store_jiaojiang` → pytest fixture 参数化 | `tests/*.py` |
| **P1-4** | 核心表添加 `tenant_id`/`brand_id`/`region_id` 列 + migration | `pg_db.py` 多表 |
| **P1-5** | POS bridge 店名映射 → 从 DB 动态查询 | `pos_bridge.py` |
| **P1-6** | AgentGateway UserContext 添加 `tenant_id`/`store_id`/`region_id` | `agent_gateway.py` |
| **P1-7** | daily_scheduler 店名映射 → 从 DB 动态查询 | `daily_scheduler.py` |
| **P1-8** | 整改方案 §第八章版本同步: v1.6 → v1.8 | 通用化方案文档 |

### P2 — 优化（展后可迭代）

| # | 整改项 |
|---|--------|
| **P2-1** | 测试用例虚拟门店参数化（HC-10 前置条件） |
| **P2-2** | D2 AssistantTask 数据模型添加 `tenant_id`/`store_id` |
| **P2-3** | 事件上报 16 字段 pydantic Schema 强制校验 |
| **P2-4** | HC-10 虚拟门店四步验收自动化脚本 |
| **P2-5** | `pipeline_config_jiaojiang.yml` → 抽象为通用 store template |

---

## 五、特征矩阵：本分支已修复 vs 新增缺口

| 维度 | 前轮已修复 | 本轮新增缺口 | 备注 |
|------|:--------:|:--------:|------|
| 文档去店名 | ✅ | — | PRD/架构文档已完成 |
| 文档 IP/凭据 | ✅ | — | `{NVR_PASSWORD}`, `{HUB_URL}` |
| 代码 NVR 凭据 | ✅ | — | 环境变量化完成 |
| IoT 可插拔 | ✅ | — | 架构独立 |
| NL MVP 硬编码 | — | ❌ **新增** | Commit `63c289b` 引入 |
| DB DDL 默认值 | ❌ 遗留 | — | `DEFAULT 'store_jiaojiang'` 仍存在 |
| supply_chain 硬编码 | ❌ 遗留 | — | 10+ 处 store-jiaojiang |
| 测试硬编码 | ❌ 遗留 | — | 25+ 处 |
| 桩接口枚举 | ❌ 遗留 | — | 3 文件使用自造字段 |
| AgentConfig 四维 | ❌ 遗留 | — | 仅 Subscription，缺 3 维 |
| 事件 16 字段 | ❌ 遗留 | — | 实现率 19% |

**关键发现**: `feature/arch-design` 的"通用化改造"在**文档层基本达标**，但在**代码层存在明显的文档-实现鸿沟**。最新提交 `63c289b` (NL MVP) 非但没有缩小鸿沟，反而**新增了 6 项硬编码违规**。

---

## 六、工作量评估

| 优先级 | 文件数 | 核心工作 | 预估工时 | 风险 |
|:------:|:------:|------|:--------:|------|
| **P0** | ~12 | 去硬编码店名/模拟数据标记/枚举统一/AgentConfig扩展/DB默认值移除 | **8-12h** | NL MVP 需要重构 query_data 数据源从模拟→DB查询，可能阻塞其他 P0 项 |
| **P1** | ~18 | IP配置化/测试参数化/DB添加tenant列/Gateway扩展 | **6-8h** | DB migration 需兼容现有数据 |
| **P2** | ~8 | 参数化/校验/template | **4-6h** | 低风险 |
| **合计** | **~38** | | **18-26h** | **≈2.5~3.5 人天** |

### 最关键的单个修复

**NL MVP 重构** (P0-1~P0-4) 是整个整改清单中**最紧急且影响面最大**的单项。因为它：
1. 是展会演示流程的入口组件
2. 同时违反 5+ 项核心要求
3. 需要从"硬编码模拟数据"改造为"参数化真实数据源"
4. 涉及新增 `tenant_id` 上下文校验 + `source_status` 标记

建议 NL MVP 重构作为第一优先级，预计 3-4h 独立完成。

---

## 七、总体评审结论

**《火瞳系统设置与架构通用化修改方案》对 `feature/arch-design` 分支完全适用且必要。**

| 维度 | 评分 | 说明 |
|------|:----:|------|
| 文档层对齐 | 🟢 85% | PRD/架构文档已按方案完成整改，仅版本号微小偏差 |
| 代码层对齐 | 🔴 25% | 通用化基础设施几乎未落地；DB/Agent/事件均未达标 |
| 最新提交合规 | 🔴 10% | NL MVP `63c289b` 是"单店硬编码"模式的极致体现 |
| 整改紧迫性 | 🔴 高 | 展会前 P0+P1 合计 ~18h，时间窗口紧张 |

**核心矛盾**: 文档层的通用化改造（PRD §1.11, 整改方案 Ch8-12）与代码层实现之间存在显著鸿沟。PRD §1.11.7 自身已诚实记录"代码层 1/6 完成"，本评审验证了这一判断并在**NL MVP 领域发现了新的缺口**。

**建议执行策略**:
1. **立即**: 修复 NL MVP 硬编码 (P0-1~P0-4)，作为展会演示的入口组件不能带着违规上线
2. **本周内**: 完成 P0-5~P0-9（DB/枚举/AgentConfig），达成通用化代码基线
3. **展前**: 完成 P1-1~P1-8，实现配置驱动和测试参数化
4. **展后**: P2 优化项 + HC-10 虚拟门店验收

> ⚠️ **红线提醒**: 如果在展会前 P0 未全部修复，火瞳在展会上实际运行的仍是"单店·Demo·固定配置"系统，这与整改方案目标直接冲突，且违反 §1.11.2 和 §3.1 的默认门店规范。
