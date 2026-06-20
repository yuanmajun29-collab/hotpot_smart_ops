# 后厨损耗预算/预测真实设备接入解决方案

**定位**：在全局“火锅门店运营副驾驶”不变的前提下，把 Phase 1 的落地重心收束到“后厨损耗预算/预测”这一条主线：先接真实称重、冷链、门磁、PDA 与必要摄像头，让损耗可见；再形成可解释的预算/预测；最后把预测转成可追踪动作。

| 项目 | 内容 |
|------|------|
| 状态 | V0.1 · 试点执行方案 |
| 关联 | ADR-016/017/019 · `kitchen_loss_prediction_wedge_plan.md` · `architecture_data_model_phase1.md` |
| 试点对象 | 单店优先：`store_yuhuan`，通过后复制到 `store_jiaojiang` |
| 当前代码基线 | `GET /v1/cost/loss-risk` 已实现规则 baseline；`edge/iot_mock/*`、`shared/iot_sensors.py`、UAT MQTT 配置已具备替换真设备的入口 |

---

## 1. 目标与原则

### 1.1 业务目标

| 层级 | 目标 |
|------|------|
| 损耗可见 | 短重、超温、质差、门磁异常、领料/出成偏差能自动折算金额 |
| 损耗预算 | 每日/每班给出“今日可接受损耗预算、重点 SKU 风险、建议备货量” |
| 损耗预测 | 输出 TopN 风险，必须带原因、证据、动作建议，不给黑盒数字 |
| 行动闭环 | 风险转复称、退货留证、优先消耗、SOP 整改、日报复盘 |
| 商业验证 | 1500 元/月 pay-test：店长/厨师长认为系统发现的可归因损耗足以覆盖订阅费 |

### 1.2 落地原则

| 原则 | 说明 |
|------|------|
| 少设备先证明 ROI | 第一阶段只接“收货秤 + 探针温度 + 冷链温湿度/门磁 + PDA + 1~2 路关键摄像头” |
| 设备数据是证据，不是自动处罚 | 系统只做预测、建议、排序、留证；退货/扣款必须人工确认 |
| 先 snapshot，后建大表 | P1B 先做 JSON snapshot feature builder；跨天回放稳定后再落 `loss_features/loss_predictions` |
| Jetson 做开发，RK3588 做量产 | Jetson 用于 VLM/LLM 实验验证；试点生产默认 RK3588 edge box + 云 API/YOLO-first |
| 全链路可降级 | 任一设备断线时保留 PDA 手填、手动 3 按钮品质打分与规则 baseline |

---

## 2. 分阶段开发路线

### P0：基线校准与假设验证（第 0~1 周）

| 交付 | 内容 |
|------|------|
| 数据盘点 | 过去 30 天 POS 桌数/外卖、ERP 采购单、退货、盘点、采购价、SKU 标准出成率 |
| 现场台账 | 连续 7 天记录“切了多少、扔了多少、来料品质好/一般/差、当天客流” |
| 代码使用 | 复用 `demo/data/*` 对齐字段；用 `/v1/cost/loss-risk` 规则 baseline 跑 TopN |
| 验收 | 至少 20 个 SKU 有采购价、理论用量、实际消耗或人工损耗记录 |

### P1A：真实收货与冷链接入（第 2~4 周）

| 交付 | 内容 |
|------|------|
| 设备接入 | 收货秤、探针温度计、冷藏/冷冻温湿度、冷库门磁、PDA 浏览器 |
| 数据链路 | 设备 → RS232/RS485/Modbus/HTTP → MQTT 网关 → `edge/iot_mock/mqtt_bridge.py` 替换真 broker → Event Hub |
| 产品体验 | PDA 收货页自动带入重量/温度，仍允许人工确认和签字 |
| 验收 | 24h 传感器在线率 >=98%；95% 收货批次有实时重量/温度；短重/超温可进入成本页与 loss-risk |

### P1B：损耗预算/预测 feature builder（第 5~8 周）

| 交付 | 内容 |
|------|------|
| Feature snapshot | 新增 `loss_feature_builder`：按 SKU/批次/班次聚合短重、超温、品质打分、客流、天气、预订、库存天数 |
| 预算输出 | 今日损耗预算：SKU 级“可接受损耗金额/风险阈值/建议备货量” |
| 预测输出 | 扩展 `/v1/cost/loss-risk`：在规则 baseline 上叠加 snapshot 特征和 LLM reason |
| 验收 | TopN 每条有 `risk_score`、证据、建议动作；厨师长可理解；预测命中率可被次日台账验证 |

### P1C：动作闭环与日报复盘（第 9~11 周）

