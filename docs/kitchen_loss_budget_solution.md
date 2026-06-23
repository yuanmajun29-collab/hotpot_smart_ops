# 后厨损耗预算 · 执行附录（接口契约冻结 + 执行细化）

> **⚠️ 优先级声明（SSOT）**：本文是 [kitchen_loss_real_device_solution.md](kitchen_loss_real_device_solution.md) 的**从属执行附录**，不是独立方案。
> 凡硬件选型、分期、ADR、采购、验收口径，**一律以 SSOT 与 ADR-019 为准**；本附录只补充 SSOT 未细化的两类内容：
> ① 新增接口的**字段级契约冻结**；② Phase 1 特征**持久化口径**与离线降级口径的细化。
> 如本附录与 SSOT 冲突，以 SSOT 为准并应修正本附录。

| 项目 | 内容 |
|------|------|
| 日期 | 2026-06-21（V0.2 · 经 Codex PK 收敛） |
| SSOT | [kitchen_loss_real_device_solution.md](kitchen_loss_real_device_solution.md) |
| 决策记录 | ADR-016 / ADR-017 / **ADR-019**（真实设备接入 Profile，已存在，本文为其契约补充） |
| 试点 | 单店优先 `store_yuhuan` → 复制 `store_jiaojiang`（同 SSOT，**不**并行双店） |
| 票号 | 统一沿用 SSOT 的 **LOSS-501~508**（见 §1 对齐表，原 LOSS-410~452 作废） |

---

## 1. 票号与口径对齐（作废本文早期的平行编号）

本文 V0.1 曾引入平行的 `LOSS-410~452` 与平行分期/硬件，**已与 SSOT 冲突，全部作废**，改为引用 SSOT：

| 早期（已废） | 收敛后归口 | 说明 |
|--------------|-----------|------|
| LOSS-410/411（POS/ERP 真连） | SSOT P0/P1A · LOSS-502 | 设备/数据真实接入归 SSOT |
| LOSS-412（师傅 3 按钮打分） | SSOT P1A · LOSS-503 + 本文 §2.2 契约 | quality-tap 端点 |
| LOSS-420（feature builder） | SSOT P1B · LOSS-504 + 本文 §3 持久化 | snapshot 持久化口径细化 |
| LOSS-421/422（forecast/loss-budget） | SSOT P1B · LOSS-505 + 本文 §2.1 契约 | loss-budget 端点 |
| LOSS-423/424（多时段调度/推送） | SSOT P1C · LOSS-507 | schedule profiles |
| LOSS-431（waste-estimate） | SSOT P1C/P2（VLM 留证→识别）+ 本文 §2.3 契约 | Phase 2，mock-first |
| LOSS-440~452（PG/对标/量产/模板） | SSOT P2 · LOSS-508 / ADR-018 | 不另起编号 |

---

## 2. 新增接口契约冻结（store-scoped · ADR-009 不变量）

通用约束（三端点共用）：
- **Store-scope**：均经 `auth.store_id` / `X-Store-Id` / `?store_id=` 解析；已认证用户访问非授权门店一律 **403**（ADR-009 跨店隔离不变量，`tests/test_store_isolation.py` 守）。
- **mock/stub/real 显式标注**：响应带 `source` 字段（`real` / `rule` / `rule+llm` / `mock`），便于前端与验收区分（Codex 反提③）。
- **失败降级**：外部依赖（LLM/VLM/真实设备）不可用时不报 500，降级到 `rule` / `mock` 并在 `source` 标注。

### 2.1 `GET /v1/cost/loss-budget` — 损耗预算（LOSS-505）

只读。在 `/v1/cost/loss-risk` 规则基线之上叠加预算/预测维度。

| 参数 | 类型 | 默认 | 说明 |
|------|------|------|------|
| `store_id` | query | auth | 缺省取登录门店；跨店 403 |
| `date` | query | 当日 | 预算日期（本地时区） |
| `limit` | query | 10 | TopN |

