# Phase 2 Spec: 食材监管 + SOP工位 + 多店Dashboard

## 概述
Phase 2 扩展 hotpot_smart_ops 三个模块：食材监管（进货口检测）、SOP 7工位合规检测、多店驾驶仓增强。

---

## 任务一：食材监管模块 (Receiving Module)

### Edge: edge/receiving/

#### 1.1 进货口检测管道 (detector.py)
- **输入**: RTSP/本地图像 → YOLO 检测
- **YOLO Classes**: 食材类别映射（肉类/蔬菜/豆制品/海鲜/冻品/调料/干货/其他）
- **输出**: `{ingredients: [{class, count, confidence}], image_url, timestamp, store_id}`
- **依赖**: `edge/common/detector/` (共享 Detector)
- **延迟预算**: <200ms per frame

#### 1.2 电子秤 MQTT 模拟器 (mqtt_scale_sim.py)
- **协议**: MQTT (paho-mqtt), topic: `hotpot/{store_id}/scale/{scale_id}`
- **Payload**: `{scale_id, weight_kg, unit, timestamp, stable: bool}`
- **模式**: 
  - `mock`: 定时发送随机重量（模拟秤盘波动→稳定）
  - `replay`: 从 CSV 文件回放
- **健康检查**: MQTT broker 连通性检测
- **启动**: `PYTHONPATH=. python3 -m edge.receiving.mqtt_scale_sim --store-id store_yuhuan --mode mock`

### Hub: POST /v1/receiving/checkin

#### 端点契约
```
POST /v1/receiving/checkin
Content-Type: application/json
X-Api-Key: <key>

{
  "store_id": "store_yuhuan",
  "batch_ref": "PO-2026-0716-001",   // optional PO ref
  "ingredients": [
    {"class": "肉类", "count": 5, "confidence": 0.92},
    {"class": "蔬菜", "count": 12, "confidence": 0.88}
  ],
  "weight_kg": 23.5,                  // from MQTT scale (latest)
  "po_weight_kg": 25.0,               // expected weight
  "temp_c": 4.2,                      // cold chain temp
  "image_ref": "receiving/2026/0716/store_yuhuan_001.jpg",
  "source": "edge_yolo_v2"
}

Response 200:
{
  "ok": true,
  "checkin_id": "CHK-20260716-yuhuan-A1B2C3",
  "batch_id": "RCV-20260716-yuhuan-X1Y2Z3",  // auto-created if batch_ref provided
  "variance_pct": -6.0,
  "event_id": "uuid",
  "ingredient_summary": {"total_items": 17, "classes": 2}
}

Errors:
  400: 缺少必填字段 (store_id, ingredients)
  409: 重复 checkin (同一 store+batch_ref 已在 5 分钟内提交)
```

#### Hub 内部逻辑
1. 创建 `receiving_checkin` event（event_type="receiving_checkin"）
2. 若提供 `batch_ref` 且不存在，自动创建入库批次（复用 `receiving_store.submit` 调用 PO 数据填充）
3. 记录食材明细到 event.metadata.ingredients
4. 重量偏差 >5% 则置 level="warn"，>10% 置 level="critical"

### Dashboard: receiving.html
- **布局**: App-shell 模式（sidebar + 内容区）
- **导航**: 新增"食材监管"nav（sidebar 中）
- **数据源**: `GET /v1/receiving/batches` + `GET /v1/receiving/checkins` (新增)
- **Hero cards**: 今日收货批次、总重量、偏差率、质检通过率
- **食材明细表**: 按批次展开，显示食材分类/数量/置信度
- **重量偏差趋势**: 简单折线图（近7天PO vs 实收）
- **Mermaid 流程图**: 进货口→YOLO检测→称重→Hub记录→入库
- **自动刷新**: 30s 轮询

---

## 任务二：SOP 7工位状态机

### Edge: edge/receiving/sop_compliance.py

7工位及其合规检测规则：

| 工位 | ID | 检测规则 | 检测方式 |
|------|-----|---------|---------|
| 汤底 | sop_broth | 汤温≥85°C，汤色正常 | IoT温度传感器 + 颜色检测 |
| 切配 | sop_cutting | 刀具在位、砧板清洁、食材分类不混放 | YOLO检测砧板/刀具 |
| 摆盘 | sop_plating | 每盘重量±5g、摆盘间距均匀 | 称重+视觉 |
| 蘸料 | sop_sauce | 蘸料盒满度>30%、标签正确 | YOLO检测 |
| 洗消 | sop_washing | 洗碗机温度≥82°C、清洁剂余量>10% | IoT传感器 |
| 传菜 | sop_serving | 传菜时间<3min、托盘平稳 | 计时+加速度计 |
| 冷库 | sop_cold_storage | 库温-18°C~-22°C、食材标签在有效期内 | IoT温度+OCR标签 |

