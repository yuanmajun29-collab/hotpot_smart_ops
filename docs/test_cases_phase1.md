# Phase 1 测试用例（全产品 7 模块）

**冯校长火锅 · 智能运营 · 基于 PRD F-xxx 与架构设计整理**

| 项目 | 内容 |
|------|------|
| 版本 | V1.1（定稿归档） |
| 日期 | 2026-06-18 |
| 范围 | 7 业务模块 + F-TASK + PDA + 层级/驾驶仓 + Admin + 跨切面 |
| 依据 | [product_design.md §5/§12](product_design.md) · [architecture_api_spec.md](architecture_api_spec.md) · [phase1_mvp_acceptance_checklist.md](phase1_mvp_acceptance_checklist.md) |
| 自动化 | `tests/`（93 passed） |
| 归档 | V1.1 定稿基线 · 2026-06-18 · 已链入 [product_design_index](product_design_index.md) 与 README |

---

## 1. 约定

### 1.1 用例 ID

`TC-<模块>-<序号>`，模块码：`HOME/TBL/KIT/SOP/TASK/COST/SALE/ALT/RPT/PDA/HQ/ADM/SEC/NFR`。

### 1.2 字段

| 字段 | 含义 |
|------|------|
| 关联 F | 对应 PRD 功能 ID |
| 优 | 优先级（沿用 PRD：P0 Must / P1 Should / P1.5 / P2 Could） |
| 类型 | 功能 / 接口 / 权限 / 边界 / 异常 / UAT |
| 自动化 | 对应 `tests/` 测试函数；`—` = 当前手工/UAT；`mock` = 依赖真数据接入后转真 |

### 1.3 状态图例

✅ 已自动化 · 🔶 部分（mock/桩） · ⬜ 手工/UAT 待执行

---

## 2. 追溯矩阵（F-xxx → 用例 → 自动化）

| 模块 | F 范围 | 用例段 | 自动化覆盖 | 状态 |
|------|--------|--------|------------|------|
| 首页 Home | F-H01~H04 | TC-HOME-* | health/metrics/summary | 🔶 |
| 桌态 Tables | F-T01~T07 | TC-TBL-* | summary tables / table_correct RBAC | 🔶 |
| 厨房 IoT | F-K01~K07 | TC-KIT-* | iot readings / 门磁规则 | 🔶 |
| SOP | F-S01~S08 | TC-SOP-* | sop assign / RAG | 🔶 |
| 任务 Task | F-TASK01~04 | TC-TASK-* | （兼容写入）sop assign | 🔶 |
| 成本 Cost | F-C01~C06 | TC-COST-* | receiving cost / VLM grade / 拒收 | 🔶 |
| 推销 Sales | F-SALES01~03 | TC-SALE-* | — | ⬜ P2 |
| 告警 Alerts | F-A01~A06 | TC-ALT-* | ack / webhook / 静默 | 🔶 |
| 日报 Report | F-R01~R05 | TC-RPT-* | 生成/列表/推送 | 🔶 |
| 追溯 Trace | F-TRACE01~02 | TC-TASK-TR* | — | ⬜ P2 |
| PDA 收货 | F-P01~P07 | TC-PDA-* | receiving submit / 双签 / 重复 | 🔶 |
| 层级/驾驶仓 | F-HQ01/06/07/12/13 · F-EXEC01 | TC-HQ-* | region/zone/national/benchmark/cockpit | ✅/🔶 |
| 运营后台 | F-HQ08~11 · F-HQ02~05 | TC-ADM-* | admin CRUD（内存桩）/ 审计 | 🔶 |
| 安全/权限 | RBAC · 多租户 · /v1 · 鉴权 | TC-SEC-* | rbac/tenant/v1 alias/auth_mode | ✅ |
| 非功能 | 性能/延迟/可用 | TC-NFR-* | — | ⬜ 真链路待测 |

---

## 3. 首页 Home（F-H01~H04）