响应：
```json
{
  "store_id": "store_yuhuan",
  "date": "2026-06-21",
  "generated_at": "2026-06-21T15:00:00+08:00",
  "source": "rule+llm",
  "items": [
    {
      "sku": "毛肚",
      "forecast_qty": 15.0,
      "forecast_unit": "份",
      "budget_loss_amount": 42.0,
      "actual_loss_amount": null,
      "variance_pct": null,
      "reason": "近7天均耗13份，今晚预订桌+雨天上调",
      "suggested_action": "备15份，雨天+10%",
      "ref_type": "loss_feature_snapshot",
      "ref_id": "store_yuhuan:2026-06-21"
    }
  ],
  "budget_loss_amount_total": 42.0,
  "actual_loss_amount_total": null
}
```
- `forecast_qty/forecast_unit`：备货建议量；预测 agent 会校验 `forecast_qty` 必须为有限、非负数，非法/缺失预测被丢弃。LLM 不可用或全部预测无效时为 `null`，`source="rule"`；至少一条有效预测命中时为 `source="rule+llm"`。
- `actual_loss_amount/variance_pct`：次日复盘回填，当日请求时为 `null`（预算→实际→偏差闭环）。
- **自动化验收测试**（LOSS-505 已实现）：`tests/test_loss_budget.py` + `tests/test_loss_forecast.py` —（a）store-scope 403；（b）无 LLM 时 `source="rule"` 且不 500；（c）含实际值时 `variance_pct` 计算正确；（d）字段齐全；（e）LLM JSON 解析、数值边界、异常降级与 `source="rule+llm"`。

### 2.2 `POST /v1/receiving/quality-tap` — 师傅手动品质打分（LOSS-503）

写入。VLM 自动验货前的过渡输入（wedge §8.3），作为损耗预测因子。

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `store_id` | body | 否 | 缺省取登录门店；跨店 403 |
| `batch_id` | body | 是 | 关联收货批次 |
| `sku` | body | 否 | 食材 |
| `grade` | body | 是 | `good` / `normal` / `poor` |
| `actor_id` | body | 否 | 缺省取登录身份 |
| `note` | body | 否 | 备注 |

行为：写事件 `event_type="receiving_quality_tap"`（metadata 含 `ref_type="receiving_batch"`、`ref_id=batch_id`）；`grade` 映射到 loss-risk 既有等级体系（`good→A`、`normal→B`、`poor→D`，`D` 触发 `_LOW_GRADES` 风险）。

响应：`{ "ok": true, "event_id": "...", "batch_id": "...", "grade": "poor", "mapped_grade": "D", "source": "real" }`
- **权限**：收货写权限（RBAC `receiving` 域），非授权角色 403。
- **自动化验收测试**（LOSS-503 已实现）：`tests/test_quality_tap.py` —（a）grade→mapped_grade 映射；（b）写入后 loss-risk 能读到该批次品质风险；（c）跨店 403；（d）非法 grade 422；（e）先打分后收货提交仍合并同批次成本项。

### 2.3 `POST /v1/vlm/waste-estimate` — 废料识别（P1C/P2，mock-first）

写入。**Phase 2 能力**，Phase 1 不承诺；契约先冻结，实现 mock-first（无边缘 VLM 时返回 `source="mock"` 或回退手动打分 §2.2）。

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `store_id` | body | 否 | 缺省取登录门店；跨店 403 |
| `image_ref` | body | 二选一 | 关键帧图片引用 |
| `stream_id` | body | 二选一 | 边缘视频流标识 |
| `ts` | body | 否 | 采集时间 |

响应：
```json
{
  "ok": true, "store_id": "store_yuhuan", "source": "mock", "model": "qwen2.5-vl-3b",
  "items": [{"waste_type": "毛肚边角", "estimated_portion": 0.8, "unit": "份", "confidence": 0.62}]
}
```
- **降级**：边缘 VLM 不可用 → `source="mock"`，或提示改用 §2.2 手动 3 按钮打分。
- **自动化验收测试**（VLM-603 已实现）：`tests/test_waste_estimate.py` —（a）store-scope 403；（b）无 VLM 时 `source="mock"` 不 500；（c）`image_ref`/`stream_id` 至少一项，缺失 422；（d）写入事件并刷新 `loss_features.waste_evidence`。

### 2.4 已实现端点（保持不变）