- **输出事件**: `POST /v1/sop/compliance` → Hub
- **检测周期**: 每30s扫描一轮
- **状态机**: 每个工位独立 running/warning/violation 三态
  - running → warning: 连续3次不合格
  - warning → running: 连续2次合格
  - warning → violation: 连续5次不合格
  - violation → warning: 手动确认后重置

### Hub: POST /v1/sop/compliance (新增)

```
POST /v1/sop/compliance
{
  "store_id": "store_yuhuan",
  "device_id": "jetson-kitchen-01",
  "timestamp": "2026-07-16T10:30:00Z",
  "stations": [
    {"station_id": "sop_broth", "status": "running", "readings": {"temp_c": 87.5}, "message": "汤温正常"},
    {"station_id": "sop_cutting", "status": "warning", "readings": {"knife_detected": false}, "message": "刀具未在指定位置"}
  ]
}

Response 200:
{
  "ok": true,
  "store_id": "store_yuhuan",
  "compliance_rate": 85.7,           // 6/7 running
  "violations": ["sop_cutting"],
  "warnings": [],
  "events_created": 2
}
```

### Dashboard: sop.html 增强
- **现有**: SOP清单（合规率/通过/未通过/违规整改）
- **新增**:
  - **7工位卡片可视化**: 每个工位一张卡片（颜色=状态: 绿 running / 黄 warning / 红 violation）
  - **工位详情弹窗**: 点击卡片显示传感器读数、违规历史、整改记录
  - **实时合规率环形图**: Canvas 或 SVG 绘制
  - **工位状态时间线**: 最近24小时状态变化
  - **数据源**: `GET /v1/sop/stations?store_id=xxx`

---

## 任务三：多店Dashboard

### cockpit.html 增强
- **现有**: 全国经营态势（Hero指标/异常滚动/趋势图/大区热力/排名）
- **新增**:
  - **多店对比模式**: 
    - 并排2-3店对比卡片（废料率/翻台率/告警数/SOP合规率）
    - 店长视图：只看自己店 vs 集团平均（当前默认）
    - 总代视图：所有门店横向对比表格
  - **门店选择器**: 下拉多选（支持全选/大区筛选）
  - **对比指标切换**: 废料率/翻台率/告警数/营收/SOP
  - **门店健康雷达图**: 5维度（营收/翻台/损耗/SOP/告警）蛛网图对比
  - **废料排名对比表**: 各店废料率排序 + vs 集团均值偏差

---

## 数据流汇总

```
Edge (Jetson)
  ├── receiving/detector.py  ──YOLO──→ Hub POST /v1/receiving/checkin
  ├── receiving/mqtt_scale_sim.py ─MQTT→ (本地/云端) MQTT Broker
  │                                              │
  │                          Hub MQTT Listener   │
  │                          POST /v1/iot/readings
  └── receiving/sop_compliance.py ──→ Hub POST /v1/sop/compliance

Hub (:8098)
  ├── routers/receiving.py   → GET/POST /v1/receiving/*
  ├── routers/sop.py         → GET/POST /v1/sop/*
  └── routers/org.py         → GET /v1/org/overview (cockpit数据源)

Dashboard (:3000)
  ├── receiving.html  → GET /v1/receiving/batches + /v1/receiving/checkins
  ├── sop.html        → GET /v1/sop/stations + /v1/sop/assignments
  └── cockpit.html    → GET /v1/org/overview (增强多店对比)
```

---

## 验收标准

- [ ] `edge/receiving/detector.py` 可独立运行并检测进货口食材
- [ ] `edge/receiving/mqtt_scale_sim.py` 可发送MQTT消息
- [ ] Hub `POST /v1/receiving/checkin` 返回正确的checkin_id和偏差
- [ ] Dashboard `receiving.html` 展示食材明细和重量偏差
- [ ] SOP 7工位状态机正确切换三态
- [ ] sop.html 增强显示工位卡片可视化
- [ ] cockpit.html 支持多店选择+对比视图
- [ ] 所有 Dashboard 页面使用 app-shell 模式 + theme.css