| TC | 关联 F | 优 | 类型 | 前置 | 步骤 | 预期 | 自动化 |
|----|--------|----|------|------|------|------|--------|
| TC-HOME-01 | F-H01 | P0 | 接口 | Hub 启动 | `GET /health` | 200；`status=ok`，含 multi_tenant/engine/db_backend/auth_mode/uptime | `test_health` |
| TC-HOME-02 | F-H01 | P0 | 接口 | 已鉴权 | `GET /metrics` | 200；store_count、stores_with_data、total_events、total_critical | `test_metrics` |
| TC-HOME-03 | F-H02 | P0 | 功能 | 门店有事件 | `GET /v1/summary?store_id=store_yuhuan` | 返回 KPI：严重告警数/待清台/SOP 率/成本偏差 | `test_post_event_and_summary` |
| TC-HOME-04 | F-H02 | P0 | 边界 | 新建空门店 | `GET /v1/summary` 空店 | total_events=0，KPI 归零不报错 | `test_empty_store_summary_is_zero` |
| TC-HOME-05 | F-H03 | P1 | UAT | 登录看板 | 点 6 宫格快捷入口 | 跳转桌态/SOP/成本/IoT/告警/日报 | ⬜ |
| TC-HOME-06 | F-H04 | P1 | 功能 | 有午/晚市数据 | 切换 noon/evening | 数据按班次过滤 | ⬜ |

---

## 4. 桌态 Tables（F-T01~T07）

| TC | 关联 F | 优 | 类型 | 前置 | 步骤 | 预期 | 自动化 |
|----|--------|----|------|------|------|------|--------|
| TC-TBL-01 | F-T01 | P0 | 功能 | 已写入桌态 | `GET /v1/tables` | 返回各桌状态（need_clean/checkout 等）回读一致 | `test_get_tables_returns_states` |
| TC-TBL-02 | F-T02 | P0 | UAT | 看板打开 | 等待 ≤5s | 桌态轮询刷新（≤5s） | ⬜ mock |
| TC-TBL-03 | F-T03 | P0 | 功能 | 多桌不同态 | turnover_suggestions 排序 | 优先级 need_clean>checkout>empty，dining 排除，动作文案正确 | `test_turnover_priority_ordering_and_actions` / `test_turnover_same_priority_sorted_by_table_id` |
| TC-TBL-04 | F-T05 | P1 | 功能 | VLM 桩 | 查询清台就绪分 | 0~100 分 + 截图（Phase 1 mock） | 🔶 mock |
| TC-TBL-05 | F-T06 | P1 | 权限 | 收货员 token | `POST /tables` 改桌态 | 403 `table_correct` 禁止 | `test_table_correct_forbidden_for_receiver` |
| TC-TBL-06 | F-T06 | P1 | 功能 | 领班 token | `POST /v1/tables` 纠正 | 200，状态持久化（need_clean 生效） | `test_table_correct_allowed_for_lingban` |
| TC-TBL-07 | F-T04/T07 | P1/P2 | UAT | — | 单桌详情/等位预测 | 状态时间线 / 等位预计 | ⬜ |

---

## 5. 厨房 IoT（F-K01~K07）

| TC | 关联 F | 优 | 类型 | 前置 | 步骤 | 预期 | 自动化 |
|----|--------|----|------|------|------|------|--------|
| TC-KIT-01 | F-K01 | P0 | 接口 | — | `POST /v1/iot/readings/batch` 写温湿度 → `GET /v1/iot/readings` | 写入条数正确，按 sensor_id/hours 查询返回曲线 | `test_iot_readings_batch_and_query` |
| TC-KIT-02 | F-K02 | P0 | 功能 | 门开事件 | 门磁开启超阈值 | 触发超时告警；关门清除追踪 | `test_door_timeout_tracker_fires_after_threshold` / `test_door_closes_clears_tracker` |
| TC-KIT-03 | F-K02 | P0 | 接口 | MQTT 桩 | 解析门磁 payload | 正确解析开/关状态 | `test_parse_door_open` |
| TC-KIT-04 | F-K03 | P0 | 功能 | IoT 摘要 | 食材三阶段快照 | 来料→保存→加工卡片 + 异常高亮 | 🔶 mock |
| TC-KIT-05 | F-K04 | P0 | 异常 | 燃气/烟雾事件 | 写入 critical IoT 事件 | critical 级 + 推送（见 TC-ALT-03） | 🔶 mock |
| TC-KIT-06 | F-K05 | P1 | 功能 | CV 桩 | 穿戴合规事件 | 未戴帽事件列表 + 截图 | 🔶 mock |
| TC-KIT-07 | F-K07 | P1 | 功能 | 传感器离线 | 查询设备在线率 | 离线传感器清单 | ⬜ |

