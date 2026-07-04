# Jetson Inference Pipeline · Deploy

> 火锅后厨 AI 推理流水线 · Jetson Orin 部署工程

## 架构

```
摄像头(RTSP) → ipc_frame_grabber → YOLO(TensorRT,8ms) → CLIP-Adapter(CUDA,15ms) → Ostrakon-VL(CPU,300ms) → Hub
                                       一级检测              二级分类                 三级语义
```

## 目录结构

```
/opt/hotpot-infer/            # Jetson 目标路径
├── pipeline/
│   ├── ipc_frame_grabber.py  # RTSP 抽帧 (systemd 常驻)
│   ├── yolo_infer.py         # YOLO TensorRT 推理
│   ├── clip_infer.py         # CLIP-Adapter 推理 (Docker)
│   ├── vlm_infer.py          # Ostrakon-VL 推理
│   └── inference_pipeline.py # 调度主脚本
├── config/
│   ├── ipc_config.yml        # 摄像头配置
│   └── pipeline_config.yml   # 流水线配置
├── models/
│   ├── yolo26l.onnx / .pt    # YOLO 模型
│   ├── adapter_weights.pt    # CLIP 适配器 (514KB)
│   └── ostrakon-vl-8b/       # VLM 模型 (5G)
├── docker/yolo-jetson/       # YOLO Docker 构建
└── systemd/
    ├── ipc-grabber.service
    └── hotpot-pipeline.service
```

## 快速部署

```bash
# 1. 部署代码到 Jetson
bash deploy.sh [jetson_ip]

# 2. 部署模型（首次）
scp models/adapter_weights.pt root@192.168.2.240:/opt/hotpot-infer/models/
scp models/yolo26l.* root@192.168.2.240:/opt/hotpot-infer/models/

# 3. 重建 Docker（首次或 Docker 更新后）
bash deploy.sh 192.168.2.240 --rebuild

# 4. 测试单帧推理
ssh root@192.168.2.240 'python3 /opt/hotpot-infer/pipeline/inference_pipeline.py --frame /tmp/ipc_frames/latest.jpg'
```

## 服务管理

```bash
# 查看状态
ssh root@192.168.2.240 'systemctl status ipc-grabber'

# 重启
ssh root@192.168.2.240 'systemctl restart ipc-grabber'

# 查看日志
ssh root@192.168.2.240 'tail -f /var/log/ipc-grabber.log'
```

## 基准数据

| 阶段 | 延迟 | 引擎 | 备注 |
|:--|:--|:--|:--|
| YOLO | ~8ms | TensorRT FP16 | 一级全帧检测 |
| CLIP-Adapter | ~15ms | PyTorch CUDA | 66 FPS, Orin 32GB |
| VLM | ~300ms | llama.cpp CPU | Ostrakon-VL-8B IQ4_XS |
| 总流水线 | <400ms | - | 正常情况(无VLM触发时<30ms) |

## 相关文档

- [流水线实施计划](../docs/jetson_inference_pipeline_plan.md)
- [VLM Bridge 接口协定](../docs/api-contracts/jetson-vlm-bridge-v1.md)
- [项目 ADR](../docs/architecture_decisions.md)
