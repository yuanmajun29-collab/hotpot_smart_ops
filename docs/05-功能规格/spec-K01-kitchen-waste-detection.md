# K01 后厨废料实时检测 — 技术规格书 (Specification)

> 版本 1.0 | 2026-07-16 | 基于 PRD K01 + 现有代码基
>
> **PRD 验收标准**: YOLO检测废料 → Dashboard推送，延迟 <5s，计数误差 <20%

---

## 1. 系统架构

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         K01 后厨废料实时检测 — 数据流                          │
├──────────┐      ┌──────────────────┐      ┌─────────────┐      ┌────────────┤
│  IPC     │ RTSP │  Jetson :8100    │ HTTP │  Jetso       │      │            │
│ 摄像头   │─────→│  Count Server    │─────→│  pipeline    │      │            │
│          │      │  YOLOv5s         │      │  4-stage     │      │            │
│          │      │  python3.8       │      │              │      │            │
└──────────┘      └──────────────────┘      └──────┬───────┘      │            │
                                                   │               │            │
                                              POST /v1/vlm/        │            │
                                              waste-estimate       │            │
                                                   │               │            │
                                                   ▼               │            │
                              ┌──────────────────────────┐         │            │
                              │  Mac Hub :8098           │         │            │
                              │  event_hub / waste域     │─────────┤            │
                              │  DB持久化 / 内存事件     │         │            │
                              └──────────┬───────────────┘         │            │
                                         │                          │            │
                                    GET /api/kitchen/               │            │
                                    waste/stats                    │            │
                                         │                          │            │
                                         ▼                          │            │
                              ┌──────────────────────────┐         │            │
                              │  Mac Dashboard :3000     │         │            │
                              │  kitchen-count.html      │─────────┘            │
                              │  每30s自动刷新           │                       │
                              └──────────────────────────┘                       │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 1.1 管线阶段（Edge Pipeline）

| Stage | 名称 | 功能 | 输入 | 输出 |
|:-----:|------|------|------|------|
| 1 | YOLO | 目标检测 | frame JPEG | detections[] |
| 2 | CLIP | 废料分类 | detections[] ROI | top_class + confidence |
| 3 | VLM | 语义分析 | 低置信度 ROI | waste_type + sku |
| 4 | **Count** | **废料计数** | ROI crop JPEG | count int |

K01 聚焦 Stage 4 (Count) + 端到端 Dashboard 推送链路。

---

## 2. 接口契约

### 2.1 Jetson Count Server (`:8100`)

#### GET /health

**用途**: 健康检查，确认 Count Server 在线、模型已加载。

**请求**:
```
GET /health HTTP/1.1
Host: <jetson_ip>:8100
```

**成功响应 (200)**:
```json
{
  "status": "ok",
  "model": "yolov5s",
  "model_loaded": true,
  "python_version": "3.8",
  "uptime_seconds": 86400
}
```

**异常响应**:
| 状态码 | 含义 | 响应体 |
|:------:|------|--------|
| 200 | 模型加载中 | `{"status":"loading","model_loaded":false}` |
| 503 | 服务不可用 | `{"status":"error","error":"..."}` |
| 无响应 | Jetson 离线/网络不通 | 连接超时 (10s) |

#### POST /count

**用途**: 上传 ROI 裁剪图片，返回废料件数。

**请求**:
```
POST /count HTTP/1.1
Content-Type: multipart/form-data

image: <binary JPEG/PNG>
zone: "备餐废弃区"
```

**参数**:
| 字段 | 类型 | 必填 | 说明 |
|------|------|:---:|------|
| `image` | file | ✅ | ROI 裁剪图 (JPEG/PNG, ≤10MB) |
| `zone` | string | 否 | 区域标识，用于日志 |

**成功响应 (200)**:
```json
{
  "status": "ok",
  "count": 5,
  "inference_ms": 45.2
}
```

**异常响应**:
| 状态码 | 场景 | 响应体 |
|:------:|------|--------|
| 400 | 缺少 image 字段 | `{"status":"error","error":"no image provided"}` |
| 400 | 图片格式不支持 | `{"status":"error","error":"unsupported format"}` |
| 413 | 图片过大 (>10MB) | `{"status":"error","error":"image too large"}` |
| 500 | 推理异常 | `{"status":"error","error":"<details>"}` |

**边界约束**:
- 首次 `/count` 调用可能触发模型下载，超时需放宽至 120s
- 连续调用间隔 ≥ 50ms（防止 GPU 争抢）
- `count` 值范围: 0 ~ 200（超过视为噪声/误检）

