# K01 后厨废料实时检测 — 测试用例

> 版本 1.0 | 2026-07-16 | 白盒 + 黑盒
>
> **PRD 验收标准**: YOLO检测废料 → Dashboard推送，延迟 <5s，计数误差 <20%
> **关联 Spec**: [spec-K01-kitchen-waste-detection.md](./spec-K01-kitchen-waste-detection.md)

---

## 测试环境

| 环境 | 用途 | 地址 |
|------|------|------|
| 本地 Mac | 白盒单元测试 (pytest) | localhost |
| Jetson 实机 | 集成测试 (Count Server) | 192.168.2.240:8100 |
| Mac Hub | 集成测试 (事件接收) | localhost:8098 |
| Mac Dashboard | E2E 验收 | localhost:3000 |

---

## 一、白盒测试（内部实现）

### 1.1 Stage Count — `stage_count.py`

| ID | 用例 | 前置条件 | 步骤 | 预期结果 |
|----|------|---------|------|---------|
| **TC-W1** | 正常计数 — 单个 ROI | ctx 有 yolo_result.detections，每个带 roi_path | 调用 `run(frame, ctx)` | 返回 `total_count > 0`，`status="ok"`，`details[]` 每项有 count + inference_ms |
| **TC-W2** | 无 ROI 可计数 | ctx 中 detections 无 roi_path | 调用 `run(frame, ctx)` | 返回 `status="skipped"`, `reason="no_rois_for_count"`, `total_count=0` |
| **TC-W3** | Jetson 离线 — 降级处理 | Jetson :8100 不可达 | 调用 `run(frame, ctx)` | 每个 ROI 返回 `status="error"`, `count=0`, `api_errors == len(rois)`, 整体 `status="partial"` |
| **TC-W4** | Count API 超时 | 模拟网络延迟 >10s | 调用 `run(frame, ctx)` | 超时 ROI 返回 `error="count API timeout"`, `count=0` |
| **TC-W5** | 混合 ROI 来源 | ctx 中 yolo detections + vlm_results 各有 ROI | 调用 `run(frame, ctx)` | `seen_paths` 去重生效，vlm ROI 不重复计数 |
| **TC-W6** | 计数注入 ctx.items | ctx 有 clip_results/vlm_results | count 完成后检查 ctx | `clip_results[].count` 和 `vlm_results[].count` 已注入正确值 |
| **TC-W7** | Count API 返回非整数 | Mock /count 返回 `{"count": 3.7}` | 调用 `run(frame, ctx)` | count 转为 `int(3.7) = 3`，不抛异常 |
| **TC-W8** | Count API 返回超限值 | Mock /count 返回 `{"count": 999}` | 调用 `run(frame, ctx)` | count 值透传（边界检验在 pipeline 聚合层处理） |

### 1.2 Pipeline 聚合 — `pipeline.py`

| ID | 用例 | 前置条件 | 步骤 | 预期结果 |
|----|------|---------|------|---------|
| **TC-W9** | 完整 4-stage 管线 | `stage_count.py` 正常 | `run_pipeline(frame)` | `result["stages"]["count"]` 存在，`result["total_waste_count"]` 为计数汇总 |
| **TC-W10** | VLM skip 模式 | `skip_vlm=True` | `run_pipeline(frame, skip_vlm=True)` | VLM stage 状态为 `"skipped"`，Count 仍正常执行 |
| **TC-W11** | YOLO 无检测→管线提前终止 | YOLO 返回空 detections | `run_pipeline(frame)` | `status="ok"`, `reason="no_detections"`，CLIP/VLM/Count 均不执行 |
| **TC-W12** | YOLO 故障→管线返回 error | YOLO stage 返回 `status="error"` | `run_pipeline(frame)` | `status="degraded"`, `error` 字段描述 YOLO 故障 |
| **TC-W13** | Count API URL 可配置 | 传入 `count_api_url` 参数 | `run_pipeline(frame, count_api_url="http://192.168.2.240:8100")` | ctx["count_api_url"] 使用传入值 |
| **TC-W14** | total_waste_count 聚合 | 多个 ROI 各有 count | pipeline 完成后检查 | `result["total_waste_count"]` == sum of all detail counts |

