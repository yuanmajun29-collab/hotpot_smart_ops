# ADR-003: SupplyChainManager JSON→Hub PG 迁移计划

> **状态**: Draft | **日期**: 2026-08-04 | **关联**: 整改方案v1.0 §四(P0-1)、ADR-002(Edge写入隔离)

---

## 1. 问题定义

### 1.1 当前状态

`SupplyChainManager` (`hotpot_platform/cloud/supply_chain/manager.py`) 存在**双轨写入**机制：

| 路径 | 方法类型 | 数据库 | 承载实体 |
|------|---------|--------|---------|
| **实例方法** | `def xxx(self)` | SQLite/PG (`self._db`) | 供应商(S04)、收货PG、采购PG |
| **类方法** | `@classmethod` xxx(`cls`) | JSON (`product_master.json`) | 货品(S01)、收货JSON、采购JSON、任务、建议、评分 |

### 1.2 核心瓶颈

`_save_to_json()` 被调用 **48 处**，覆盖 **9 种业务实体**：

| 实体 | `_save_to_json()` 调用数 | 类别 | ADR-002 级别 |
|------|:---:|------|:---:|
| 货品 S01 (CRUD+锁+变更) | 7 | 主数据 | L2-必须迁移 |
| 收货 S02 (创建→审批全流程) | 10 | 业务数据 | L2-必须迁移 |
| 采购 S03 (CRUD→确认→取消) | 9 | 业务数据 | L2-必须迁移 |
| AI 助理任务/建议 | 6 | 任务数据 | L2-必须迁移 |
| Demo/种子数据加载 | 3 | 测试数据 | L1-可保留 |
| 供应商评分快照 | 3 | 分析数据 | L2-必须迁移 |
| 其他 (状态变更等) | ~10 | 混合 | 逐案评估 |
| **合计** | **48** | | **45处L2** |

### 1.3 风险

- **数据一致性**: 同一实体可能同时存在于 JSON 和 PG，无同步机制
- **并发安全**: JSON 无事务、无锁、无并发控制
- **审计断裂**: JSON 写入不走 PG 审计链
- **部署风险**: 文件系统依赖 vs 数据库 ACID 保证

---

## 2. 迁移策略

### 2.1 原则

1. **渐进式迁移**: 不一次性删除 JSON 路径（风险太高）
2. **双写过渡期**: JSON + Hub PG 同时写，验证一致后切单写
3. **向后兼容**: Edge UI 离线模式仍需 JSON fallback
4. **模块化推进**: 按业务域逐个模块迁移，非大爆炸式重写

### 2.2 三阶段路线图

```
Phase 1 (本次): 开关 + 弃用警告 + 桩方法     ←── 你在这里
    ↓
Phase 2 (下一步): 逐模块迁移 S01→S03→S02→AI   ←~3-5天
    ↓
Phase 3 (展会后): 切单写 PG + 删除 JSON 路径   ←~2天
```

---

## 3. Phase 1 详细设计（本次执行）

### 3.1 新增类变量

```python
class SupplyChainManager:
    # ── 写入模式 (ADR-002 compliance) ──
    _write_mode: str = "json"          # "json" | "hub_pg" | "both"
    _hub_pg_available: bool = False    # Hub 连接检测标志
```

### 3.2 改造 `_save_to_json()`

```python
@classmethod
def _save_to_json(cls) -> None:
    """保存数据到 JSON 文件。

    .. deprecated:: 2026-08-04
        此方法将在 Phase 3 移除。新代码应使用 Hub PG 写入路径。
        见 ADR-002 (Edge写入隔离与Hub主写约定) 和 ADR-003 (本文件)。
    """
    import warnings
    if cls._write_mode == "hub_pg":
        logger.debug("[ADR-002] JSON写入已跳过 (_write_mode=hub_pg)")
        return

    if cls._write_mode in ("json", "both"):
        # ... 原有逻辑不变 ...
        if cls._write_mode == "both":
            warnings.warn(
                "[ADR-002] 双写模式: 数据同时写入JSON和Hub PG",
                DeprecationWarning,
                stacklevel=2,
            )
```

### 3.3 新增 `_save_to_hub_pg()` 桩方法

```python
@classmethod
def _save_to_hub_pg(cls, entity_type: str, operation: str, data: Dict) -> bool:
    """将业务数据写入 Hub PostgreSQL (Phase 2 实现)。

    Args:
        entity_type: "product" | "receiving" | "purchase_order" | "task" | "suggestion"
        operation: "create" | "update" | "delete"
        data: 要写入的数据字典

    Returns:
        True 如果写入成功

    TODO (Phase 2):
        - 通过 Hub REST API 或直连 PG 写入
        - 加入 JWT 认证头
        - 加入审计字段 (operator, store_id, timestamp)
        - 异步批量写入优化
    """
    logger.warning("[ADR-003] _save_to_hub_pg 尚未实现 (桩方法)")
    return False
```