---

## 6. SOP（F-S01~S08）

| TC | 关联 F | 优 | 类型 | 前置 | 步骤 | 预期 | 自动化 |
|----|--------|----|------|------|------|------|--------|
| TC-SOP-01 | F-S01~S03 | P0 | 功能 | 已写入 SOP 统计 | `GET /v1/sop` | 合规率回读一致（7 卡片/截图仍 mock） | 🔶 `test_get_sop_returns_compliance` |
| TC-SOP-02 | F-S04 | P0 | 接口 | 有违规项 | `POST /v1/sop/assign` 指派整改 | 200，生成 assignment + sop_assigned 事件 | `test_sop_assign_create_and_list` |
| TC-SOP-03 | F-S06 | P1 | 接口 | 已指派 | `PUT /v1/sop/assignments/{id}/status` | 状态流转 pending→处理→复核 | `test_sop_assign_status_update` |
| TC-SOP-04 | F-S04 | P0 | 权限 | 前厅领班 token | `POST /v1/sop/assign` | 403 `sop_assign` 禁止 | `test_sop_assign_forbidden_for_lingban` |
| TC-SOP-05 | F-S07 | P1 | 功能 | RAG 规则后端 | `POST /sop/ask` 提问 | 返回 SOP 知识答案（rule 命中） | `test_sop_ask` / `test_sop_answer_rule` / `test_sop_search_receiving` |
| TC-SOP-06 | F-S07 | P1 | 边界 | 未知问题 | `POST /sop/ask` 无关问题 | 优雅兜底，无命中提示 | `test_sop_unknown_query` |
| TC-SOP-07 | F-S05 | P0 | 功能 | — | 关键项人工签字 | PDA/Web 确认 + 时间戳（见 TC-PDA-04） | `test_receiving_submit_requires_dual_signatures` |
| TC-SOP-08 | F-S08 | P2 | UAT | PMO | SOP 版本 OTA | 版本号 + 生效时间 | ⬜ P2 |

---

## 7. 任务 Task（F-TASK01~04 · P1.5）

| TC | 关联 F | 优 | 类型 | 前置 | 步骤 | 预期 | 自动化 |
|----|--------|----|------|------|------|------|--------|
| TC-TASK-01 | F-TASK01 | P1.5 | 功能 | feature flag on | 创建统一任务 | 支持 pending/in_progress/submitted/closed/cancelled | ⬜ P1.5 |
| TC-TASK-02 | F-TASK02 | P1.5 | 功能 | 任务带 due_at | 计算 SLA | overdue/escalated 派生标记（非主状态） | ⬜ P1.5 |
| TC-TASK-03 | F-TASK03 | P1.5 | 接口 | 任务流转 | 查 task_events | 记录 create/submit/reopen/cancel/reassign | ⬜ P1.5 |
| TC-TASK-04 | F-TASK04 | P1.5 | 接口 | — | `POST /v1/sop/assign` | 兼容写入 tasks，旧 SOP 指派不断链 | 🔶 `test_sop_assign_create_and_list` |
| TC-TASK-TR1 | F-TRACE01~02 | P2 | 功能 | — | 按 ref_type/ref_id/trace_id 追溯 | 串联 OpsEvent/tasks/签字/日报 | ⬜ P2 |

---

## 8. 成本 Cost（F-C01~C06）

| TC | 关联 F | 优 | 类型 | 前置 | 步骤 | 预期 | 自动化 |
|----|--------|----|------|------|------|------|--------|
| TC-COST-01 | F-C01 | P0 | 功能 | 已写入成本 | `GET /v1/cost` | 来料批次 items 回读（SKU/偏差） | `test_get_cost_returns_items` / `test_receiving_updates_cost_snapshot` |
| TC-COST-02 | F-C02 | P0 | 边界 | 短重 >3% | 提交偏差批次 | variance_pct 计算正确，>3% 标 warn | `test_receiving_submit_success`（variance） |
| TC-COST-03 | F-C03 | P0 | 功能 | VLM 桩 | 外观分级 | A/B/C/D 等级 + 截图 | `test_quality_grade_rule` |
| TC-COST-04 | F-C04 | P0 | 功能 | 低等级批次 | 拒收建议 | LLM/规则一句拒收理由 | `test_review_rule` |
| TC-COST-05 | F-C05 | P1 | 功能 | 领料/出成秤 | 出成率 | 改刀损耗量化 | ⬜ |
| TC-COST-06 | F-C06 | P2 | UAT | PMO | 供应商累计 KPI | 区域/全国榜单 | ⬜ P2 |