### 1.3 Hub 事件处理 — `waste_estimate.py`

| ID | 用例 | 前置条件 | 步骤 | 预期结果 |
|----|------|---------|------|---------|
| **TC-W15** | Edge 路径 — items + total_waste_count | items 非空，total_waste_count=15 | `compute_waste_estimate(items=..., total_waste_count=15)` | 返回含 `total_waste_count: 15`，不触发 mock |
| **TC-W16** | Mock 路径 — 无 items | items=None/[] | `compute_waste_estimate(image_ref="...")` | 返回 mock 数据，含 1 个随机 item |
| **TC-W17** | image_url 提取 | image_ref 含 `/static/` 路径 | `compute_waste_estimate(image_ref="http://hub/static/waste/img.jpg")` | 返回含 `image_url: "/static/waste/img.jpg"` |
| **TC-W18** | 空 items + image_ref fallback | items=[] 但有 image_ref | `compute_waste_estimate(items=[], image_ref="test.jpg")` | 走 Mock 路径，source="mock" |

### 1.4 Hub 路由 — `routers/kitchen.py`

| ID | 用例 | 前置条件 | 步骤 | 预期结果 |
|----|------|---------|------|---------|
| **TC-W19** | waste/stats 默认查询 | DB 有 7 天数据 | `GET /api/kitchen/waste/stats` | 返回 `days=7`, `trend` 长度=7, `daily` 有数据 |
| **TC-W20** | waste/stats 指定天数 | DB 有数据 | `GET /api/kitchen/waste/stats?days=3` | 返回最近 3 天数据 |
| **TC-W21** | waste/stats 无数据 | 空 DB | `GET /api/kitchen/waste/stats` | 返回 `trend=[]`, `daily=[]`, 不报错 |
| **TC-W22** | waste/stats days 超限 | — | `GET /api/kitchen/waste/stats?days=100` | 返回 422，`days` 范围校验失败 |
| **TC-W23** | waste/stats 跨门店越权 | auth 绑定 store_yuhuan | `GET /api/kitchen/waste/stats?store_id=store_jiaojiang` | 返回 403 |
| **TC-W24** | live_count 补充 | 内存事件中有 vlm_waste_estimate | 查询 stats | `live_count > 0`，统计内存中未落 DB 的最新计数 |

---

## 二、黑盒测试（外部接口）

### 2.1 Jetson Count Server (`:8100`)

| ID | 用例 | 方法 | 输入 | 预期输出 |
|----|------|:---:|------|---------|
| **TC-B1** | Health 正常 | GET /health | — | 200, `{"status":"ok","model_loaded":true}` |
| **TC-B2** | /count 正常计数 | POST /count | 含明显可数物体图片 (如3个独立物件) | 200, `{"status":"ok","count":3}` |
| **TC-B3** | /count 空图 | POST /count | 纯色空白图 | 200, `{"status":"ok","count":0}` |
| **TC-B4** | /count 缺少 image | POST /count | 无 image 字段 | 400, `{"status":"error","error":"no image provided"}` |
| **TC-B5** | /count 大图 | POST /count | >10MB 图片 | 413 或 400 |
| **TC-B6** | /count 非图片格式 | POST /count | text/plain 文件 | 400, `{"status":"error"}` |
| **TC-B7** | /count 高并发 | POST /count | 10 次连续请求，间隔 100ms | 全部返回 200，count 值稳定 |
| **TC-B8** | 模型首次加载 | POST /count | 冷启动首次请求 | 可能耗时 30-120s，最终返回 200 |

### 2.2 Hub 废料事件 (`:8098`)

| ID | 用例 | 方法 | 输入 | 预期输出 |
|----|------|:---:|------|---------|
| **TC-B9** | 提交完整废料事件 (含计数) | POST /v1/vlm/waste-estimate | items 含 count + total_waste_count | 200, `{"ok":true,"event_id":"..."}` |
| **TC-B10** | 提交无计数的事件 (兼容) | POST /v1/vlm/waste-estimate | items 无 count 字段 | 200, 正常接收 |
| **TC-B11** | 未认证请求 | POST /v1/vlm/waste-estimate | 无 Authorization header | 401 |
| **TC-B12** | 跨门店写入 | POST /v1/vlm/waste-estimate | store_id 与 token 门店不一致 | 403 |
| **TC-B13** | 空 items + 无 image_ref | POST /v1/vlm/waste-estimate | items=[], 无 image_ref | 422 |
| **TC-B14** | 超长 zone 字段 | POST /v1/vlm/waste-estimate | zone 为 1000 字符长串 | 200（不截断）或 422 |

