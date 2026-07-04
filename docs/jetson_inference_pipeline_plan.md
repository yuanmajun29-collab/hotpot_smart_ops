# Jetson 边缘推理流水线 · 实施计划

> 2026-07-04 · v1.0 · 小马(Hermes) 整理
>
> 基于 2026-07-04 CLIP-Adapter GPU 基准实测结果 + 已有 ADR/接口协定

---

## 1. 总览

### 硬件

| 项目 | 规格 |
|:--|:--|
| 设备 | NVIDIA Jetson Orin |
| 系统 | L4T R34.1.1 / JetPack 5.0 |
| CPU | 12核 ARM64 (Cortex-A78AE) |
| 内存 | 29GB (可用 ~26GB) |
| GPU | Orin, 32GB VRAM, 67 INT8 TOPS |
| 磁盘 | 57G (已用 21G / 可用 34G) |

### 模型清单

| 模型 | 大小 | 推理引擎 | 延迟 | 角色 |
|:--|:--|:--|:--|:--|
| **yolo26l** | 147M (.pt + .onnx) | TensorRT FP16 | ~8ms | 🔍 **一级过滤**：目标检测 |
| **CLIP-Adapter** | 514KB (adapter) | PyTorch CUDA | **15.1ms** | 🔍 **二级分类**：少样本缺陷/食材分类 |
| **Ostrakon-VL-8B** | 5.0G (IQ4_XS) | llama.cpp CPU | ~300ms | 🧠 **三级分析**：场景理解/VLM |

### 流水线架构

```
┌──────────────────────────────────────────────────────────────────┐
│  IPC 摄像头 (RTSP)                                                │
│      │                                                            │
│      ▼  ipc_frame_grabber.py (systemd 常驻, 每10s抽帧)            │
│      │                                                            │
│      ▼  /tmp/ipc_frames/latest.jpg                                │
│      │                                                            │
│  ┌───▼─────────────────────────────────────────────────────────┐ │
│  │ 一级过滤: YOLO (TensorRT, Docker)                            │ │
│  │   ├─ 检测到异常目标 (zone/region) → 进入二级                  │ │
│  │   └─ 无异常 → 跳过 (不触发后续)                              │ │
│  └───┬─────────────────────────────────────────────────────────┘ │
│      │ 裁剪 ROI                                                   │
│      ▼                                                            │
│  ┌───▼─────────────────────────────────────────────────────────┐ │
│  │ 二级分类: CLIP-Adapter (PyTorch CUDA, Docker l4t-pytorch)    │ │
│  │   ├─ 1-Shot / Few-Shot 食材/缺陷分类                          │ │
│  │   └─ confidence < 阈值 → 进入三级                             │ │
│  └───┬─────────────────────────────────────────────────────────┘ │
│      │ 低置信度 / 需语义理解的帧                                   │
│      ▼                                                            │
│  ┌───▼─────────────────────────────────────────────────────────┐ │
│  │ 三级分析: Ostrakon-VL-8B (llama.cpp, CPU)                    │ │
│  │   ├─ 场景理解 (废料特征、餐余识别)                            │ │
│  │   └─ 输出结构化 JSON → POST Hub                               │ │
│  └───┬─────────────────────────────────────────────────────────┘ │
│      │                                                            │
│      ▼  HTTP POST                                                 │
│  ┌──────────────────────────────────────────────────────────────┐│
│  │ Mac 本机 Hub (:8088)                                          ││
│  │  POST /v1/vlm/waste-estimate                                  ││
│  │  → compute_waste_estimate → store.add_event                   ││
│  └──────────────────────────────────────────────────────────────┘│
└──────────────────────────────────────────────────────────────────┘
```

---

## 2. 组件详解

### 2.1 ipc_frame_grabber — 视频采集层

**文件**: `/root/ipc_frame_grabber.py`  
**配置**: `/root/ipc_config.yml`  
**运行方式**: `ipc-grabber.service` (systemd, 开机自启)