---

## 9. 推销 Sales（F-SALES01~03 · P2）

| TC | 关联 F | 优 | 类型 | 步骤 | 预期 | 自动化 |
|----|--------|----|------|------|------|--------|
| TC-SALE-01 | F-SALES01 | P2 | 功能 | 按桌态/时段生成推销建议 | 规则命中生成建议，不自动触达顾客 | ⬜ P2 |
| TC-SALE-02 | F-SALES02 | P2 | 权限 | 编辑话术库 | 仅 marketing_ops 可编辑，PMO 可审计 | ⬜ P2 |
| TC-SALE-03 | F-SALES03 | P2 | 功能 | 推销任务下发 | 生成 F-TASK 任务，门店人工确认 | ⬜ P2 |

---

## 10. 告警 Alerts（F-A01~A06）

| TC | 关联 F | 优 | 类型 | 前置 | 步骤 | 预期 | 自动化 |
|----|--------|----|------|------|------|------|--------|
| TC-ALT-01 | F-A01/A02 | P0 | 接口 | 有事件 | `GET /v1/events?level=critical` | 按时间倒序，仅返回 critical | `test_events_level_filter_returns_only_critical` |
| TC-ALT-02 | F-A03 | P0 | 权限 | 领班 ack / 收货员 ack | `POST /alerts/ack` | 领班 200 留痕；收货员 403 `ack` | `test_ack_allowed_for_lingban_forbidden_for_receiver` |
| TC-ALT-03 | F-A04 | P0 | 接口 | webhook 配置 | critical 事件触发推送 | 30s 内企微 webhook 发送 | `test_critical_event_triggers_webhook_e2e` |
| TC-ALT-04 | F-A04 | P0 | 接口 | — | `GET /alerts/routes` / `POST /alerts/test-push` | 路由状态（URL 脱敏）；测试推送成功 | `test_alerts_routes_and_test_push` |
| TC-ALT-05 | F-A06 | P1 | 边界 | warn 级事件 | 无 push flag 的 warn | 不推送（仅 critical 推） | `test_warn_not_pushed_without_flag` |
| TC-ALT-06 | F-A05 | P1 | 功能 | critical 30min 未 ack | `GET /v1/alerts/escalations` | 未 ack 老 critical 计入升级；新 critical 不计；ack 后清除 | `test_escalation_counts_unacked_old_critical` / `test_recent_critical_not_escalated` / `test_ack_clears_escalation` |
| TC-ALT-07 | F-A04 | P0 | E2E | 日报推送链路 | 日报 critical 推送 | webhook E2E 成功 | `test_daily_report_push_webhook_e2e` |

---

## 11. 日报 Report（F-R01~R05）

| TC | 关联 F | 优 | 类型 | 前置 | 步骤 | 预期 | 自动化 |
|----|--------|----|------|------|------|------|--------|
| TC-RPT-01 | F-R01/R02 | P0 | 接口 | 门店有数据 | `POST /v1/reports/daily/generate` | 生成 4 章（翻台/SOP/成本/安全）+ 整改清单 | `test_daily_report_generate_and_list` |
| TC-RPT-02 | F-R03 | P1 | 接口 | 已有日报 | 重新生成 | 手动触发刷新成功 | `test_daily_report_generate_and_list` |
| TC-RPT-03 | F-R04 | P1 | 接口 | 多日数据 | `GET /v1/reports/daily?limit=` | 按日期列表回看 | `test_daily_report_generate_and_list` |
| TC-RPT-04 | F-R01 | P0 | 权限 | 前厅领班 token | `POST /v1/reports/daily/generate` | 403 `report_generate` 禁止 | `test_daily_report_forbidden_for_lingban` |
| TC-RPT-05 | F-R01 | P0 | 权限 | 集团决策者 token | 生成日报 | 403（只读角色无 report_generate） | `test_report_generate_forbidden_for_decision_maker` |
| TC-RPT-06 | F-R01 | P0 | 功能 | scheduler on | 22:00 定时生成 | lifespan 启动调度，shutdown 优雅停 | 🔶（lifespan 已测启停） |
| TC-RPT-07 | F-R05 | P2 | UAT | PMO | 区域对标 narrative | LLM 跨店段落 | ⬜ P2 |