---

### 2.2 Edge Pipeline → Hub 桥接

#### POST /v1/vlm/waste-estimate

**用途**: 接收边缘推理结果（含计数），写入事件流 + 持久化。

**请求**:
```
POST /v1/vlm/waste-estimate HTTP/1.1
Host: <hub_host>:8098
Content-Type: application/json
Authorization: Bearer <jwt_token>
```

**请求体 (完整边缘路径)**:
```json
{
  "store_id": "store_yuhuan",
  "items": [
    {
      "waste_type": "备餐废弃",
      "sku": "毛肚",
      "estimated_portion": 0.8,
      "unit": "份",
      "confidence": 0.82,
      "reason": "边角料切剩",
      "suggested_action": "复称记录",
      "count": 5,
      "source": "kitchen_pipeline"
    }
  ],
  "source": "vlm-shadow",
  "model": "ostrakon-vl-8b-iq4xs",
  "zone": "备餐废弃区",
  "ts": "2026-07-16T12:00:00Z",
  "image_ref": "file:///tmp/kitchen_frame.jpg",
  "image_data": "<base64>",
  "image_mime": "image/jpeg",
  "total_waste_count": 15
}
```

**字段说明**:
| 字段 | 类型 | 必填 | 说明 |
|------|------|:---:|------|
| `store_id` | string | ✅ | 门店ID |
| `items` | array | 条件 | 废料项列表（至少1项，或提供 image_ref/stream_id） |
| `items[].count` | int | 否 | K01 核心字段：该 ROI 的废料计数 |
| `source` | string | 否 | `vlm-shadow`（边缘）/ `mock`（Hub mock） |
| `total_waste_count` | int | 否 | K01 核心字段：整帧废料总数 |
| `image_data` | string | 否 | 原图 base64（≤5MB，否则跳过） |
| `image_mime` | string | 否 | 图片 MIME 类型 |

**成功响应 (200)**:
```json
{
  "ok": true,
  "event_id": "evt_k01_20260716_001",
  "store_id": "store_yuhuan",
  "source": "vlm-shadow",
  "items": [...],
  "generated_at": "2026-07-16T12:00:01Z"
}
```

**异常响应**:
| 状态码 | 场景 | 响应体 |
|:------:|------|--------|
| 401 | Token 无效或过期 | `{"detail":"Invalid token"}` |
| 403 | 跨门店写入 | `{"detail":"Forbidden: cross-store"}` |
| 422 | 缺少有效输入源 | `{"detail":"..."}` |
| 500 | Hub 内部错误 | `{"detail":"Internal server error"}` |

---

### 2.3 废料统计查询 API

#### GET /api/kitchen/waste/stats

**用途**: Dashboard 查询废料计数趋势数据。

**请求**:
```
GET /api/kitchen/waste/stats?store_id=store_yuhuan&days=7 HTTP/1.1
Authorization: Bearer <jwt_token>
```

**参数**:
| 参数 | 类型 | 默认 | 范围 | 说明 |
|------|------|------|------|------|
| `store_id` | string | 当前门店 | — | 门店ID |
| `days` | int | 7 | 1-90 | 查询天数 |

**成功响应 (200)**:
```json
{
  "store_id": "store_yuhuan",
  "days": 7,
  "trend": [153, 128, 172, 0, 145, 168, 190],
  "dates": ["2026-07-10", "2026-07-11", "2026-07-12", "2026-07-13", "2026-07-14", "2026-07-15", "2026-07-16"],
  "daily": [
    {
      "date": "2026-07-16",
      "total_count": 190,
      "event_count": 12,
      "items": [
        {"sku": "毛肚", "count": 45, "waste_type": "备餐废弃"},
        {"sku": "鸭肠", "count": 30, "waste_type": "边角料"}
      ]
    }
  ],
  "live_count": 5,
  "generated_at": "2026-07-16T15:30:00Z"
}
```

**字段说明**:
| 字段 | 类型 | 说明 |
|------|------|------|
| `trend` | int[] | 每日废料总数，与 `dates` 一一对应 |
| `dates` | string[] | 日期列表 (YYYY-MM-DD) |
| `daily` | object[] | 每日明细 |
| `daily[].total_count` | int | 当日总计数 |
| `daily[].event_count` | int | 当日推理事件数 |
| `daily[].items` | object[] | 按 SKU 聚合的计数 |
| `live_count` | int | 内存中未落 DB 的最新计数 |