### 2.3 Hub 统计查询 (`:8098`)

| ID | 用例 | 方法 | 输入 | 预期输出 |
|----|------|:---:|------|---------|
| **TC-B15** | 查询 7 天趋势 | GET /api/kitchen/waste/stats?days=7 | 已有 7 天事件数据 | 200, `trend` 长度=7, `dates` 长度=7 |
| **TC-B16** | 查询 1 天 | GET /api/kitchen/waste/stats?days=1 | 有今天数据 | 200, `trend` 长度=1 |
| **TC-B17** | days=0 边界 | GET /api/kitchen/waste/stats?days=0 | — | 422 (ge=1) |
| **TC-B18** | days=90 边界 | GET /api/kitchen/waste/stats?days=90 | — | 200 |
| **TC-B19** | 无认证 | GET /api/kitchen/waste/stats | 无 Authorization | 401 |
| **TC-B20** | days=1 且无数据 | GET /api/kitchen/waste/stats?days=1 | 空 DB | 200, `trend=[0]`, `dates=[今天]` |

### 2.4 Dashboard (`kitchen-count.html :3000`)

| ID | 用例 | 前置条件 | 操作 | 预期结果 |
|----|------|---------|------|---------|
| **TC-B21** | 页面加载 | Hub :8098 在线 | 打开 kitchen-count.html | Hero 卡片显示数值（非 "--"），"Hub 在线" 徽章 |
| **TC-B22** | Hub 离线显示 | Hub :8098 离线 | 打开 kitchen-count.html | "Hub 离线" 徽章，hero 保留上次值或 "--" |
| **TC-B23** | 30s 自动刷新 | — | 等待 30s | 页面数据更新（network 面板可见新请求） |
| **TC-B24** | 7日趋势柱状图 | 有 7 天数据 | 查看 chart 区域 | 7 根柱子，高度与 trend 值成正比，日期标签格式 MM-DD |
| **TC-B25** | SKU 品类分布 | 有多个 SKU 数据 | 查看 sku-list 区域 | 按 count 降序排列，条形宽度与占比成正比 |
| **TC-B26** | 事件日志 | 有多日事件 | 查看 event-log 区域 | 最近有事件的日子在前，显示 date + total_count + top items |
| **TC-B27** | 空数据状态 | DB 无数据 | 打开页面 | Hero 显示 "--"、"0"，图表/列表显示 "暂无数据" |

---

## 三、E2E 全链路测试

| ID | 场景 | 链路 | 步骤 | 验收标准 |
|----|------|------|------|---------|
| **TC-E1** | 端到端废料计数 | 摄像头 → YOLO → Count → Hub → Dash | 1. 放置已知数量废料 (如 10 件) 2. 触发推理 3. 等待 Dashboard 刷新 | Dashboard 显示废料总数与实际偏差 < 20% |
| **TC-E2** | 端到端延迟 | 同上 | 1. 记录 frame 采集时间戳 2. Dashboard 显示该 frame 数据的时间戳 | Δt < 5s |
| **TC-E3** | Jetson 离线恢复 | 同上 | 1. 断开 Jetson 网络 2. 等 30s 3. 恢复网络 | 离线期间 count=0 不阻塞；恢复后正常计数 |
| **TC-E4** | Hub 离线恢复 | 同上 | 1. 停止 Hub 2. 触发推理 3. 恢复 Hub | Pipeline 缓存事件，Hub 恢复后重传成功 |
| **TC-E5** | 多帧连续推理 | 同上 | 连续推理 100 帧 | 无内存泄漏，count 值稳定，无管道阻塞 |
| **TC-E6** | 计数准确性验证 | 同上 | 准备 3 组已知数量 (5/15/30件) 的测试场景 | 每组误差 < 20%：\|count_ai - count_gt\| / count_gt < 0.2 |

