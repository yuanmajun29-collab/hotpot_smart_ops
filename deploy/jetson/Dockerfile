# ===== 后厨边缘推理服务 =====
# 功能：YOLO检测 → CLIP场景分类 → VLM废料识别 三级推理
# 部署：docker compose up -d kitchen
# 基础镜像：l4t-pytorch（Jetson GPU，已预装 CUDA/PyTorch）

FROM nvcr.io/nvidia/l4t-pytorch:r34.1.1-pth1.12-py3

WORKDIR /app

# Python 依赖
RUN pip install --no-cache-dir \
    fastapi uvicorn[standard] \
    opencv-python-headless \
    httpx \
    pyyaml

# 复制后厨代码
COPY server.py ./
COPY pipeline/ ./pipeline/
COPY bridge_waste_vision.py bridge_waste_vision.sh ./
COPY kitchen_compliance.onnx ./models/

# 共用模块（从 shared/ 注入）
COPY detector/ ./detector/

# 模型卷挂载点（运行时注入）
RUN mkdir -p /models/ostrakon-vl-8b

# 健康检查
HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
    CMD curl -f http://localhost:9200/health || exit 1

EXPOSE 9200

CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "9200"]