### 3.4 各 CRUD 方法的改造模板

每个调用 `_save_to_json()` 的类方法，在 Phase 1 只需加一行日志：

```python
@classmethod
def create_product_master(cls, req, operator="") -> ProductMaster:
    # ... 原有逻辑 ...

    cls._product_cache[sku] = product
    cls._save_to_json()  # <-- 不改这行，只改内部行为

    # 新增: Hub PG 双写 (Phase 2 启用)
    if cls._write_mode in ("both", "hub_pg"):
        cls._save_to_hub_pg("product", "create", product.model_dump())

    return product
```

### 3.5 配置开关

```bash
# 环境变量控制写入模式
export HOTPOT_SUPPLY_CHAIN_WRITE_MODE=json      # 默认(当前)
# export HOTPOT_SUPPLY_CHAIN_WRITE_MODE=hub_pg   # Phase 3
# export HOTPOT_SUPPLY_CHAIN_WRITE_MODE=both     # Phase 2 过渡
```

---

## 4. Phase 2 迁移顺序（下一步）

### 4.1 优先级矩阵

| 顺序 | 模块 | 调用数 | 复杂度 | 原因 |
|:---:|------|:---:|:---:|------|
| **1** | S01 货品主数据 | 7 | 低 | 结构简单，无状态机 |
| **2** | S03 采购订单 | 9 | 中 | 有状态机但路径清晰 |
| **3** | S02 收货质检 | 10 | 高 | VLM集成+审批流+照片 |
| **4** | AI 助理任务/建议 | 6 | 中 | 相对独立 |
| **5** | 供应商评分 | 3 | 低 | 分析结果，可异步 |

### 4.2 每个 Phase 2 子阶段的标准流程

```
1. 为该模块新建 Hub PG 表（如不存在）
2. 在 _save_to_hub_pg() 中实现该实体的写入逻辑
3. 将 _write_mode 切换为 "both"
4. 运行完整测试套件
5. 对比 JSON 和 PG 数据一致性（脚本自动化）
6. 验证通过后切换为 "hub_pg"
7. 清理该模块的 JSON 缓存代码
```

---

## 5. Phase 3 收尾（展会后）

1. 删除 `_save_to_json()` 方法及所有调用
2. 删除 `_load_from_json()` 方法
3. 删除 `_data_file` 相关初始化逻辑
4. `init_product_data()` 改为从 Hub API 加载种子数据
5. Demo 数据加载改为直接写 Hub PG
6. 更新 CLAUDE.md 和对齐表标记 "Edge本地JSON路径已移除"

---

## 6. 验收标准

### Phase 1 验收
- [ ] `_save_to_json()` 在 `hub_pg` 模式下跳过执行
- [ ] `json` 模式行为完全不变（向后兼容）
- [ ] `both` 模式同时写两路 + 发出 DeprecationWarning
- [ ] T1-T4 70 测试全部通过
- [ ] 环境变量 `HOTPOT_SUPPLY_CHAIN_WRITE_MODE` 可控

### Phase 2 验收（每模块）
- [ ] 该模块所有 CRUD 操作写入 Hub PG
- [ ] JSON ↔ PG 数据一致性 < 100% (自动化对比脚本)
- [ ] 断网降级到 JSON 本地仍可用
- [ ] 审计日志包含该模块操作记录

### Phase 3 验收
- [ ] 零 `_save_to_json()` 调用残留
- [ ] 零 `product_master.json` 文件生成
- [ ] 全量测试通过（含新的 PG 集成测试）
- [ ] ADR-002 合规检查通过

---

## 7. 风险与回滚

| 风险 | 概率 | 影响 | 缓解措施 |
|------|:---:|:---:|------|
| PG 写入失败导致数据丢失 | 中 | 高 | 双写期保留 JSON fallback |
| 性能退化（每次 CRUD 都写 PG） | 中 | 中 | 异步批量写入 + 内存缓存 |
| Edge UI 离线模式不可用 | 低 | 高 | 检测网络状态，离线自动切 JSON |
| 48 处调用遗漏修改 | 低 | 中 | grep 自动化扫描 |

**回滚方案**: 设置 `HOTPOT_SUPPLY_CHAIN_WRITE_MODE=json` 即可立即回退到原始行为。

---

## 8. 关联文档

- **整改方案 v1.0**: `docs/01-核心权威/火瞳_整改方案_v1.0_20260804.md` §四(P0-1)
- **ADR-002**: `docs/04-技术设计/ADR-002_Edge写入隔离与Hub主写约定.md`
- **差距矩阵**: Step 1 交付物（可视化矩阵）
- **PRD 对齐表**: `docs/04-技术设计/PRD_V5_3i_CODE_ALIGNMENT.md`
