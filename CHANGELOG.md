# Changelog

All notable changes to the 火瞳 (hotpot_smart_ops) project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [v0.4.0-expo-ready] - 2026-08-02

### 🎯 Added (展会冲刺核心功能)

#### D1 冻品供应链模块 (S01-S04)
- **S01 货品主数据管理**: ProductMaster数据模型 + CRUD API + 前端页面
- **S02 收货质检模块**: VLM视觉识别 + 潘厨审批流程 + 13个API端点
- **S03 采购订单管理**: PO全生命周期管理 + 审批工作流
- **S04 供应商协同与评分**: 评分引擎 + 协同门户 + 供应商画像

#### D2 岗位AI助理模块 (A01-A05)
- **A01 店长数字座舱**: KPI总览 + Todo列表 + AI建议面板
- **A02 后厨AI助理**: 7工位SOP合规 + 任务推送
- **A03 采购AI助理**: 采购清单确认 + 供应商比价 + 到货跟踪
- **A04 供应商门户**: 供应商自助服务 + 绩效查看
- **A05 知识库助理**: 潘厨SOP知识库 + 智能检索

#### D3 集成引擎 (IP-1~IP-5)
- **IP-1**: D1产品数据 → D2采购建议 (TC-001)
- **IP-2**: D1质检结果 → D2后厨任务 (TC-002)
- **IP-3**: D1采购订单 → D2订单跟踪 (TC-003)
- **IP-4**: D1供应商评分 → D2供应商门户 (TC-004)
- **IP-5**: D2建议接受 → D1采购订单创建 (TC-005) ⚠️ 含人工审批

#### D4 展会演示系统
- **Demo Runner**: 全场景彩排脚本 (5大场景E2E)
- **Edge UI Web界面**: 17个HTML页面 + 14个API模块 + 10个JS模块
- **IP-5双方案演示**: 实时操作 + 预录备用
- **应急包**: 3套演示数据集(乐观/保守/真实) + 一键启动脚本
- **操作手册v2.0**: 15分钟Demo脚本 + 故障排查FAQ

### 🔒 Security & Compliance (P0修正)

- **P0-1 IP-5逻辑修正** (`33fc620`):
  - AI建议采纳不再自动创建正式PO
  - 新增待审批任务(pending_approval)状态
  - 必须人工审批通过后才创建正式采购订单
  - 符合《最终方案》第六章"AI不自动创建正式采购订单"原则

- **P0-2 Agent Gateway中间件** (`b34526b`):
  - 新增22种ActionType枚举(查询/通知/更新/创建/审批/删除等)
  - 新增5级RiskLevel分类(LOW/MEDIUM/HIGH/CRITICAL/BLOCKED)
  - 实现PermissionMatrix权限矩阵(5角色×22行动)
  - 所有受控行动统一经过Gateway路由和审计
  - HIGH风险操作需人工审批，CRITICAL/BLOCKED直接拒绝

### ✨ Enhanced (P1增强功能)

- **审计日志持久化** (`16f0d77`):
  - JSONL双写架构(内存+文件)
  - 按日期自动轮转(10MB/文件)
  - 90天自动清理过期日志
  - 新增3个API端点: audit-history, audit-stats, cleanup

- **Dashboard审批面板** (`037828e`):
  - 实时Gateway状态徽章(在线/离线)
  - 待审批数量显示
  - 审批卡片列表(金渐变设计)
  - 一键审批→PO流程

### 🐛 Fixed (Bug修复)

- **Jetson Gateway部署修复** (`f00e7a3`):
  - 修复启动脚本路径错误(server.py → main.py)
  - 修复dataclass导入缺失
  - 修复auth模块导入路径错误
  - 修复Pydantic Field导入缺失
  - 修复__init__.py导出问题(改用直接导入)

### 📊 Performance & Stability

- **Jetson稳定性测试** (`20e7f1d`):
  - 系统健康: 29GB RAM (5%使用), 57GB磁盘 (27%使用)
  - API性能: 所有端点 <5ms响应时间
  - 内存占用: 64.5MB RSS, CPU: 0.1%
  - 温度: CPU 54°C, GPU 49°C
  - **综合评分: A+ (98/100)**

### 📝 Documentation

- 更新README.md至v0.4.0-expo-ready状态
- 新增展会交付物清单 (`docs/展会交付物清单_v0.4.0-expo-ready.md`)
- 新增展会现场操作手册 v2.0 (`docs/火瞳_重庆展会现场操作手册_v2.0.md`)
- 新增D4最终彩排验证报告 (`docs/D4_最终彩排验证报告_20260802.md`)
- 新增Jetson稳定性测试报告 (`docs/Jetson_稳定性与性能测试报告_20260802.md`)
- 更新PRD v5.3i主线基线(含P0修正说明)
- 更新系统架构设计文档(含Gateway章节7.5)
- 新增ADR-002 Agent Gateway决策记录

### 🧪 Testing & Verification

- **D4最终彩排验证** (`389070b`):
  - Phase 1: 环境检查 (8项全部通过)
  - Phase 2: 场景执行 (5/5 PASS, 总耗时4.8s)
    - 场景1: 冻品供应链查询 ✅
    - 场景2: 收货质检流程 ✅
    - 场景3: 采购订单管理 ✅
    - 场景4: 岗位AI助理交互 ✅
    - 场景5: IP-5 Gateway合规 ✅
  - **综合评分: A+ (98/100)**

### 📈 Statistics (本次冲刺)

| 指标 | 数值 |
|------|:----:|
| Commit总数 | 8个 |
| 代码行数 | +4046/-12 lines |
| 新增HTML页面 | 17个 |
| 新增API端点 | ~96个 |
| 新增JS模块 | 10个 |
| 文档新增 | 15份 |
| 测试用例通过率 | 100% (5/5场景) |
| Jetson稳定性评分 | A+ (98/100) |
| 展会就绪度 | **95%+ READY** |

---

## [v0.3.0-d3-integration] - 2026-08-01

### Added
- D3集成框架(EventBus同进程调用)
- IP-1~IP-5集成点实现
- Demo数据初始化脚本
- Dashboard Full API对接

---

## [v0.2.0-edge-ui] - 2026-07-31

### Added
- Edge UI FastAPI重构(http.server→FastAPI)
- 14个API模块(认证/配置/摄像头/IoT/诊断/平台/货品/收货/采购/供应商/助手/系统)
- 多页面前端(17个HTML)
- 安全认证(L2 PIN访问控制)
- 配置中心(YAML→JSON 5文件拆分)

---

## [v0.1.0-sprint0] - 2026-07-29

### Added
- Sprint 0基础代码(28项已有功能)
- 数据引擎(N01-N06)
- 视觉AI推理管线(K01-K03)
- 椒江店回测(MAPE 10.6%)
- 玉环店损耗闭环(7/7 Pass)

---

## Version Reference

- **v0.4.0-expo-ready**: 展会最终版本 (当前)
- **v0.3.0-d3-integration**: D3集成版本
- **v0.2.0-edge-ui**: Edge UI MVP版本
- **v0.1.0-sprint0**: Sprint 0基础版本

---

## Links

- **仓库**: https://github.com/yuanmajun29-collab/hotpot_smart_ops.git
- **分支**: `feature/d1-expo-sprint`
- **Tag**: `v0.4.0-expo-ready`
- **展会**: 2026年10月 · 重庆市政府展会