| 交付 | 内容 |
|------|------|
| 动作生成 | 风险一键生成复称、优先消耗、退货留证、SOP 整改任务 |
| 推送 | 15:00 备货建议、22:00 当日损耗复盘、周一趋势周报；需要 `daily_scheduler` schedule profiles |
| 闭环指标 | 行动闭环率、预测命中率、可归因损耗金额、已挽回/已避免损耗金额 |
| 验收 | 70% 高风险项在 SLA 内有处理结果；日报能展示“预测 → 动作 → 结果” |

### P2：双店复制与模板化（第 12~18 周）

| 交付 | 内容 |
|------|------|
| 多店复制 | `store_yuhuan` 通过后复制到 `store_jiaojiang`，验证店型差异 |
| 数据持久化 | pay-test 通过后落 `loss_features/loss_predictions` 表，支持跨天回放和区域对标 |
| 模板化 | 行业模板参数化：SKU、阈值、设备 profile、推送时段、任务策略 |
| 验收 | 新店部署 <=1 天；设备映射 <=2 小时；模板配置不改代码 |

---

## 3. 数据接入架构

```mermaid
flowchart LR
    subgraph devices [真实设备层]
        Scale[收货/改刀秤]
        Probe[探针温度计]
        Cold[冷链温湿度/门磁]
        PDA[PDA 收货]
        Cam[关键摄像头]
    end
    subgraph edge [门店边缘层]
        Gateway[工业 IoT 网关<br/>RS232/RS485/Modbus/MQTT]
        EdgeBox[RK3588 Edge Box]
        Bridge[mqtt_bridge / iot adapter]
    end
    subgraph hub [Hub / 应用层]
        Receiving[/v1/receiving]
        Iot[/v1/iot/readings]
        Cost[/v1/cost/loss-risk]
        Feature[loss_feature_builder<br/>snapshot first]
        Task[/v1/tasks / sop assign]
        Report[daily report / push]
    end
    Scale --> Gateway
    Probe --> Gateway
    Cold --> Gateway
    PDA --> Receiving
    Cam --> EdgeBox
    Gateway --> Bridge
    EdgeBox --> Bridge
    Bridge --> Iot
    Receiving --> Feature
    Iot --> Feature
    Feature --> Cost
    Cost --> Task
    Cost --> Report
```

### 3.1 设备事件契约

真实设备统一转成以下结构后入 Hub，避免每个品牌在业务代码里分叉：

```json
{
  "store_id": "store_yuhuan",
  "sensor_id": "receiving_scale",
  "stage": "receiving",
  "type": "weight",
  "value": 48.2,
  "unit": "kg",
  "ts": "2026-06-21T15:30:00+08:00",
  "ref_type": "receiving_batch",
  "ref_id": "RCV-20260621-001",
  "raw": {
    "protocol": "modbus_rtu",
    "gateway_id": "gw_yuhuan_01"
  }
}
```

### 3.2 代码落点

| 能力 | 当前资产 | 下一步改造 |
|------|----------|------------|
| 设备注册 | `shared/iot_sensors.py` | 扩展 `sensor_id`、校准系数、协议、采样频率、health 状态 |
| MQTT 接入 | `edge/iot_mock/mqtt_bridge.py` | 新增真实 broker profile 与断线缓存；保留 mock publisher |
| 食材生命周期 | `edge/iot_mock/ingredient_iot_bridge.py` | 输入源由 demo JSON 切换为 MQTT/Hub reading |
| 收货页 | `dashboard/pda/receiving.html` | 绑定实时重量/温度，显示“设备读数 + 人工确认” |
| 风险 API | `cloud/event_hub/routers/cost.py` | `/v1/cost/loss-risk` 接 feature snapshot 与 action status |
| 纯规则 | `cloud/event_hub/domain/loss_risk.py` | 保留短重/超温 baseline，新增预算阈值和证据聚合 |
| LLM 预测 | `cloud/llm_report/report_agent.py` | 新增 forecast prompt，输出备货建议和理由 |
| 调度推送 | `cloud/event_hub/daily_scheduler.py` | 单时段扩展为 schedule profiles：15:00/22:00/周报 |

---

## 4. 硬件规划与选型

### 4.1 边缘计算

| 场景 | 推荐 | 选型理由 | 边界 |
|------|------|----------|------|
| 原型验证 | 旧 Android / PC + 云 API | 不先花硬件钱，快速验证预测逻辑 | 不承诺离线推理 |
| 算法开发机 | NVIDIA Jetson Orin Nano Super Developer Kit 8GB | 官方规格为 67 INT8 TOPS、8GB LPDDR5、7W-25W，适合 VLM/LLM/YOLO 试验 | 作为开发机，不作为首批量产 BOM |
| 试点/量产 | RK3588 工业边缘盒 16GB 起 | RK3588 类板卡有 6 TOPS NPU、最多 32GB RAM、丰富视频/串口/网口，适合 MQTT、轻量 CV、断网缓存与 RKNN | VLM/LLM 本地常驻只做实验，生产 YOLO-first + 云 LLM |

