# P0修复: API归一 + 离线缓冲 — 规格说明书

> 日期: 2026-07-16 | 关联: docs/architecture-deep-review.md
> 代码根: ~/company/products/to-b/hotpot_smart_ops/

## 任务1: API归一 (US-001, US-002, SC-002/US-003)

### 1.1 路由前缀统一为 `/api/v1/`

**当前状态 (5种前缀混用):**
| 文件 | 当前前缀 | 端点 |
|------|---------|------|
| routers/devices.py | `/v1/devices/` | register, heartbeat, pull-config, config, list, detail |
| routers/vlm.py | `/v1/vlm/` | waste-estimate, images |
| routers/kitchen.py | `/api/kitchen/` | waste/stats, trend, alerts, alerts/check, alerts/{id}/ack |
| routers/feedback.py | `/v1/feedback/` | submit, list, stats, rebuild |
| routers/cost.py | `/v1/cost/` | loss-risk, loss-budget, forecast, etc |
| routers/sop.py | `/v1/sop/` | assign, status, ask, compliance |
| routers/receiving.py | `/v1/receiving/` | quality-tap, submit, checkin, list |
| routers/daily_report.py | `/v1/daily/report` | 日报 |
| routers/staff_behavior.py | `/api/staff-behavior/` | event, stats, alerts, timeline |
| routers/admin_users.py | `/v1/admin/` | users list |
| edge/agent/modules/front_hall_infer.py | `/api/scene/` | analyze |

**目标:** 所有API统一为 `/api/v1/{domain}/*`

| Domain | 新路径 |
|--------|--------|
| devices | `/api/v1/devices/*` |
| vlm | `/api/v1/vlm/*` |
| kitchen | `/api/v1/kitchen/*` |
| feedback | `/api/v1/feedback/*` |
| cost | `/api/v1/cost/*` |
| sop | `/api/v1/sop/*` |
| receiving | `/api/v1/receiving/*` |
| daily_report | `/api/v1/daily/*` |
| staff_behavior | `/api/v1/staff-behavior/*` |
| admin | `/api/v1/admin/*` |
| scene | `/api/v1/scene/*` (edge agent) |
| auth | `/auth/*` (保持不变，认证独立) |

### 1.2 统一错误响应格式

**目标格式:**
```json
{
  "error": {
    "code": "DEVICE_NOT_FOUND",
    "message": "设备不存在: jetson-yuhuan-01",
    "details": {"device_id": "jetson-yuhuan-01"}
  }
}
```

**新增文件:** `hotpot_platform/cloud/event_hub/common/errors.py`
- ErrorResponse Pydantic 模型
- AppError 异常基类 + 子类 (NotFoundError, ValidationError, UnauthorizedError, ConflictError)
- `register_error_handlers(app)` 全局 exception handler

成功响应保持 `{"ok": True, ...}` 格式不变。

### 1.3 Dashboard集中配置

**修改文件:** `hotpot_platform/dashboard/serve.py`
- 新增 `--hub-url` 参数 (默认 `http://127.0.0.1:8098`)
- 新增 `GET /config.js` 端点注入 `window.HOTPOT_CONFIG = {hubUrl: "...", apiPrefix: "/api/v1"}`

**修改文件:**
- `front-hall.html` → 从 `const HUB = 'http://192.168.2.240:8098'` 改为读取 `window.HOTPOT_CONFIG.hubUrl`
- `admin.html` → 同上
- `kitchen-vision.html` → 同上
- `edge-vision.html` → 同上
- `index.html` → 注入 `<script src="/config.js"></script>` (如果尚未)
- `assets/core.js` → `hubUrl()` 优先读 `window.HOTPOT_CONFIG`

**Dashboard文件需同时更新API前缀：** 各页面中硬编码的 `/v1/` `/api/` 改为读 `window.HOTPOT_CONFIG.apiPrefix`

### 1.4 旧路由兼容

每个改过前缀的路由模块新增 Deprecation 兼容：
```python
# 在 router 定义后追加旧路由，返回 301 + Deprecation header
@router.api_route("/v1/devices/{path:path}", methods=["GET","POST","PUT","DELETE"])
def _deprecated_v1_devices(path: str, request: Request):
    return RedirectResponse(url=f"/api/v1/devices/{path}", status_code=301,
                           headers={"X-Deprecated": "true", "X-Deprecation-Date": "2026-09-01"})
```

各模块只需添加一个通配fallback路由。旧 `/v1/` → 301 → 新 `/api/v1/`。

## 任务2: 离线缓冲 (RB-001, AV-003)

### 2.1 问题

推理结果 (`kitchen/inference/pipeline.py` `post_to_hub()`) 仅内存重试3次，断网即丢。
对比：`front_hall/bridge/store_forward.py` 已有磁盘缓冲实现，但推理管线未接入。