```yaml
# ipc_config.yml (当前配置)
stream_url: "rtsp://admin:password@192.168.1.64:554/Streaming/Channels/101"
interval_seconds: 10
save_latest_only: true
auto_infer: false              # 当前关闭；届时改为 true
hub_url: "http://192.168.2.85:8098"
store_id: "store_yuhuan"
zone: "备餐废弃区"
```

**职责**:
- RTSP 拉流 → 每 N 秒抽帧 → 保存 `/tmp/ipc_frames/latest.jpg`
- 支持 `auto_infer` 开关控制是否触发后续推理

**依赖**: `python3-opencv` (cv2), `pyyaml`

**状态**: ✅ 常驻运行

---

### 2.2 yolo26_infer — 一级目标检测

**文件**: `/root/yolo26_infer.py`  
**模型**: `/root/models/yolo26l.onnx` → TensorRT `yolo26l.engine`  
**运行方式**: 在 Docker 容器内或宿主机直接运行 (需 TensorRT Python binding)

```bash
# 推理命令（示例）
python3 /root/yolo26_infer.py --image /tmp/ipc_frames/latest.jpg --output /tmp/yolo_result.json
```

**职责**:
- YOLO 快速扫描整帧，检测预设类别目标（食材、餐具、人员区域）
- 输出 JSON：`[{x1,y1,x2,y2,conf,cls}, ...]`
- 根据检测结果决定是否触发二级

**延迟**: ~8ms (TensorRT FP16)

**状态**: ⬜ 脚本完好，但 Docker yolo-jetson 镜像已清理，需重建

**重建步骤**:
```bash
# Jetson 上
cd /root/yolo-jetson
docker build -t yolo-jetson-infer:local .
```

---

### 2.3 CLIP-Adapter — 二级少样本分类

**文件**: 需从 Mac 部署 to Jetson  
**适配器权重**: `adapter_weights.pt` (514KB)  
**运行方式**: Docker `nvcr.io/nvidia/l4t-pytorch:r34.1.1-pth1.12-py3` (需重新 pull)

```bash
# 推理命令（示例）
docker run --rm --runtime=nvidia \
  -v /tmp:/tmp \
  -v /root/models:/models \
  nvcr.io/nvidia/l4t-pytorch:r34.1.1-pth1.12-py3 \
  python3 /tmp/clip_adapter_infer.py \
    --image /tmp/ipc_frames/roi.jpg \
    --adapter /models/adapter_weights.pt \
    --classes "毛肚,鹅肠,废料"
```

**实测基准 (2026-07-04)**:
| 指标 | 结果 |
|:--|:--|
| GPU | Orin, 32GB |
| 推理延迟 | **15.1ms** |
| FPS | **66.0** |
| 1-Shot 微调 | ~2s |
| 模型参数 | 87.8M (ViT-B/32) |
| 适配器大小 | 514KB |

**Mac 验证结果** (1-Shot, 火锅后厨数据):

| 图像 | 零样本 | 1-Shot | 正确标签 |
|:--|:--|:--|:--|
| 油污手套 | ✓ | ✓ | waste |
| 火锅废料 | ✓ | ✓ | food_waste |
| 新鲜毛肚 | ✗ (误判 waste) | ✓ | food |

准确率：零样本 33.3% (1/3) → **1-Shot 66.7% (2/3)**，微调仅 1.2s。

**状态**: ⬜ Docker l4t-pytorch 镜像已清理，需重新 pull；适配器权重需部署

**重建步骤**:
```bash
# 1. 重新 pull 镜像
docker pull nvcr.io/nvidia/l4t-pytorch:r34.1.1-pth1.12-py3

# 2. 从 Mac 部署适配器权重和推理脚本
scp ~/company/hotpot_smart_ops/clip-adapter/adapter_weights.pt \
    root@192.168.2.240:/root/models/
scp ~/company/hotpot_smart_ops/clip-adapter/infer.py \
    root@192.168.2.240:/tmp/clip_adapter_infer.py
```

---

