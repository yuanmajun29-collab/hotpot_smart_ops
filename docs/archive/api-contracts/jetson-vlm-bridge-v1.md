# Jetson VLM Bridge ↔ hotpot_smart_ops Hub 接口协定

> 版本 1.0 | 2026-07-01 | 方案A：离线脚本模式
> 
> **签名方**：小马(Conductor) · 小寇(Hub Worker) · 小卡(Jetson Worker)

---

## 1. 架构

```
Jetson Orin (192.168.2.240)                   Mac 本机 (Hub :8088)
┌──────────────────────────┐      HTTP POST    ┌──────────────────────────┐
│ bridge_waste_vision.py   │ ─────────────────→│ POST /v1/vlm/waste-estimate│
│  1. 读图片                │   Authorization   │  → compute_waste_estimate │
│  2. run_ostrakon_vl.sh   │   Bearer <token>   │  → store.add_event       │
│  3. 解析 JSON             │                    │  → persist_loss_features │
│  4. POST Hub              │ ←─────────────────│  ← {"ok":true,...}       │
└──────────────────────────┘      JSON响应       └──────────────────────────┘
```

## 2. 端点

| 项 | 值 |
|---|---|
| **URL** | `http://<HUB_HOST>:8088/v1/vlm/waste-estimate` |
| **方法** | `POST` |
| **Content-Type** | `application/json` |
| **认证** | `Authorization: Bearer <token>` |
| **超时** | 30s |

## 3. 请求体

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
      "reason": "边角料切剩，未变质",
      "suggested_action": "复称记录后入库"
    }
  ],
  "source": "vlm-shadow",
  "model": "ostrakon-vl-8b-iq4xs",
  "zone": "备餐废弃区",
  "ts": "2026-07-01T12:00:00Z",
  "image_ref": "test_kitchen.jpg"
}
```

### 字段说明

| 字段 | 类型 | 必填 | 说明 |
|------|------|:--:|------|
| `store_id` | string | ✅ | 门店ID，如 `store_yuhuan` |
| `items` | array | 条件 | 边缘 VLM 识别项列表（与 image_ref/stream_id 三选一） |
| `source` | string | 否 | 数据源标识，默认 `mock`，边缘推理传 `vlm-shadow` |
| `model` | string | 否 | 模型标识，默认 `mock-rule`，边缘推理传 `ostrakon-vl-8b-iq4xs` |
| `zone` | string | 否 | 识别区域，如 `备餐废弃区` |
| `ts` | string | 否 | ISO8601 时间戳 |
| `image_ref` | string | 条件 | Hub 推理用图片引用（与 items/stream_id 三选一） |
| `stream_id` | string | 条件 | Hub 推理用视频流ID（与 items/image_ref 三选一） |

### items[] 字段

| 字段 | 类型 | 必填 | 说明 |
|------|------|:--:|------|
| `waste_type` | string | ✅ | 损耗类型：`备餐废弃` / `边角料` / `过期临界` / `餐后剩余` |
| `sku` | string | ✅ | 食材名 |
| `estimated_portion` | number | ✅ | 预估份量（0.0~1.0 为半份/整份） |
| `unit` | string | 否 | 单位，默认 `份` |
| `confidence` | number | 否 | 置信度 0~1 |
| `reason` | string | 否 | 判断依据 |
| `suggested_action` | string | 否 | 建议操作 |

### 互斥规则

请求必须满足以下**任一**条件：
- `vlm_raw.items` 非空（边缘已推理模式）—— **本次对接使用的模式**
- `image_ref` 或 `stream_id` 非空（Hub 侧推理/Mock 模式）

`vlm_raw` 模式优先：当 `vlm_raw.items` 有效时，使用边缘结果；否则走 Mock。

## 4. 响应体

### 成功 (200)

```json
{
  "ok": true,
  "event_id": "evt_xxx",
  "generated_at": "2026-07-01T04:00:00Z",
  "store_id": "store_yuhuan",
  "source": "vlm-shadow",
  "model": "ostrakon-vl-8b-iq4xs",
  "image_ref": "test_kitchen.jpg",
  "zone": "备餐废弃区",
  "ts": "2026-07-01T12:00:00Z",
  "items": [
    {
      "waste_type": "备餐废弃",
      "sku": "毛肚",
      "estimated_portion": 0.8,
      "unit": "份",
      "confidence": 0.82,
      "reason": "边角料切剩，未变质",
      "suggested_action": "复刻记录后入库"
    }
  ]
}
```

### 错误

| 状态码 | 含义 |
|--------|------|
| 401 | 无有效 Token |
| 403 | 跨门店写入拒绝 |
| 422 | 请求体格式错误 / 无有效输入源 |
| 500 | Hub 内部错误 |

## 5. Jetson VLM Prompt 协定

`run_ostrakon_vl.sh` 的 Prompt 必须输出纯 JSON（不含 markdown 代码块）：

```
你是后厨废弃物识别系统。分析图片中的废弃食材/餐余，输出严格 JSON（不含 markdown）：
{"items":[{"waste_type":"备餐废弃|边角料|过期临界|餐后剩余","sku":"食材名","estimated_portion":0.8,"unit":"份","confidence":0.82,"reason":"判断依据","suggested_action":"建议操作"}]}
只输出 JSON，不要额外文字。
```

## 6. 认证

Jetson 使用 Hub 的 JWT Token 认证：
```bash
# 获取 token
curl -X POST http://<HUB>:8088/auth/token \
  -H "Content-Type: application/json" \
  -d '{"username":"zhangdian","password":"demo","role":"店长","store_id":"store_yuhuan"}'

# 使用 token
curl -X POST http://<HUB>:8088/v1/vlm/waste-estimate \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{...}'
```

## 7. 变更记录

| 日期 | 版本 | 变更 |
|------|------|------|
| 2026-07-01 | 1.0 | 初版协定，方案A离线脚本模式 |