---

## 12. PDA 收货（F-P01~P07）

| TC | 关联 F | 优 | 类型 | 前置 | 步骤 | 预期 | 自动化 |
|----|--------|----|------|------|------|------|--------|
| TC-PDA-01 | F-P01 | P0 | 功能 | 有 PO | 扫/选今日 PO 批次 | 列表/扫码选批 | `test_fetch_po_orders` |
| TC-PDA-02 | F-P02/P03 | P0 | 接口 | — | `POST /v1/receiving/submit` 带重量/温度 | 200，写入批次 + cost 快照 | `test_receiving_submit_success` / `test_receiving_updates_cost_snapshot` |
| TC-PDA-03 | F-P05 | P0 | 功能 | 拍照 | VLM 外观分级 | 10s 内返回等级 | `test_quality_grade_rule` |
| TC-PDA-04 | F-P06 | P0 | 异常 | 单签 | 仅 1 个签字提交 | 拒绝：要求双人签字 | `test_receiving_submit_requires_dual_signatures` |
| TC-PDA-05 | F-P01 | P0 | 边界 | 重复批次 | 同 batch_id 重复提交 | 拒绝重复 | `test_receiving_duplicate_batch_rejected` |
| TC-PDA-06 | F-P06 | P0 | 接口 | 已提交 | `GET /v1/receiving/batches` / `/v1/audit/signatures` | 批次 + 签字审计可查 | `test_receiving_batches_and_audit_signatures` |
| TC-PDA-07 | F-P05 | P0 | 权限 | 收货员 token | `POST /v1/receiving/submit` | 200（收货员允许）；领班 403 | `test_receiving_submit_allowed_for_receiver` / `test_receiving_submit_forbidden_for_lingban` |
| TC-PDA-08 | F-P04/P07 | P1 | UAT | — | RFID 扫描 / 拒收留证 | 扫描提示 / 拍照 + 原因 | ⬜ |

---

## 13. 层级 / 驾驶仓（F-HQ01/06/07/12/13 · F-EXEC01）

| TC | 关联 F | 优 | 类型 | 前置 | 步骤 | 预期 | 自动化 |
|----|--------|----|------|------|------|------|--------|
| TC-HQ-01 | F-HQ06 | P1 | 接口 | 多店有数据 | `GET /v1/region/overview` | 区域 rollup + 门店健康度矩阵 + KPI | `test_region_overview_structure` / `test_region_overview_health_fields` |
| TC-HQ-02 | F-HQ07 | P1 | 功能 | 含异常店 | region overview anomaly | 食安/SOP/翻台/来料标红，支持下钻 | `test_region_overview_health_fields` |
| TC-HQ-03 | F-HQ06 | P1 | 接口 | 默认无参 | region overview 默认 | 默认返回 zone 维度 | `test_default_overview_is_zone` |
| TC-HQ-04 | F-HQ06 | P1 | 功能 | 多区数据 | zone rollup | 大区聚合正确 | `test_zone_east_china_rollup` |
| TC-HQ-05 | F-HQ01 | P1 | 接口 | — | `GET /v1/benchmark`（+legacy `/benchmark`） | 跨店翻台/SOP/成本/告警排名 | `test_benchmark_alias` / `test_benchmark_empty` |
| TC-HQ-06 | F-EXEC01/F-HQ12 | P1 | 接口 | tick 后 | `GET /v1/national/overview` | 全国 KPI rollup（驾驶仓/全国总揽共用） | `test_national_overview_after_tick` / `test_laoban_login_and_national_overview` |
| TC-HQ-07 | F-EXEC01 | P1 | 权限 | 集团决策者登录 | 登录 + 全国总揽 | 只读访问成功 | `test_laoban_login_and_national_overview` |
| TC-HQ-08 | F-HQ06 | P1 | 功能 | 健康度规则 | compute_store_health | critical 阈值正确判定 | `test_compute_store_health_critical` |
| TC-HQ-09 | F-HQ13 | P1 | UAT | — | national→zone→region→store 面包屑 | 下钻路径统一 | ⬜ 部分 |