### 2.4 Ostrakon-VL — 三级 VLM 分析

**文件**: `/root/run_ostrakon_vl.sh` (已删，需重写)  
**模型**: `/root/models/ostrakon-vl-8b/Ostrakon-VL-8B.IQ4_XS.gguf` (5.0G)  
**Projector**: `Ostrakon-VL-8B.mmproj-Q8_0.gguf`  
**运行方式**: llama.cpp 本地 CPU 推理

```bash
# 推理命令（示例）
~/llama.cpp/build/bin/llama-llava-cli \
  -m /root/models/ostrakon-vl-8b/Ostrakon-VL-8B.IQ4_XS.gguf \
  --mmproj /root/models/ostrakon-vl-8b/Ostrakon-VL-8B.mmproj-Q8_0.gguf \
  --image /tmp/ipc_frames/low_conf.jpg \
  -p "你是后厨废弃物识别系统。分析图片..." \
  --temp 0.1 -n 512
```

**Prompt 协定** (来自 `jetson-vlm-bridge-v1.md`):
```
你是后厨废弃物识别系统。分析图片中的废弃食材/餐余，输出严格 JSON（不含 markdown）：
{"items":[{"waste_type":"备餐废弃|边角料|过期临界|餐后剩余","sku":"食材名","estimated_portion":0.8,"unit":"份","confidence":0.82,"reason":"判断依据","suggested_action":"建议操作"}]}
只输出 JSON，不要额外文字。
```

**Hub 接口**: `POST /v1/vlm/waste-estimate` (已签约，见 `jetson-vlm-bridge-v1.md`)

**状态**: ⬜ 推理脚本 + llama.cpp 需重建

**重建步骤**:
```bash
# 1. 重编 llama.cpp（如果二进制也清了）
cd /root
git clone https://github.com/ggerganov/llama.cpp.git
cd llama.cpp
cmake -B build
cmake --build build -j4 --target llama-llava-cli

# 2. 重写推理包装脚本 run_ostrakon_vl.sh
```

---

## 3. 分阶段实施

### Phase 0 — 环境恢复（当前）

| 任务 | 命令 | 状态 |
|:--|:--|:--|
| Docker 镜像 pull | `docker pull nvcr.io/nvidia/l4t-pytorch:r34.1.1-pth1.12-py3` | ⬜ |
| 重编 yolo-jetson 镜像 | `cd /root/yolo-jetson && docker build` | ⬜ |
| 重编 llama.cpp | `git clone && cmake --build` | ⬜ |
| 部署 clip_adapter_infer.py | scp from Mac | ⬜ |
| 写推理调度主脚本 | 见 Phase 1 | ⬜ |

### Phase 1 — 单模块验证

| 模块 | 验证目标 | 验收标准 |
|:--|:--|:--|
| YOLO | TensorRT 推理 restore | 推理 <10ms，输出 JSON 正确 |
| CLIP-Adapter | GPU 推理 restore | 推理 <20ms，1-Shot acc ≥ 60% |
| Ostrakon-VL | CPU 推理 restore | 推理 <500ms，输出 JSON 合法 |

### Phase 2 — 模块串联

| 任务 | 内容 |
|:--|:--|
| 调度主脚本 | `inference_pipeline.py` 串联三级 |
| IPC grabber 集成 | `auto_infer: true` 触发 pipeline |
| Hub 对接 | POST `/v1/vlm/waste-estimate` |

### Phase 3 — 生产化

| 任务 | 内容 |
|:--|:--|
| systemd 常驻 | pipeline 作为 systemd 服务 |
| 监控 | 延迟 / 准确率 / 丢帧 指标 |
| 降级 | YOLO → CLIP → VLM 逐级降级策略 |

---

## 4. 接口契约

### 模块间数据格式