---

## 四、非功能测试

| ID | 类型 | 参数 | 目标 |
|----|------|------|------|
| **TC-N1** | 性能 — Count API 延迟 | 单张 ROI (640×480) | P50 < 100ms, P99 < 500ms |
| **TC-N2** | 性能 — Pipeline 总延迟 | 完整 4-stage（含 VLM） | P50 < 2s, P99 < 5s |
| **TC-N3** | 性能 — Dashboard API 响应 | GET /api/kitchen/waste/stats | < 500ms (含 DB 查询) |
| **TC-N4** | 长稳 — 72h 连续运行 | 每 30s 一次 pipeline | 无内存泄漏（RSS 增长 < 20%），无进程退出 |
| **TC-N5** | 并发 — 10 设备同时上报 | 10 个 Jetson 并发 POST waste-estimate | Hub CPU < 80%, 0 个 5xx 错误 |
| **TC-N6** | 安全 — API 未授权访问 | 不带 token 访问所有端点 | 全部返回 401 |
| **TC-N7** | 兼容 — Jetson Orin Nano | 在 Nano 上运行 Count Server | /health 正常，/count 延迟 < 500ms |
| **TC-N8** | 兼容 — 图片格式 | JPEG / PNG / WebP | 三种格式均返回有效 count |

---

## 五、测试数据

### 5.1 测试图片

| 图片 | 路径 | 用途 |
|------|------|------|
| 后厨实景 | `demo/data/real_kitchen.jpg` | YOLO 检测 + Count |
| 火锅废料 | `demo/data/real_hotpot_waste.jpg` | 废料分类 + Count |
| 简单厨房 | `demo/data/kitchen.jpg` | 空场景边界测试 |
| 空白图 | 生成纯色 640×480 JPEG | count=0 边界测试 |

### 5.2 Mock Count API 响应

```python
# 用于白盒测试的 mock 数据
MOCK_COUNT_RESPONSES = {
    "normal":     {"status": "ok", "count": 5},
    "empty":      {"status": "ok", "count": 0},
    "timeout":    {"status": "error", "error": "count API timeout (10s)", "count": 0},
    "offline":    {"status": "error", "error": "Connection refused", "count": 0},
    "large":      {"status": "ok", "count": 150},
    "non_int":    {"status": "ok", "count": 3.7},
}
```

---

## 六、测试执行优先级

| 优先级 | 用例范围 | 说明 |
|:---:|------|------|
| **P0** | TC-W1, TC-W3, TC-W9, TC-B1, TC-B2, TC-B3, TC-B9, TC-B15, TC-B21, TC-E1, TC-E2 | MVP 验收必须通过 |
| **P1** | TC-W2, TC-W4~W8, TC-W10~W14, TC-W15~W18, TC-B4~B8, TC-B10~B14, TC-B16~B20, TC-B22~B27, TC-E3~E6 | 试点完成前通过 |
| **P2** | TC-N1~N8, TC-W19~W24, TC-B8 | 生产就绪前通过 |

---

## 七、与现有测试用例的关系

现有测试（`tests/test_kitchen_yolo.py`, `tests/test_waste_estimate.py`）覆盖:
- YOLO 检测 (test_kitchen_yolo_detection)
- 空场景 (test_kitchen_yolo_empty_scene)
- 完整管道 (test_kitchen_full_pipeline)
- Hub mock 路径 (test_waste_estimate_mock_*)
- Edge 路径 (test_waste_estimate_edge_*)
- 图片流转 (test_waste_estimate_edge_with_image)
- 越权保护 (test_waste_estimate_cross_store_forbidden)

**新增用例（本文档增量）**:
- Count stage 白盒测试 (TC-W1 ~ TC-W8) — 全部新增
- Pipeline Count 聚合测试 (TC-W9 ~ TC-W14) — 全部新增
- Count API 黑盒测试 (TC-B1 ~ TC-B8) — 全部新增
- Dashboard E2E (TC-B21 ~ TC-B27) — 全部新增
- E2E 计数准确性 (TC-E1 ~ TC-E6) — 全部新增
- 非功能测试 (TC-N1 ~ TC-N8) — 全部新增