---

### 2.4 Dashboard (kitchen-count.html :3000)

**数据源**: `GET /api/kitchen/waste/stats`
**刷新间隔**: 30s (hero + chart + SKU + log)
**展示指标**:
- 今日废料总数 (`daily[-1].total_count`)
- 7日均值 (`avg(trend.filter(v>0))`)
- 今日事件数 (`daily[-1].event_count`)
- 峰值日 (`max(trend)` + 对应日期)
- 7日趋势柱状图
- SKU 品类分布 (按 `items[].count` 聚合)
- 最近上报事件日志

---

## 3. 端到端延迟预算

PRD 要求: **总延迟 < 5s**（从摄像头采集到 Dashboard 刷新）

| 环节 | 预算 | 说明 |
|------|:---:|------|
| IPC 采集 → Jetson | 500ms | RTSP 取帧 |
| YOLO 检测 (Stage 1) | 50ms | YOLOv5s / YOLO26n |
| CLIP 分类 (Stage 2) | 200ms | CLIP-Adapter |
| VLM 分析 (Stage 3) | 1000ms | 仅低置信度 ROI |
| **Count 计数 (Stage 4)** | **200ms** | Jetson :8100 /count API |
| Pipeline → Hub POST | 500ms | JSON + base64, 网络 |
| Hub 处理 → Dashboard 轮询 | 2000ms | DB写入 + 30s轮询窗口 |
| **端到端** | **< 5s** | |

> **注意**: Dashboard 30s 轮询窗口占 2s 预算，若要求实时推送，后续可升级为 WebSocket/SSE。

---

## 4. 计数误差约束

PRD 要求: **计数误差 < 20%**

| 场景 | 预期误差 | 说明 |
|------|:---:|------|
| 独立小物件 (1-10件) | < 10% | 无遮挡，清晰可辨 |
| 堆叠废料 (10-50件) | < 20% | 部分遮挡，YOLOv5s 边界 |
| 密集废料 (50-200件) | < 30% | 超出模型能力，触发告警但不阻塞 |
| 空盘/无废料 | 0% | 返回 count=0 |

**误差计算**: `|count_ai - count_gt| / max(1, count_gt) × 100%`

---

## 5. 异常与降级

### 5.1 降级矩阵

| 故障点 | 影响 | 降级行为 |
|--------|------|---------|
| Jetson :8100 离线 | Count 无法获取 | `count=0, status="error"`，不阻塞 pipeline |
| /count 超时 (>10s) | 单 ROI 计数缺失 | 跳过该 ROI，继续处理其他 |
| /count 返回异常值 (>200) | 噪声误检 | 截断为 200，标记 `status="capped"` |
| Hub :8098 离线 | 事件无法上传 | store-and-forward，恢复后重传 |
| Pipeline 4 阶段全故障 | 无数据产出 | Dashboard 显示最后已知值 + "离线" 标记 |

### 5.2 首次加载特殊处理

Jetson `/count` 首次调用时模型下载可能耗时 30-120s。Pipeline 需：
- 设置首次调用超时为 120s
- 后续调用超时恢复为 10s
- 首次加载期间跳过计数，不阻塞 pipeline

---

## 6. 数据持久化

| 数据 | 存储位置 | 保留策略 |
|------|---------|---------|
| 原始废料事件 | Hub SQLite `events` 表 | 60 天 |
| 每日聚合计数 | Hub DB `waste_daily_stats` 表 | 永久 |
| 废料图片 | Hub `static/waste_images/` | 30 天 |
| 内存事件 | `Store.events` 列表 (≤200条) | 进程生命周期 |

---

## 7. 环境与配置

| 配置项 | 环境变量 | 默认值 |
|--------|---------|--------|
| Count API URL | `HOTPOT_COUNT_API_URL` | `http://127.0.0.1:8100` |
| Hub URL | `HOTPOT_HUB_URL` | `http://192.168.2.85:8098` |
| 门店 ID | `HOTPOT_STORE_ID` | `store_yuhuan` |
| 检测区域 | `HOTPOT_ZONE` | `备餐废弃区` |
| Count 超时 | — | 10s (首次 120s) |

---

## 8. 变更记录

| 日期 | 版本 | 变更 |
|------|------|------|
| 2026-07-16 | 1.0 | 初版：K01 接口契约 + 延迟预算 + 误差约束 |
