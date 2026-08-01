# Edge UI — API 接口规范文档 v1.0

> **版本**: v1.0
> **日期**: 2026-08-01
> **基础路径**: `http://{host}:9080/api/v1`
> **认证方式**: L2 PIN (Session Cookie)
> **数据格式**: JSON (UTF-8)

---

## 1. 概述

### 1.1 Edge UI 架构

```
┌─────────────────────────────────────────────┐
│              浏览器 / 前端页面               │
│  (products.html / dashboard.html / ...)     │
└──────────────────┬──────────────────────────┘
                   │ HTTP/JSON
                   ▼
┌─────────────────────────────────────────────┐
│           FastAPI 应用 (:9080)              │
│                                             │
│  ┌─────────┐  ┌─────────┐  ┌─────────────┐ │
│  │ 认证中间件│→ │API Router│→ │Service Layer│ │
│  │(L2 PIN) │  │ (9模块)  │  │(Manager类)   │ │
│  └─────────┘  └─────────┘  └─────────────┘ │
│                             │              │
│                    ┌────────▼────────┐     │
│                    │ JSON File Store │     │
│                    │ (data/*.json)    │     │
│                    └─────────────────┘     │
└─────────────────────────────────────────────┘
```

### 1.2 模块清单 (9个API模块)

| # | 模块名 | 路由前缀 | 文件 | 端点数 | 状态 |
|---|--------|----------|------|--------|------|
| 1 | 认证授权 | `/auth` | `auth_api.py` | 3 | ✅ |
| 2 | 系统状态 | `/system` | `system_api.py` | 4 | ✅ |
| 3 | 摄像头 | `/cameras` | `camera_api.py` | 5 | ✅ |
| 4 | 视觉推理 | `/vision` | `vision_api.py` | 3 | ✅ |
| 5 | 数据引擎 | `/data` | `data_api.py` | 4 | ✅ |
| 6 | 仓库IoT | `/warehouse` | `warehouse_api.py` | 4 | ✅ |
| 7 | SOP合规 | `/sop` | `sop_api.py` | 3 | ✅ |
| 8 | 知识库 | `/knowledge` | `knowledge_api.py` | 3 | ✅ |
| 9 | **货品主数据** | `/products` | `product_master_api.py` | **13** | ✅ **新增** |

**总计**: **42 个 API 端点**

---

## 2. 统一规范

### 2.1 认证机制

#### L2 PIN 认证流程

```
1. 客户端 POST /api/v1/auth/login { "pin": "123456" }
       ↓
2. 服务端验证PIN → 创建Session → 返回 session_id + Set-Cookie
       ↓
3. 后续请求自动携带Cookie: session_id=xxx
       ↓
4. 服务端 Depends(get_current_session) 验证Session有效性
       ↓
5. 通过 → 继续处理请求
   失效 → 401 Unauthorized
```

#### Session 结构

```json
{
  "session_id": "sess_a1b2c3d4",
  "user_id": "admin",
  "created_at": "2026-08-01T16:30:00",
  "expires_at": "2026-08-01T18:30:00",
  "ip_address": "127.0.0.1"
}
```

#### 认证依赖注入

所有受保护端点的统一签名：

```python
async def endpoint_name(
    param: Type = Query(..., description="..."),
    _: dict = Depends(get_current_session),  # ← 认证注入
):
    # 业务逻辑
    pass
```

### 2.2 统一响应格式

#### 成功响应

```json
{
  "code": 200,
  "data": { /* 具体业务数据 */ },
  "message": "success"
}
```

**注意**: 当前实现直接返回 Pydantic Model，未包裹 code/message。建议后续统一。

#### 错误响应

```json
{
  "detail": "错误描述信息"
}
```

#### 标准HTTP状态码

| 状态码 | 含义 | 使用场景 |
|--------|------|----------|
| **200** | OK | GET 请求成功 |
| **201** | Created | POST 创建成功 |
| **204** | No Content | DELETE 成功且无返回体 |
| **400** | Bad Request | 参数校验失败 |
| **401** | Unauthorized | 未登录/Session过期 |
| **403** | Forbidden | 无权限操作 |
| **404** | Not Found | 资源不存在 |
| **409** | Conflict | 资源冲突（如SKU重复） |
| **422** | Unprocessable Entity | 语义错误（Pydantic校验失败） |
| **500** | Internal Server Error | 服务器内部错误 |

### 2.3 分页规范

**请求参数**:

| 参数 | 类型 | 默认值 | 约束 | 说明 |
|------|------|--------|------|------|
| `page` | int | 1 | ≥1 | 页码（从1开始） |
| `page_size` | int | 20 | 1-100 | 每页数量 |

**列表响应结构**:

```json
{
  "total": 100,        // 总记录数
  "page": 1,           // 当前页码
  "page_size": 20,      // 每页数量
  "items": [...],       // 当前页数据数组
  // 模块特定字段...
}
```

### 2.4 错误码定义