**YOLO 输出 → CLIP 输入**:
```json
{
  "detections": [
    {"x1": 100, "y1": 50, "x2": 300, "y2": 250, "conf": 0.92, "cls": "food_zone"},
    {"x1": 400, "y1": 60, "x2": 600, "y2": 240, "conf": 0.85, "cls": "waste_zone"}
  ],
  "ts": "2026-07-04T12:00:00Z",
  "frame": "/tmp/ipc_frames/latest.jpg"
}
```

**CLIP 输出 → VLM 输入 (低置信度时)**:
```json
{
  "low_conf_rois": [
    {"roi_path": "/tmp/roi_0.jpg", "yolo_conf": 0.92, "clip_conf": 0.45, "top_pred": "unknown"}
  ]
}
```

**VLM 输出 → Hub**:
```json
{
  "store_id": "store_yuhuan",
  "items": [
    {"waste_type": "备餐废弃", "sku": "毛肚", "estimated_portion": 0.8, "confidence": 0.82, "reason": "边角料切剩"},
    {"waste_type": "餐后剩余", "sku": "蔬菜拼盘", "estimated_portion": 0.5, "confidence": 0.75, "reason": "剩半份未动"}
  ],
  "source": "vlm-shadow",
  "model": "ostrakon-vl-8b-iq4xs",
  "zone": "备餐废弃区",
  "ts": "2026-07-04T12:00:00Z"
}
```

### 降级矩阵

| 场景 | YOLO | CLIP-Adapter | VLM | 行为 |
|:--|:--|:--|:--|:--|
| 正常 | ✓ | ✓ | ✓(低置信度) | 完整流水线 |
| YOLO 故障 | ✗ | ✗ | ✗ | 跳过推理，记录错误 |
| CLIP 故障 | ✓ | ✗ | ✓(所有 ROI) | 跳过二级，直接 VLM |
| VLM 故障 | ✓ | ✓ | ✗ | 仅 YOLO + CLIP，标记 `vlm_unavailable` |
| Docker 全挂 | ✗ | ✗ | ✗ | 仅 IPC 抽帧，等待恢复 |

---

## 5. 与产品方案的对应关系

| 本文 | 产品文档 |
|:--|:--|
| 一级 YOLO | ADR-005 (边缘推理 yolo-first) |
| 二级 CLIP-Adapter | **新增**，补充 YOLO 在少样本缺陷/特定食材上的不足 |
| 三级 Ostrakon-VL | ADR-014 (YOLO+VLM 三级过滤), ADR-020 (VLM 视觉损耗) |
| IPC 抓帧 | ADR-019 (真实设备接入) |
| Hub 对接 | `jetson-vlm-bridge-v1.md` (已签约接口) |
| 硬件规格 | ADR-017 (Jetson 开发机, 67 TOPS) |

---

## 6. 当前阻塞

| 阻塞 | 解决方案 | 优先级 |
|:--|:--|:--|
| Docker l4t-pytorch 镜像 | `docker pull` — 需 Jetson 网络稳定 | P0 |
| yolo-jetson Docker 镜像 | `docker build` — 代码在 `/root/yolo-jetson` | P0 |
| llama.cpp 二进制 | 重编 或 scp 预编译包 | P0 |
| CLIP-Adapter 推理脚本 | 从 Mac 写并 scp | P1 |
| 调度主脚本 `inference_pipeline.py` | 待 Phase 2 实现 | P1 |
| 网络 (docker pull/git clone) | Jetson 网络间歇不稳定 | P0 |

---

## 7. 参考资料

- [ADR-005](architecture_decisions.md#adr-005) — 边缘推理 yolo-first
- [ADR-014](architecture_decisions.md#adr-014) — YOLO+VLM 三级过滤
- [ADR-017](architecture_decisions.md#adr-017) — 硬件分期 Profile
- [ADR-020](architecture_decisions.md#adr-020) — VLM 视觉损耗经营
- [Jetson VLM Bridge 协定](api-contracts/jetson-vlm-bridge-v1.md) — Hub 接口
- [CLIP-Adapter GPU 实测](https://mp.weixin.qq.com/s/3ObvNJrYmWrXLRexOYnIMA) — 论文 & 参考