---

## 14. 运营后台 Admin（F-HQ08~11 · F-HQ02~05）

| TC | 关联 F | 优 | 类型 | 前置 | 步骤 | 预期 | 自动化 |
|----|--------|----|------|------|------|------|--------|
| TC-ADM-01 | F-HQ08 | P0 | 接口 | PMO/IT token | `POST /v1/admin/stores` 建店 | 200，新店建租户 + org 树更新 | `test_admin_create_store` |
| TC-ADM-02 | F-HQ08 | P0 | 接口 | — | `GET /v1/admin/stores` / `/v1/admin/org-tree` | 门店列表 + 组织树（含 pipeline 状态） | `test_admin_stores_and_org_tree` |
| TC-ADM-03 | F-HQ08 | P0 | 权限 | 店长 token | 访问 admin 接口 | 403 admin 禁止 | `test_admin_forbidden_for_store_manager` |
| TC-ADM-04 | F-HQ08 | P0 | 权限 | 集团决策者 token | 访问 admin | 403（决策者非 admin） | `test_laoban_cannot_access_admin` |
| TC-ADM-05 | F-HQ09 | P0 | 接口 | PMO/IT | `GET /v1/admin/users` | 用户列表 + role + data_scope；店长越权 403 | `test_admin_users_list` / `test_admin_users_forbidden_for_store_manager` |
| TC-ADM-06 | F-HQ11 | P1 | 接口 | PMO | 建店后 `GET /v1/admin/audit-logs` | 配置/权限变更留痕可检索，count 增长 | `test_admin_audit_logs_record_store_creation` |
| TC-ADM-07 | F-HQ08 | P0 | 功能 | — | `POST /v1/admin/pipeline/tick` | 内存桩驱动 pipeline 推进 | `test_pipeline_tick_inprocess` |
| TC-ADM-08 | F-HQ02~05 | P1/P2 | UAT | PMO/IT | SOP/阈值/供应商/模型 OTA | 版本/生效/回滚 | ⬜ P2~3 |

---

## 15. 安全 / 权限 / 接口契约（跨切面）

| TC | 关联 | 优 | 类型 | 前置 | 步骤 | 预期 | 自动化 |
|----|------|----|------|------|------|------|--------|
| TC-SEC-01 | RBAC | P0 | 权限 | — | 后端 ROLE_ACTIONS ↔ `rbac.json` 对齐 | 各角色 actions 集合一致 | `test_backend_actions_match_dashboard_rbac_matrix` |
| TC-SEC-02 | RBAC | P0 | 功能 | — | 各角色 data_scope | 店长/领班/厨师长/收货员=store，督导=region，PMO/决策者=national | `test_role_data_scopes_cover_phase1_personas` |
| TC-SEC-03 | 鉴权 | P0 | 接口 | — | `POST /auth/token` 登录 | 返回 JWT + user（role/store/scope） | `test_auth_token` |
| TC-SEC-04 | 鉴权 | P0 | 接口 | token | `GET /v1/auth/me` | 返回身份 + 实时 auth_mode | `test_auth_me` |
| TC-SEC-05 | 鉴权 | P0 | 边界 | 不传 role | 登录无 role | 使用账号真实角色（不被强制覆盖） | `test_login_without_role_uses_demo_user_role` |
| TC-SEC-06 | 鉴权 | P0 | 异常 | role 不符 | 传错配 role 登录 | 403 角色不匹配 | `test_login_rejects_role_mismatch` |
| TC-SEC-07 | 鉴权 | P0 | 边界 | 运行时改 env | strict→unset 切换 | auth_mode() 调用时读取，反映实时值 | `test_auth_mode_reads_env_at_call_time` |
| TC-SEC-08 | 多租户 | P0 | 功能 | 两店数据 | 跨店读写 | store 隔离，互不串数据 | `test_tenant_isolation` |
| TC-SEC-09 | RBAC | P0 | 权限 | 收货员/领班/决策者 | 越权写操作 | 403（receiving/ack/table_correct/sop_assign/report_generate 按矩阵） | `test_*_forbidden_*`（7 条） |
| TC-SEC-10 | /v1 契约 | P1 | 接口 | — | `/v1/summary` vs `/summary` | 同 handler，响应体一致 | `test_v1_summary_alias_matches_legacy` |
| TC-SEC-11 | /v1 契约 | P1 | 接口 | — | legacy 路径响应头 | `Deprecation: true` | `test_legacy_has_deprecation_header` |
| TC-SEC-12 | /v1 契约 | P1 | 接口 | — | /v1 路径响应头 | 无 Deprecation 头 | `test_v1_has_no_deprecation_header` |
| TC-SEC-13 | 鉴权 | P0 | 前端契约 | 登录页 | 演示身份登录 | 前端不发送客户端 role；成功后只使用服务端 `user.role` | `test_dashboard_login_does_not_send_client_chosen_role` / `test_dashboard_login_uses_server_role_after_success` |
| TC-SEC-14 | 多租户 | P0 | 权限 | JWT token | 门店账号访问跨店读写/列表/metrics/rollup | 跨店读写 403；`/v1/stores`、`/v1/alerts/routes`、`/metrics` 仅本店；区域/全国 rollup 403 | `test_store_user_*` / `test_store_scoped_user_*`（9 条） |