| 错误码 | HTTP状态 | 场景 | 示例 |
|--------|----------|------|------|
| `AUTH_001` | 401 | PIN错误 | `"detail": "PIN码错误"` |
| `AUTH_002` | 401 | Session过期 | `"detail": "Session已过期，请重新登录"` |
| `VAL_001` | 422 | 必填参数缺失 | `"detail": "Field required"` |
| `VAL_002` | 422 | 参数格式错误 | `"detail": "string does not match regex"` |
| `VAL_003` | 422 | 参数范围越界 | `"detail": "Input should be greater than 0"` |
| `BIZ_001` | 409 | 业务规则冲突 | `"detail": "SKU 已存在: FP-MW-001"` |
| `BIZ_002` | 403 | 权限不足 | `"detail": "该货品已锁定，关键字段不可修改"` |
| `BIZ_003` | 404 | 资源不存在 | `"detail": "SKU 不存在: FP-XXX"` |
| `SYS_001` | 500 | 服务器内部错误 | `"detail": "内部服务器错误"` |

---

## 3. 模块详细规范

### 3.1 模块1: 认证授权 (`/auth`)

| 方法 | 路径 | 功能 | 认证 | 说明 |
|------|------|------|------|------|
| POST | `/auth/login` | 登录 | ❌ | PIN认证，返回session_id |
| POST | `/auth/logout` | 登出 | ✅ | 销毁Session |
| GET | `/auth/session` | 查询当前Session | ✅ | 返回用户信息+剩余有效期 |

**POST /auth/login 请求**:
```json
{ "pin": "123456" }
```

**POST /auth/login 响应 (200)**:
```json
{
  "session_id": "sess_xxx",
  "user_id": "admin",
  "expires_in": 7200
}
```

---

### 3.2 模块2: 系统状态 (`/system`)

| 方法 | 路径 | 功能 | 认证 | 说明 |
|------|------|------|------|------|
| GET | `/ping` | 健康检查 | ❌ | 返回 `{ "status": "ok", "version": "..." }` |
| GET | `/system/info` | 系统信息 | ✅ | Python版本/平台/启动时间 |
| GET | `/system/stats` | 运行统计 | ✅ | 内存/CPU/请求数 |
| GET | `/system/logs` | 最近日志 | ✅ | 最后N条日志（调试用） |

---

### 3.3 模块3: 摄像头 (`/cameras`)

| 方法 | 路径 | 功能 | 认证 | 说明 |
|------|------|------|------|------|
| GET | `/cameras` | 摄像头列表 | ✅ | 返回已配置的IPC信息 |
| GET | `/cameras/{id}/snapshot` | 抓拍一张 | ✅ | HTTP抓拍返回JPEG |
| GET | `/cameras/{id}/stream` | 视频流地址 | ✅ | 返回RTSP/MJPEG URL |
| POST | `/cameras/{id}/config` | 更新配置 | ✅ | 修改IPC参数 |
| GET | `/cameras/{id}/status` | 在线状态 | ✅ | 是否可达 |

**GET /cameras/{id}/snapshot 响应**:
- Content-Type: `image/jpeg`
- Body: JPEG 二进制图片数据 (~64KB)

---

### 3.4 模块4: 视觉推理 (`/vision`)

| 方法 | 路径 | 功能 | 认证 | 说明 |
|------|------|------|------|------|
| POST | `/vision/detect` | 目标检测 | ✅ | 上传图片→返回检测结果 |
| POST | `/vision/classify` | 图像分类 | ✅ | 食材分类（荤/素/锅底） |
| POST | `/vision/compare` | 视觉比对 | ✅ | 与标准图对比（质检用） |

**POST /vision/detect 请求**:
```json
{
  "image": "base64_encoded_image_data",
  "model": "yolov8n",  // 可选模型选择
  "threshold": 0.5      // 置信度阈值
}
```

**POST /vision/detect 响应 (200)**:
```json
{
  "detections": [
    {
      "class": "hot_pot_ingredient",
      "confidence": 0.92,
      "bbox": [x1, y1, x2, y2],
      "label": "毛肚"
    }
  ],
  "inference_time_ms": 45,
  "model_version": "v1.0"
}
```

---

### 3.5 模块5: 数据引擎 (`/data`)

| 方法 | 路径 | 功能 | 认证 | 说明 |
|------|------|------|------|------|
| GET | `/data/predictions` | 销量预测 | ✅ | 返回未来7天预测 |
| GET | `/data/waste-stats` | 损耗统计 | ✅ | 日/周/月损耗数据 |
| POST | `/data/backtest` | 回测分析 | ✅ | 策略回测（MAPE等指标） |
| GET | `/data/alerts` | 预警列表 | ✅ | 未处理的预警 |

---

### 3.6 模块6: 仓库IoT (`/warehouse`)

| 方法 | 路径 | 功能 | 认证 | 说明 |
|------|------|------|------|------|
| GET | `/warehouse/sensors` | 传感器列表 | ✅ | 温湿度/重量/门磁传感器 |
| GET | `/warehouse/sensors/{id}/readings` | 传感器读数 | ✅ | 最新读数+历史趋势 |
| POST | `/warehouse/sensors/{id}/calibrate` | 校准传感器 | ✅ | 偏移量校正 |
| GET | `/warehouse/inventory` | 库存快照 | ✅ | 当前库存量 |

