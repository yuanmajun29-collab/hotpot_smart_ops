# GitHub 精华项目吸收 — 火锅AI产品完善

> 日期: 2026-07-15
> 目的: 从GitHub高星项目中提取可借鉴的架构/模式/工具，完善火锅AI系统

---

## 一、高价值项目矩阵

| 项目 | 星数 | 领域 | 借鉴价值 | 优先级 |
|------|------|------|---------|--------|
| [roboflow/supervision](https://github.com/roboflow/supervision) | ⭐48K | CV工具链 | 标注/可视化/后处理 | ⭐⭐⭐ |
| [open-edge-platform/anomalib](https://github.com/open-edge-platform/anomalib) | ⭐5.9K | 异常检测 | 边缘部署/TensorRT导出 | ⭐⭐⭐ |
| [obss/sahi](https://github.com/obss/sahi) | ⭐5.4K | 切片推理 | 大图小目标（后厨全景） | ⭐⭐⭐ |
| [dusty-nv/jetson-inference](https://github.com/dusty-nv/jetson-inference) | ⭐8.9K | Jetson部署 | TensorRT优化/多模型 | ⭐⭐⭐ |
| [tryolabs/norfair](https://github.com/tryolabs/norfair) | ⭐2.6K | 目标追踪 | 多目标持续追踪 | ⭐⭐ |
| [ultralytics/ultralytics](https://github.com/ultralytics/ultralytics) | ⭐59K | YOLO | 已在用（YOLO26） | ✅ |
| [open-mmlab/mmdetection](https://github.com/open-mmlab/mmdetection) | ⭐32K | 检测框架 | 多模型对比实验 | ⭐ |

---

## 二、逐项分析 & 吸收建议

### 2.1 Supervision ⭐48K — 标注→可视化完整管线

**项目核心**:
```
标注工具 → 数据集管理 → 模型训练 → 推理后处理 → 可视化
```

**我们可借鉴**:

| Supervision功能 | 火锅系统的映射 | 增益 |
|----------------|--------------|------|
| `sv.Detections` 统一数据格式 | 统一 YOLO/VLM/Count 输出 | 减少胶水代码 |
| `sv.ByteTrack` 目标追踪 | 后厨人员/餐具跨帧追踪 | 防重复计数 |
| `sv.Annotator` 可视化 | Dashboard实时标注叠加 | 提升演示效果 |
| `sv.VideoSink` 视频输出 | 事件录像自动保存 | 审计回溯 |
| `sv.Classificatio`n 数据集管理 | 火锅废料/餐具分类标注 | 规范化标注流程 |

**吸收方案**: 在 `hotpot_yolo_detect.py` 中引入 Supervision 做检测结果后处理（NMS/追踪/可视化），替代当前手写逻辑。

### 2.2 Anomalib ⭐5.9K — 工业异常检测平台

**项目核心**:
```
数据加载 → 模型训练 → 超参优化 → 边缘导出(TensorRT/ONNX) → 部署
```

**我们可借鉴**:

| Anomalib功能 | 火锅系统的映射 | 增益 |
|-------------|--------------|------|
| 模型导出到TensorRT/ONNX | YOLO模型Jetson优化 | 提升推理速度30-50% |
| 实验管理(YAML配置) | 多店模型版本管理 | 可追溯 |
| 门控逻辑(threshold tuning) | 告警阈值自动调优 | 减少误报 |
| 推理Pipeline模式 | 检测→追踪→计数流水线 | 架构参考 |

**吸收方案**: 参考 Anomalib 的 `export` 模块，为我们的YOLO模型添加 TensorRT FP16 导出路径（对标 `dusty-nv/jetson-inference`）。

### 2.3 SAHI ⭐5.4K — 大图切片推理

**项目核心**: 将高分辨率图像切为小片独立推理，再拼接结果。

**我们可借鉴**:

| SAHI功能 | 火锅系统的映射 | 增益 |
|---------|--------------|------|
| 切片推理(tiled inference) | 后厨全景摄像头（4K） | 小废料不遗漏 |
| 重叠区域去重 | 切片边界合并 | 避免重复计数 |
| 多模型组合 | YOLO(快)+VLM(深)分层推理 | 速度+精度平衡 |

**吸收方案**: 这正是今天学的"SAM农田地块提取"中提到的**切断田问题**解法。后厨4K摄像头直接推理→小废料漏检，用SAHI切片+重叠+拼接方案。

### 2.4 jetson-inference ⭐8.9K — Jetson部署最佳实践

**项目核心**: TensorRT优化的DNN推理 + C++/Python双接口 + 预训练模型库。

**我们可借鉴**:

| 功能 | 火锅系统应用 |
|------|------------|
| `detectNet` TensorRT推理 | YOLO→TensorRT加速 |
| `videoSource/videoOutput` | RTSP摄像头接入+录像输出 |
| 多模型并发 | YOLO+VLM+Count三模型调度 |
| Docker容器化 | 一键部署脚本 |

**吸收方案**: 
1. 用 TensorRT 替代当前 CPU PyTorch 推理 → 后厨实时性从15fps→30fps+
2. 参考其 Dockerfile 设计我们的 L4T 容器

### 2.5 Norfair ⭐2.6K — 轻量级多目标追踪

**项目核心**: 在任何检测器上加追踪，纯Python，100行代码即可。

**我们可借鉴**:

| 功能 | 火锅系统应用 |
|------|------------|
| 跨帧目标ID关联 | 追踪同一废料从出现到撤走 |
| 轨迹分析 | 餐具/托盘流转路径分析 |
| 驻留时间统计 | 空盘停留超时告警 |

**吸收方案**: 给YOLO检测结果加Norfair追踪→每个废料有唯一ID→精确统计数量和生命周期。

---

## 三、火锅后厨专属：开源沙漠

### GitHub直接搜索结论

- **火锅/后厨/厨房AI**: 11个微型项目（0-9星），均为学生课程项目
- **食品废料检测**: 2个项目（5-21星），场景不匹配
- **餐厅SOP监控**: 0个项目
- **后厨AI+边缘**: 0个项目

→ **火锅后厨AI是开源沙漠，我们自建具有先发优势。**

### 间接可借鉴的工业项目

| 领域 | 代表项目 | 借鉴方向 |
|------|---------|---------|
| 工业缺陷检测 | anomalib | 边缘部署流程 |
| 智慧零售 | 多家CV公司闭源方案 | 客流动线→后厨动线 |
| 安防监控 | DeepStream | 多路视频处理 |
| 垃圾分类 | TrashNet等 | 废料分类 |

---

## 四、吸收行动计划

| 优先级 | 行动 | 来源 | 预期效果 | 工时 |
|--------|------|------|---------|------|
| P0 | Supervision集成（可视化+追踪） | roboflow/supervision | 减少胶水代码，提升演示效果 | 1天 |
| P0 | TensorRT导出管道 | anomalib + jetson-inference | 推理速度×2 | 2天 |
| P1 | SAHI切片推理 | obss/sahi | 4K摄像头小目标不遗漏 | 1天 |
| P1 | Norfair追踪 | tryolabs/norfair | 废料生命周期分析 | 0.5天 |
| P2 | Anomalib实验管理 | anomalib | 多店模型版本管理 | 1天 |

---

## 五、我们的独特壁垒

GitHub上没有的东西（我们的护城河）:
1. **火锅SOP状态机** — 7工位全链路，闭源Knowhow
2. **蒸汽/加汤/蘸料专用检测** — 场景定制化
3. **YOLO+VLM+Count三模型协同** — 架构创新
4. **Hub Dashboard** — 从数据到决策的闭环
5. **冯校长真实数据** — 训练飞轮

---

*关联文档: [开发方案](./火锅AI-开发方案.md) | [市场调研](./火锅AI-市场调研.md)*
