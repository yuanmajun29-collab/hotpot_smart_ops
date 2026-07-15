# 火瞳 — 架构设计文档

> 基于现有代码架构 + 6大模块全场景需求

---

## 一、系统架构总览

```
                      📱 Dashboard (:9120)
                           │ REST API
                      ☁️ Hub (:8098)
                    FastAPI + 多租户
                           │
        ┌──────────────────┼──────────────────┐
        ▼                  ▼                  ▼
   🧠 Edge Agent     🧠 Edge Agent      🧠 Edge Agent
   (门店A-Jetson)    (门店B-Jetson)     (门店C-Jetson)
        │
   ┌────┼────┬────┬────┐
   ▼    ▼    ▼    ▼    ▼
 后厨  前厅  食材  员工  SOP
```

## 二、分层架构

| 层 | 组件 | 技术 | 端口 |
|----|------|------|:--:|
| **展示层** | Dashboard | Vue3 + ECharts | :9120 |
| **数据层** | Hub API | FastAPI + SQLite/PostgreSQL | :8098 |
| **调度层** | Edge Agent | FastAPI | :9100 |
| **推理层** | YOLO / CLIP / VLM / Count | PyTorch + TensorRT | 内部 |
| **感知层** | IPC摄像头 / IoT传感器 | RTSP / MQTT | — |

## 三、核心模块设计

### 3.1 后厨模块 (`edge/kitchen/`)

```
YOLO检测(8ms) → CLIP分类(50ms) → VLM语义(320ms+) → Count计数
      可插拔 stages/                    规则引擎 rules.py
```

| 组件 | 文件 | 状态 |
|------|------|:--:|
| 管线调度 | `pipeline.py` | ✅ |
| YOLO引擎 | `stages/yolo.py` | ✅ |
| CLIP引擎 | `stages/clip.py` | ✅ |
| VLM引擎 | `stages/vlm.py` | ✅ |
| 推理规则 | `rules.py` | ✅ |
| Count计数 | **新增** | 📋 |

### 3.2 前厅模块 (`edge/front_hall/`)

| 模式 | 策略 | 耗时 | 场景 |
|------|------|------|------|
| plan_b | YOLO规则推断 | ~40ms | 默认：空桌/需清理/有人 |
| plan_a | YOLO+CLIP混合 | ~190ms | 精确：语义细分 |

### 3.3 食材监管（新增 `edge/receiving/`）

```
电子秤 → 重量数据(MQTT)
   +                      → 比较判断 → Hub
摄像头 → CV品质检测(YOLO)
```

### 3.4 员工行为（新增 `edge/staff/`）

```
YOLO检测人 + PPE分类(着装) → 行为规则(交头接耳/停留)
```

### 3.5 设备管理 (`edge/agent/`)

| 端点 | 功能 |
|------|------|
| `POST /v1/devices/register` | 设备注册 |
| `POST /v1/devices/{id}/heartbeat` | 心跳续期 |
| `POST /v1/devices/{id}/pull-config` | 配置拉取 |
| `PUT /v1/devices/{id}/config` | 模块配置推送 |

## 四、数据流

```
摄像头(RTSP) → IPC抓帧 → YOLO检测 → 事件JSON
    → Hub :8098 → 入库 → Dashboard :9120 刷新
    → 日报生成(cron) → 微信推送(公众号模板消息)
```

## 五、部署架构

```
单店:
  Jetson Orin (推理) + PoE交换机 + 2-4摄像头

总部:
  Mac (Hub) + Dashboard + 日报cron

云端(未来):
  Docker Compose + PostgreSQL + Nginx
```

## 六、技术栈

| 层 | 选型 | 理由 |
|----|------|------|
| 检测 | YOLO26-L | 成熟/TensorRT可加速 |
| 分类 | CLIP | 零样本/场景灵活 |
| 语义 | VLM (llama.cpp) | 已部署已验证 |
| 计数 | Count Anything | 文本引导/无需重训 |
| 后端 | FastAPI | 异步/已验证 |
| 前端 | Vue3 + ECharts | Dashboard已有 |
| 边缘 | Jetson Orin NX | 29GB/12核 |
| 协议 | RTSP / MQTT / REST | 标准化 |

---

*关联: [PRD](./火锅AI-PRD-产品需求文档.md) | [开发计划](./火锅AI-开发计划.md) | [测试用例](./火锅AI-测试用例.md)*