---

### 3.7 模块7: SOP合规 (`/sop`)

| 方法 | 路径 | 功能 | 认证 | 说明 |
|------|------|------|------|------|
| GET | `/sop/rules` | SOP规则列表 | ✅ | 所有SOP检查项 |
| GET | `/sop/compliance` | 合规状态 | ✅ | 今日执行情况 |
| POST | `/sop/check` | 执行检查 | ✅ | 手动触发某项SOP检查 |

---

### 3.8 模块8: 知识库 (`/knowledge`)

| 方法 | 路径 | 功能 | 认证 | 说明 |
|------|------|------|------|------|
| POST | `/knowledge/search` | 知识检索 | ✅ | RAG语义搜索 |
| POST | `/knowledge/qa` | 智能问答 | ✅ | FAQ自动回答 |
| GET | `/knowledge/categories` | 知识分类 | ✅ | 目录结构 |

**POST /knowledge/search 请求**:
```json
{
  "query": "毛肚怎么保存",
  "top_k": 5,
  "category": "storage"  // 可选分类过滤
}
```

---

### 3.9 模块9: 货品主数据 (`/products`) ⭐ 新增

详见 [D1-S01_货品主数据详细设计_v1.0.md](./D1-S01_货品主数据详细设计_v1.0.md) 第4章

| 方法 | 路径 | 功能 | 认证 |
|------|------|------|------|
| GET | `/products` | 货品列表(分页/搜索/筛选) | ✅ |
| GET | `/products/stats` | 统计概览 | ✅ |
| GET | `/categories` | 品类列表 | ✅ |
| GET | `/products/{sku_code}` | 货品详情 | ✅ |
| POST | `/products` | 新建货品 | ✅ |
| PUT | `/products/{sku_code}` | 更新货品 | ✅ |
| POST | `/products/{sku_code}/lock` | 锁定货品 | ✅ |
| POST | `/products/{sku_code}/unlock` | 解锁货品 | ✅ |
| DELETE | `/products/{sku_code}` | 删除货品 | ✅ |
| POST | `/products/init` | 初始化种子数据 | ✅ |
| POST | `/products/{sku_code}/change` | 提交变更申请 | ✅ |
| GET | `/products/changes` | 变更申请列表 | ✅ |
| POST | `/products/changes/{id}/approve` | 审批变更 | ✅ |

---

## 4. 前端调用示例

### 4.1 JavaScript (Fetch API)

```javascript
// 1. 登录
const loginRes = await fetch('/api/v1/auth/login', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ pin: '123456' }),
  credentials: 'include'  // 自动携带Cookie
});
const { session_id } = await loginRes.json();

// 2. 获取货品列表
const productsRes = await fetch('/api/v1/products?page=1&page_size=20&keyword=毛肚', {
  credentials: 'include'
});
const { total, items } = await productsRes.json();

// 3. 创建新货品
const createRes = await fetch('/api/v1/products', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({
    sku_code: 'FP-TEST-001',
    name: '测试肥牛',
    specification: '500g/盒',
    brand: '测试品牌',
    unit_price: 88.0,
    category: 'FROZEN_MEAT'
  }),
  credentials: 'include'
});
const newProduct = await createRes.json(); // HTTP 201
```

### 4.2 cURL 命令行

```bash
# 登录
curl -c cookies.txt -X POST http://localhost:9080/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"pin":"123456"}'

# 查看统计
curl -b cookies.txt http://localhost:9080/api/v1/products/stats

# 创建货品
curl -b cookies.txt -X POST http://localhost:9080/api/v1/products \
  -H "Content-Type: application/json" \
  -d '{"sku_code":"FP-NEW-001","name":"新品","specification":"1kg/件","brand":"品牌A","unit_price":50,"category":"FROZEN_MEAT"}'

# 锁定货品
curl -b cookies.txt -X POST http://localhost:9080/api/v1/products/FP-NEW-001/lock
```

---

## 5. 版本历史与变更日志

| 版本 | 日期 | 变更内容 | 作者 |
|------|------|----------|------|
| v1.0 | 2026-08-01 | 初始版本，覆盖9个模块42个端点 | AI Assistant |

### v1.0 变更明细

**新增**:
- 模块9: 货品主数据管理 (`product_master_api.py`) — 13个端点
- 统一错误码定义
- 前端调用示例 (JS + cURL)

**确认**:
- 模块1-8 接口保持不变（向后兼容）

---

## 附录A: OpenAPI Schema 导出

Edge UI 启动后可访问自动生成的 API 文档：

```
http://localhost:9080/docs     # Swagger UI
http://localhost:9080/redoc    # ReDoc
```

FastAPI 自动从 Pydantic 模型和路由函数生成完整的 OpenAPI 3.0 schema。

---

> **下一步**: D1-S02 开发时补充 `receiving_api.py` 的接口规范