**结论**：维持 ADR-017 的双轨：Jetson 负责模型可行性和 Demo 速度；RK3588 负责现场成本、稳定性和规模复制。

### 4.2 必选设备（单店 P1A）

| 设备 | 数量 | 关键规格 | 用途 |
|------|------|----------|------|
| RK3588 工业边缘盒 | 1 | 16GB RAM、NVMe/eMMC、双网口优先、systemd 自启、断电恢复 | MQTT bridge、轻量推理、断网缓存 |
| 工业 IoT 网关 | 1 | RS232 + RS485、Modbus RTU、标准 MQTT/HTTP、4G/以太网 | 接秤、温湿度、门磁等异构设备 |
| 收货电子秤 | 1 | 30~150kg，RS232/RS485/Modbus/USB 输出，支持稳定重量事件 | PO 短重、成本差异 |
| 探针温度计 | 1~2 | 蓝牙/USB/串口优先；可人工确认 | 来料温控、拒收证据 |
| 冷藏/冷冻温湿度 | 2~4 | RS485 Modbus 或 MQTT；探头防水；支持校准 | 超温/断链风险 |
| 冷库门磁 | 2 | 干接点/DI 输入；开门超时事件 | 冷链 SOP 与损耗归因 |
| 收货 PDA | 2 | Android/H5 浏览器、摄像头、扫码、Wi-Fi/4G、可手套操作 | 收货、签字、拍照、人工打分 |
| 后厨/收货摄像头 | 1~2 | PoE、4MP 起、H.265、RTSP/ONVIF、WDR、防油污安装位 | 二期 VLM/废料识别；P1A 只留证 |
| POE 交换机 + UPS | 1 批 | VLAN/固定 IP；边缘盒与网关至少 30 分钟续航 | 网络与断电韧性 |

### 4.3 延后设备（P1C/P2 再买）

| 设备 | 延后原因 |
|------|----------|
| 改刀双秤 / 出成秤 | P1A 先用收货短重与冷链证明 ROI；出成率等 P1C 行动闭环再接 |
| RFID 全追溯 | 成本高、操作改造大；先用批次码/二维码 |
| 全后厨多路 VLM 摄像头 | 油烟、遮挡、标注成本高；先 1~2 路关键点留证 |
| 本地常驻 VLM/LLM | 算力、内存、模型维护成本高；先云 API + 规则 baseline |

---

## 5. 采购与现场接线清单

### 5.1 采购前确认

| 项 | 验收问题 |
|----|----------|
| 秤 | 是否能输出稳定重量事件？协议是否开放？是否可连续读数？ |
| 温湿度/门磁 | 是否 RS485 Modbus 或 MQTT？是否能配置采样频率和告警阈值？ |
| 网关 | 是否支持 RS232/RS485、Modbus RTU、标准 MQTT server、断线重传？ |
| 摄像头 | 是否支持 RTSP/ONVIF？油烟区域是否可清洁、可防护？ |
| PDA | H5 是否流畅？扫码/拍照权限是否可用？电池是否覆盖一班？ |
| 网络 | 弱电间、POE、固定 IP、NTP、上行网络、4G 备份是否确认？ |

### 5.2 现场 Topic 规划

沿用当前 UAT 形态：

| 传感器 | Topic 示例 | 说明 |
|--------|------------|------|
| 收货秤 | `hotpot/store_yuhuan/sensors/receiving_scale` | kg |
| 探针温度 | `hotpot/store_yuhuan/sensors/receiving_probe_temp` | C |
| 冷冻温度 | `hotpot/store_yuhuan/sensors/cold_storage_1` | C |
| 冷藏温度 | `hotpot/store_yuhuan/sensors/cold_storage_2` | C |
| 冷库门磁 | `hotpot/store_yuhuan/sensors/freezer_door_1` | 0=closed |

### 5.3 设备健康

| 指标 | P1A 验收线 |
|------|------------|
| 读数延迟 | 局域网入 Hub <5s；云端可见 <30s |
| 在线率 | 24h 连续在线 >=98% |
| 缺失读数 | 连续缺失 >5min 生成设备健康告警 |
| 时间同步 | 设备/网关/边缘盒时差 <1s |
| 数据校准 | 秤与标准砝码误差 <=0.2%；温度探头误差 <=0.5C |

---

## 6. 开发任务拆解