`GET /v1/cost/loss-risk`（LOSS-402）= 只读规则基线契约，**保持现状**（`domain/loss_risk.py`），由 LOSS-505 在其上叠加预算/预测，不改其既有字段。

---

## 3. Phase 1 特征持久化口径（Codex 反评③：snapshot 必须持久化）

| 项 | 收敛口径 |
|----|----------|
| Phase 1（P1B/LOSS-504）存储 | **持久化到 `store_snapshots(kind="loss_features")`**（`db.py`/`pg_db.py` 已有该表，`INSERT OR REPLACE` by store_id+kind），或 append-only `events`/OpsEvent；**不**用临时进程内 JSON |
| Phase 1（P1B/LOSS-504）HTTP | **`GET /v1/cost/loss-features`** 读 snapshot；**`POST /v1/cost/loss-features/rebuild`** 从 cost 重建并持久化（`tests/test_loss_features_api.py`） |
| 复用既有 | 优先复用 `receiving_batches`、`iot_readings`、`store_snapshots.cost`（见 `architecture_data_model_phase1.md` §line184） |
| 关系表延后 | `loss_features` / `loss_predictions` 独立表延后到 **P2 · LOSS-508**：pay-test 通过或需跨天回放/模型对比时再落 |

> 修正 V0.1「暂不建表、临时 JSON」的表述：snapshot-first 正确，但 Phase 1 起就落 `store_snapshots`/events 作为持久化边界，避免重启丢特征。

---

## 4. 硬件口径对齐（以 SSOT §4 / ADR-017 / ADR-019 为准）

本附录**不**维护独立硬件表。纠正 V0.1 的错误口径：

| V0.1 错误 | 收敛后（与 SSOT 一致） |
|-----------|------------------------|
| Jetson Orin Nano 8GB = **40 TOPS** | **Jetson Orin Nano Super 8GB = 67 INT8 TOPS**（NVIDIA 官方，SSOT §9 来源） |
| 立即采购 **2× Jetson**（双店各 1） | Jetson 8GB **仅开发/原型**；按需 **1 台** dev kit 用于实验/Demo，**pay-test 后**再定；不默认双店各买 |
| 量产默认 Jetson | **量产默认 RK3588 16GB + 工业 IoT 网关 + 云 LLM / YOLO-first**（SSOT §4.1） |
| 自拟双店 BOM | 以 SSOT §4.2 单店 P1A 必选设备 + §10 最小采购建议为准 |

---

## 5. 离线/断网口径细化（Codex 反评⑥）

拆分两个不同概念，避免把「传感器补传」与「完整离线营业」混为一谈：

| 能力 | 口径 | 阶段 |
|------|------|------|
| 传感器 store-and-forward | IoT/摄像头/POS 接入**必须**有短时本地缓冲 + 断线重连 + replay 安全（不丢读数） | P1A 即要求（设备级） |
| 完整 24h 离线业务运行 | **不**作为 Phase 2 硬验收闸，除非客户合同要求且有压测背书（ADR-008 维持 P1.5 降级口径） | 按合同 |

---

## 6. 收敛记录（对 Codex PK 7 点的处置）

| Codex 点 | 处置 |
|----------|------|
| ① SSOT 统一 | 本文降级为 SSOT 从属附录（顶部声明）；平行编号/分期/硬件作废（§1、§4） |
| ② 硬件纠正 | 67 INT8 TOPS、8GB 仅开发、RK3588 16GB 量产默认、不立即买双 Jetson（§4） |
| ③ 特征持久化 | Phase 1 落 `store_snapshots(kind="loss_features")`/events，关系表延后 LOSS-508（§3） |
| ④ 接口冻结 | loss-budget / quality-tap / waste-estimate 字段+store-scope+降级+验收测试冻结（§2） |
| ⑤ ADR-019 | 措辞改为**扩展/补充已存在的 ADR-019**，非新增（全文及 SSOT 关联） |
| ⑥ 离线 24h | 拆分 store-and-forward 与完整离线；后者非 Phase 2 硬闸（§5） |
| ⑦ 收敛动作 | 本文转附录 + SSOT/ADR-019 加指针；不 push commit 562a72e as-is，另起收敛提交 |
