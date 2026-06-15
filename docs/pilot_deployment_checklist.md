# 试点店部署 Checklist（索引）

**冯校长火锅智能运营 · Phase 1 · 台州试点**

请按门店类型选择对应清单：

| 当前试点店 | store_id | 城市 |
|------------|----------|------|
| **冯校长火锅·玉环店** | `store_yuhuan` | 玉环市 |
| **冯校长火锅·椒江店** | `store_jiaojiang` | 椒江区 |

门店配置见 `demo/data/stores.json`。

请按门店类型选择部署清单：

| 门店类型 | 文档 | 适用说明 |
|----------|------|----------|
| **直营店** | [pilot_deployment_checklist_direct.md](pilot_deployment_checklist_direct.md) | 总部统一 IT/采购/ERP，全栈部署，数据直连总部中台 |
| **加盟店** | [pilot_deployment_checklist_franchise.md](pilot_deployment_checklist_franchise.md) | SaaS 化轻部署，预配置边缘盒，远程运维，加盟协议约束 |

## 建议试点组合（当前）

- **玉环店**（`store_yuhuan`）：Phase 1 试点 A  
- **椒江店**（`store_jiaojiang`）：Phase 1 试点 B  

两店并行部署，验证台州区域复制与 ROI；后续再扩展加盟/SaaS 模式。

## 差异速览（直营 vs 加盟 · 远期）

| 维度 | 直营 | 加盟 |
|------|------|------|
| 硬件采购 | 总部 IT 统采 | 总部套件租赁/配售 + 加盟方配合施工 |
| 软件部署 | 总部/区域 IT 现场 | 总部远程 + 预配置镜像，加盟方零代码 |
| POS/ERP | 深度 API 对接 | 经总部网关统一对接，加盟方不开放系统 |
| 来料/成本 | 全供应商 PO 对账 | 限总部配送中心物料对账 |
| SOP | 总部 PMO 定制 | 总部 OTA 统一下发，不可本地改 |
| 运维 | 区域 IT on-call | 总部 400/远程 + 4G 备份必选 |
| 验收签字 | 店长 + 区域 + 总部 PMO | 加盟业主 + 店长 + 加盟督导 + 总部 |

## 建议试点组合（历史模板 · 多店扩张参考）

- 一线 **直营** 1 家：验证增收与全栈能力上限  
- 二线 **直营** 1 家：验证 ROI 普适性  
- **加盟** 1 家：验证 SaaS 化复制与低 IT 依赖  

**当前冯校长火锅 Phase 1 已确定为玉环 + 椒江 2 店。**

关联文档：[solution.md](solution.md) · [设计·开发·实施](design_dev_implementation_plan.md) · [PoC→生产差距](poc_to_production_gap.md) · PoC：`/home/liuwz/hotpot_smart_ops/`
