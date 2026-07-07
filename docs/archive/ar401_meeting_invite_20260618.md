# AR-401 架构设计评审 · 会议邀请（定稿）

**冯校长火锅 · 智能运营 Phase 1 · 玉环 / 椒江试点**

| 项目 | 内容 |
|------|------|
| 状态 | 待发 / 已发送（发送后勾选） |
| 会议编号 | AR-401-20260618 |
| 定稿日期 | 2026-06-15 |
| 前置 | PM-401 产品评审（6/17）结论已知 |

---

## 会议信息（已定）

| 项 | 内容 |
|----|------|
| **日期** | 2026 年 6 月 18 日（周四） |
| **时间** | 10:00 ~ 12:30（150 分钟） |
| **形式** | 腾讯会议（链接见下方，建议提前 10 分钟入会） |
| **腾讯会议** | 会议号：`888-888-888`  密码：`061718`（**占位：创建会议后改 [product_meetings_tencent.json](product_meetings_tencent.json) 并运行 gen 脚本**） |
| **入会链接** | https://meeting.tencent.com/dm/placeholder-replace-after-create |
| **主持** | 研发负责人 / 架构师 |
| **记录** | 研发 / PMO |
| **演示环境** | Hub + 看板 + 代码目录走查（会前由研发确认） |

### 演示与材料地址

| 服务 | URL | 用途 |
|------|-----|------|
| **Event Hub** | http://10.1.12.17:8088/health | API 健康检查 |
| **看板** | http://10.1.12.17:3000/login.html | 数据流演示 |
| **架构索引** | docs/architecture_design_index.md | 会前必读 |
| **评审清单** | docs/architecture_review_checklist.md | 现场勾选 |
| **差距清单** | docs/poc_to_production_gap.md | P0 关闭计划 |

**会前启动命令**（研发，评审当日 09:30 前）：

```bash
cd /mnt/project/hotpot_smart_ops
docker compose up -d
pytest -q
```

---

## 一、邮件正文（可直接发送）

**主题**：`【评审邀请】冯校长火锅·智能运营 Phase 1 架构设计评审（6/18 周四 10:00）`

**收件人**：研发负责人、架构师、后端、算法/边缘、DevOps、产品、PMO、区域 IT（建议）

```
各位好，

定于 2026年6月18日（周四）10:00-12:30 召开 Phase 1 架构设计评审会（AR-401），
在 PM-401 产品结论基础上，确认 L1/L2 边界、OpsEvent/API/存储/部署方案，
并对齐 UAT 八条阻塞项（BL-01~BL-07）的技术关闭计划。

■ 入会方式
  腾讯会议号：888-888-888  密码：061718
  入会链接：https://meeting.tencent.com/dm/placeholder-replace-after-create
  （创建真实会议后更新 docs/product_meetings_tencent.json 并重新生成 ICS）

■ 会前必读（30 分钟）
  1. docs/architecture_design_index.md — 逻辑架构与 DoD
  2. docs/architecture_design_phase1.md — Phase 1 规格
  3. docs/poc_to_production_gap.md — P0 差距
  4. cloud/event_hub/app.py — 现有 API 路由

■ 会议目标
  1. 确认 Phase 1 仅 L1 边缘 + L2 单 Hub（ADR-001）
  2. 六闭环 C-01~C06 与 PoC 代码映射签字
  3. 拍板：PG/SQLite、/v1 API、CV 后端、离线队列优先级
  4. 输出结论：通过 / 有条件通过 / 不通过

■ 议程
  10:00-10:15  目标与三层边界
  10:15-10:45  逻辑架构 + 六闭环走查
  10:45-11:15  API / 数据模型 / ADR 拍板
  11:15-11:45  部署拓扑 + 安全 + gap P0
  11:45-12:15  BL-01~07 与 sprint §6.1 对齐
  12:15-12:30  结论签字

■ 产出
  - 填写 docs/architecture_review_outcome_template.md
  - 更新 docs/architecture_changelog.md 与 ADR 状态
  - 修订项并入 sprint_task_backlog.md §6.1

谢谢！
研发负责人
```

---

## 二、会前分工

| 角色 | 会前交付 |
|------|----------|
| 研发负责人 | 1 页「代码目录 vs design_dev §2.5」差异说明 → [ar401_code_directory_mapping.md](ar401_code_directory_mapping.md) |
| 后端 | API 路由清单（对照 architecture_api_spec.md） |
| 算法/边缘 | CV/IoT 真数据路径说明（BL-01/02） |
| DevOps | docker-compose + systemd 拓扑确认 |
| 产品 | PM-401 结论摘要（Must Have 无变更或变更列表） |

---

## 三、会后 48h

| # | 动作 | 负责人 |
|---|------|--------|
| 1 | 回填 architecture_review_outcome_template.md | 记录人 |
| 2 | 更新 architecture_design_index.md DoD #8 | PMO |
| 3 | ADR 提议中 → 已采纳 | 架构师 |
| 4 | gap P0 负责人与截止日 | 研发负责人 |
| 5 | 通知 sprint 启动 BL 专项 | PMO |

---

## 四、关联文档

| 文档 | 用途 |
|------|------|
| [architecture_review_checklist.md](architecture_review_checklist.md) | 现场评审表 |
| [ar401_meeting_agenda_20260618.html](ar401_meeting_agenda_20260618.html) | 可打印议程 |
| [architecture_review_outcome_template.md](architecture_review_outcome_template.md) | 结论回填 |
| [architecture_decisions.md](architecture_decisions.md) | ADR 拍板记录 |