---

## 16. 非功能 / NFR（性能 · 延迟 · 可用）

> 真链路（CV/IoT/webhook）接入后转真；当前以 mock/桩占位，验收阈值见架构 phase1 §NFR。

| TC | 指标 | 优 | 目标 | 验证方式 | 状态 |
|----|------|----|------|----------|------|
| TC-NFR-01 | 桌态推理延迟 | P0 | <1s（边缘） | YOLO/VLM 真实链路 benchmark | ⬜ 待 BL-01 |
| TC-NFR-02 | Hub API P95 | P0 | <200ms（摘要） | 压测 `/v1/summary` | ⬜ |
| TC-NFR-03 | critical 告警送达 | P0 | <30s 企微 | webhook SLA 脚本 `scripts/test_wechat_push_sla.py` | 🔶 |
| TC-NFR-04 | 断网边缘缓存 | P0 | 24h | DEV-105 离线队列 | ⬜ |
| TC-NFR-05 | VLM 层推理延迟 | P1 | 待实测固化 | feature flag 默认 off；AOI 外部基准仅参考（ADR-014） | ⬜ |

---

## 17. 覆盖度小结

| 维度 | 已自动化 | 部分/桩 | 手工/UAT/待真数据 |
|------|----------|---------|--------------------|
| 接口（Hub REST） | 高（93 passed） | iot/cv summary 桩 | — |
| 权限 RBAC + 多租户 | ✅ 完整 | — | — |
| /v1 契约 + 鉴权模式 | ✅ 完整 | — | — |
| 功能（业务闭环） | 中 | CV/IoT/VLM mock | 真链路 BL-01~04 |
| 前端 UI / 交互 | — | — | UAT（PM-402 店长测试） |
| 非功能 NFR | — | webhook SLA | 真链路 benchmark |
| P2（Sales/Trace/OTA） | — | — | Phase 2 |

**Go-Live 门禁**：TC-SEC-*、TC-PDA-*、TC-ALT-03/07、TC-RPT-01 等 P0 用例须全绿 + BL-01~08 真数据接入后 TC-NFR-*、TC-TBL-02、TC-KIT-* 转真测。

---

## 18. 关联文档

- [product_design.md §5/§12](product_design.md) — F-xxx 功能规格与 MVP 范围
- [phase1_mvp_acceptance_checklist.md](phase1_mvp_acceptance_checklist.md) — 验收勾选表（与本用例互补）
- [architecture_api_spec.md](architecture_api_spec.md) — REST API 契约
- [uat_concept_test_record.md](uat_concept_test_record.md) — PM-402 店长概念测试
- `tests/` — 自动化套件（93 passed）