### 2.2 方案

1. **新增 `edge/agent/buffer.py`** — 通用推断结果缓冲层
   - SQLite 本地队列 (`inference_buffer` 表)
   - `enqueue(result: dict)` — 推理结果入队
   - `flush(max_per_batch=50)` — 批量POST到Hub，成功→删除，失败→保留+退避
   - 后台 flush worker (asyncio task, 每30s一次)
   - 断点续传：Agent重启时从SQLite恢复未发送结果

2. **修改 `kitchen/inference/pipeline.py`**
   - `post_to_hub()` 改为调用 buffer (不再直接POST)
   - 保留原有直接POST能力(fallback)，通过 `--hub` 参数直接POST时走原路径

3. **修改 `edge/agent/server.py`**
   - 启动时创建 `InferenceBuffer` 实例
   - 启动后台 `_buffer_flush_loop()` coroutine
   - 注册 `HOTPOT_BUFFER_DIR` 环境变量 (默认 `/tmp/hotpot_buffer`)

4. **修改 `edge/agent/modules/kitchen_infer.py`** (如存在)
   - 现有 kitchen 推理模块改为走 buffer

### 2.3 接口契约

```python
class InferenceBuffer:
    def __init__(self, db_path: str, hub_url: str, api_key: str = ""): ...
    async def enqueue(self, endpoint: str, payload: dict) -> str: ...  # 返回 event_id
    async def flush(self, max_per_batch: int = 50) -> int: ...         # 返回成功数
    async def stats(self) -> dict: ...                                  # {queued, total_sent, total_failed}
```

### 2.4 测试用例

- 断网场景：buffer.enqueue() → 断网 → buffer.flush() 失败 → 队列保留 → 网络恢复 → flush 成功
- 重启恢复：buffer.enqueue() → kill process → restart → flush → 队列中数据恢复并发送
- 上限控制：队列超 max_items → FIFO 丢弃最旧 (保留最新)
- Hub 500：flush → Hub 返回 500 → 保留队列 → 下次重试

### 2.5 文件清单

| 文件 | 操作 |
|------|------|
| `hotpot_platform/cloud/event_hub/common/errors.py` | **新增** |
| `hotpot_platform/cloud/event_hub/app.py` | 修改: 注册 error handlers |
| `hotpot_platform/cloud/event_hub/routers/devices.py` | 修改: 前缀 `/v1/`→`/api/v1/`, 加 deprecated 通配 |
| `hotpot_platform/cloud/event_hub/routers/kitchen.py` | 修改: 前缀 `/api/`→`/api/v1/` |
| `hotpot_platform/cloud/event_hub/routers/vlm.py` | 修改: 前缀 `/v1/`→`/api/v1/` |
| `hotpot_platform/cloud/event_hub/routers/feedback.py` | 修改: 前缀 `/v1/`→`/api/v1/` |
| `hotpot_platform/cloud/event_hub/routers/cost.py` | 修改: 前缀 `/v1/`→`/api/v1/` |
| `hotpot_platform/cloud/event_hub/routers/sop.py` | 修改: 前缀 `/v1/`→`/api/v1/` |
| `hotpot_platform/cloud/event_hub/routers/receiving.py` | 修改: 前缀 `/v1/`→`/api/v1/` |
| `hotpot_platform/cloud/event_hub/routers/daily_report.py` | 修改: 前缀 `/v1/`→`/api/v1/` |
| `hotpot_platform/cloud/event_hub/routers/staff_behavior.py` | 修改: 前缀 `/api/`→`/api/v1/` |
| `hotpot_platform/cloud/event_hub/routers/admin_users.py` | 修改: 前缀 `/v1/`→`/api/v1/` |
| `edge/agent/modules/front_hall_infer.py` | 修改: `/api/scene/`→`/api/v1/scene/` |
| `edge/agent/buffer.py` | **新增** |
| `edge/agent/server.py` | 修改: 初始化/启动 buffer |
| `edge/kitchen/inference/pipeline.py` | 修改: post_to_hub 走 buffer |
| `edge/front_hall/inference/pipeline.py` | 检查是否需要 buffer |
| `hotpot_platform/dashboard/serve.py` | 修改: 新增 `/config.js` + `--hub-url` |
| `hotpot_platform/dashboard/front-hall.html` | 修改: 集中配置 |
| `hotpot_platform/dashboard/admin.html` | 修改: 集中配置 |
| `hotpot_platform/dashboard/kitchen-vision.html` | 修改: 集中配置 |
| `hotpot_platform/dashboard/edge-vision.html` | 修改: 集中配置 |
| `hotpot_platform/dashboard/assets/core.js` | 修改: hubUrl 优先读全局配置 |