| ID | Phase | 任务 | DoD |
|----|-------|------|-----|
| LOSS-501 | P1A | 设备注册与 health profile | `shared/iot_sensors.py` 支持协议/校准/health；dashboard 能看设备在线 |
| LOSS-502 | P1A | 真 MQTT/Modbus 接入 adapter | `mqtt_bridge.py` 接真实 broker；断线重连；mock 与 real profile 明确区分 |
| LOSS-503 | P1A | PDA 收货实时称重/温度绑定 | 收货页显示设备读数、人工确认、异常原因；写入 receiving/cost snapshot |
| LOSS-504 | P1B | `loss_feature_builder` snapshot | 生成 SKU/批次/班次 JSON 特征；有单测；暂不强制建表 |
| LOSS-505 | P1B | 损耗预算/预测 API 扩展 | `/v1/cost/loss-risk` 返回预算阈值、证据、TopN、建议动作 |
| LOSS-506 | P1C | 风险转任务/SOP | 一键复称/退货留证/优先消耗；状态回写日报 |
| LOSS-507 | P1C | schedule profiles | 15:00 备货、22:00 损耗复盘、周报三类调度可配置 |
| LOSS-508 | P2 | feature/prediction 落表 | pay-test 通过后落 `loss_features/loss_predictions`，支持跨天回放 |

---

## 7. 验收方案

| 维度 | 验收 |
|------|------|
| 数据真实性 | 至少 100 个真实收货批次；设备读数与人工台账可抽样对账 |
| 风险解释性 | 每条 TopN 风险含“原因 + 证据 + 金额 + 建议动作” |
| 预算有效性 | 预测备货量与店长经验对比，连续 7 天误差收敛；偏差必须可解释 |
| 行动闭环 | 高风险项处理闭环率 >=70%；处理结果进入日报 |
| 商业验证 | 系统发现并闭环的可归因损耗金额 >= 月服务费，店长愿意付费继续用 |
| 稳定性 | 边缘盒 7x24 运行；断网恢复后补传；重启后 systemd 自愈 |

---

## 8. 风险与缓解

| 风险 | 缓解 |
|------|------|
| 秤协议封闭或输出不稳定 | 采购前要求协议样例；优先 RS232/RS485/Modbus 开放设备；保留 PDA 手填 |
| 厨师长不信预测 | 每条预测必须给证据；先让系统排名，不直接自动执行 |
| 摄像头受油烟/遮挡影响 | P1A 摄像头只留证；VLM 废料识别放 P1C/P2；优先称重/温度这些强结构数据 |
| 设备太多导致现场复杂 | P1A 必选设备控制在 7 类以内；RFID/改刀双秤/全量摄像头延后 |
| 本地模型维护成本高 | 云 API + 规则 baseline 先过 pay-test；本地 VLM/LLM 仅开发机验证 |
| 多店模板返工 | 从 P1A 起所有配置走 `store_id + sensor_id + profile`，不写死门店 |

---

## 9. 外部硬件资料来源

| 类别 | 来源 |
|------|------|
| Jetson Orin Nano Super | [NVIDIA 官方规格](https://www.nvidia.com/en-us/autonomous-machines/embedded-systems/jetson-orin/nano-super-developer-kit/)：67 INT8 TOPS、8GB LPDDR5、102GB/s、7W-25W |
| RK3588 工业板 | [Firefly ITX-3588J 官方资料](https://en.t-firefly.com/product/industry/itx3588j)：RK3588、6 TOPS NPU、最高 32GB RAM、双 GbE、RS485/RS232、SATA/PCIe/POE 等接口 |
| 工业 IoT 网关 | [Milesight UC300 官方资料](https://www.milesight.com/iot/product/iot-controller/uc300) 与 [datasheet](https://resource.milesight.com/milesight/iot/document/uc300-datasheet-en.pdf)：RS232 + RS485、Modbus RTU、数字/模拟输入、标准 MQTT server 集成 |

---

## 10. 最小采购建议

第一家店不要一次买全量方案。建议先采购：

1. RK3588 16GB 工业边缘盒 1 台。
2. 工业 IoT 网关 1 台。
3. 收货秤 1 台，必须开放 RS232/RS485/Modbus/USB 数据输出。
4. 探针温度计 1~2 支。
5. 冷藏/冷冻温湿度传感器各 1~2 个，门磁 2 个。
6. Android PDA 2 台。
7. 收货/后厨关键位 PoE 摄像头 1~2 路。
8. POE 交换机、UPS、线材、安装支架。

这套设备足以证明“短重 + 超温 + 品质人工打分 + 客流/采购基线 → 损耗预算/预测 → 动作闭环”的主线。改刀出成秤、RFID、全量 VLM 摄像头等，等单店 pay-test 通过后再进入 P1C/P2。
