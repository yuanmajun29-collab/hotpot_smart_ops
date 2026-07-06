# 🍲 火锅后厨智能平台 — 项目全貌

> 整理日期：2026-07-05 · Conductor：小马

---

## 一、项目定位

为火锅餐饮连锁提供**边缘AI + 云端管理**的智能运营平台。首单：玉环店（store_yuhuan）。

**核心价值**：数据不出店 → Jetson边缘推理 → 云端Dashboard管理。

---

## 二、系统架构

```
┌─────────────────────────────────────────────┐
│                  云端 (Mac/Hub)              │
│  ┌──────────┐  ┌──────────┐  ┌───────────┐ │
│  │ Hub :8098│  │Dashboard │  │ 数据库     │ │
│  │ FastAPI  │  │ :9120    │  │ hub.db    │ │
│  └────┬─────┘  └──────────┘  └───────────┘ │
└───────┼─────────────────────────────────────┘
        │ HTTP
┌───────┴─────────────────────────────────────┐
│              Jetson Orin 32GB (边缘)         │
│  ┌────────────┐          ┌────────────┐     │
│  │ 前厅 :9100 │          │ 后厨 :9200 │     │
│  │ 桌台/客流  │          │ YOLO→CLIP  │     │
│  │ ONNX推理   │          │ →VLM 三级  │     │
│  └────────────┘          └────────────┘     │
│          │                      │           │
│     ┌────┴────┐           ┌────┴────┐       │
│     │ IPC摄像头│           │ IPC摄像头│       │
│     │ 前厅监控 │           │ 后厨监控 │       │
│     └─────────┘           └─────────┘       │
└─────────────────────────────────────────────┘
```

---

## 三、目录结构

```
hotpot_smart_ops/
├── edge/                          ← 边缘端（Jetson部署）
│   ├── front-hall/                ← 前厅
│   │   ├── docker/                Dockerfile + compose
│   │   ├── server.py              FastAPI :9100
│   │   ├── table_state.onnx       桌台状态识别
│   │   ├── stream/                摄像头流管理
│   │   ├── store_forward.py       断网本地缓存
│   │   └── iot_mock/              IoT传感器模拟
│   ├── kitchen/                   ← 后厨
│   │   ├── docker/                Dockerfile + compose
│   │   ├── server.py              FastAPI :9200
│   │   ├── pipeline/              YOLO+CLIP+VLM 三级推理
│   │   ├── bridge_waste_vision.*  推理→Hub 桥接
│   │   ├── kitchen_compliance.onnx 后厨合规检测
│   │   └── rknn_deploy/           RKNN 部署备选
│   └── shared/                    ← 共用（rsync不上镜像）
│       ├── detector/              检测器基类
│       ├── config/                管道配置
│       ├── systemd/               自启服务
│       ├── deploy.sh              增量部署
│       └── scripts/               模型下载
├── hotpot_platform/                      ← 云端
│   ├── cloud/event_hub/           Hub API :8098
│   │   ├── app.py                 FastAPI入口
│   │   ├── routers/               API路由
│   │   │   ├── vlm.py            /v1/vlm/waste-estimate
│   │   │   ├── iot.py            IoT设备管理
│   │   │   ├── cost.py           成本分析
│   │   │   ├── tasks.py          任务管理
│   │   │   └── admin.py          管理后台
│   │   ├── db.py                  数据库
│   │   └── auth.py                认证
│   └── dashboard/                 静态前端 :9120
│       ├── vlm-demo.html          智能识别页 ✅
│       ├── index.html             首页
│       ├── cost.html              成本分析
│       ├── cockpit.html           驾驶舱
│       └── admin/                 管理后台
├── tests/                         测试（37个文件）
├── docs/                          文档+架构决策
├── demo/data/                     演示数据
└── shared/                        前后端共用schema
```

---

## 四、功能模块 & 状态

### 🔵 边缘推理（Jetson）

| 模块 | 功能 | 状态 | 备注 |
|:--|:--|:--|:--|
| 后厨 VLM | Ostrakon-VL 废料识别 | ✅ 已验证 | 4类识别（57s） |
| 后厨 YOLO | 目标检测 | ⚠️ 待容器化 | TensorRT容器内ONNX解析失败 |
| 后厨 CLIP | 场景分类 | ⚠️ 待容器化 | 同上 |
| 后厨 Docker | 容器化推理API | ⚠️ 框架就绪 | VLM卡llama共享库 |
| 前厅 Docker | 桌台/客流推理 | ⚠️ 未构建 | Dockerfile已写 |
| IPC抓帧 | 摄像头RTSP拉流 | ⚠️ 未配 | 缺RTSP地址 |
| 设备管理 | 注册/心跳/配流 | ❌ 未开发 | 最大缺口 |

### 🟢 云端平台

| 模块 | 功能 | 状态 | 备注 |
|:--|:--|:--|:--|
| Hub API | 废料识别接收 | ✅ | /v1/vlm/waste-estimate |
| Hub API | 事件管理 | ✅ | GET/POST /events |
| Hub API | 图片上传 | ✅ | /v1/images |
| Hub API | 成本分析 | ✅ | /v1/cost/* |
| Hub API | 设备管理 | ⚠️ 基础 | IoT profiles存在，缺配流 |
| Hub API | 认证 | ✅ | X-Api-Key |
| Dashboard | 智能识别页 | ✅ | vlm-demo.html 完整 |
| Dashboard | RBAC面板 | ❌ | 原小卡任务，未完成 |
| Dashboard | 设备管理页 | ❌ | 对应设备管理API |
| Dashboard | 首页/驾驶舱 | ⚠️ | 页面存在，未接真实数据 |

### 🔴 缺失功能

| 优先级 | 功能 | 说明 |
|:--|:--|:--|
| 🔴 P0 | 设备管理（盒子注册→配流） | 盒子没法上线管理 |
| 🔴 P0 | IPC摄像头RTSP配置 | 缺源没法推理 |
| 🟡 P1 | 后厨Docker全链路 | 现在裸机可跑，容器化需修共享库 |
| 🟡 P1 | Dashboard RBAC | 多门店多角色需要 |
| 🟡 P1 | 前厅Docker构建验证 | 桌台/客流还没跑过 |
| 🟢 P2 | 代码Git push | 等VPN |
| 🟢 P2 | CR流程规范化 | 火锅项目未走CR |

---

## 五、部署方式

| 组件 | 部署 | 位置 |
|:--|:--|:--|
| Hub API | uvicorn 直接起 | Mac :8098 |
| Dashboard | python http.server | Mac :9120 |
| 后厨推理 | bridge_waste_vision.sh | Jetson裸机 (可行) |
| 后厨 API | Docker hotpot-kitchen | Jetson :9200 (框架就绪) |
| 前厅 API | Docker hotpot-front-hall | Jetson :9100 (未构建) |
| 模型权重 | rsync 增量 | Jetson /opt/hotpot-infer/ |

---

## 六、数据流

```
IPC摄像头 → 抓帧(jpg) → Jetson推理 → bridge脚本
                                        ↓
                              POST /v1/vlm/waste-estimate
                                        ↓
                                   Hub入库
                                        ↓
                              Dashboard :9120 展示
```

---

## 七、团队分工

| 角色 | 负责 | 状态 |
|:--|:--|:--|
| 🐴 小马 | 总指挥、规整工作、Jetson agent | 活跃 |
| 🧠 小居 | 代码审查、Dashboard前端、后端API | 已handoff接手 |
| 🏗️ 小抠 | 后端代码 | ❌ CLI未认证 |
| 🖥️ 小卡 | 前端开发 | ❌ 无回写 |
