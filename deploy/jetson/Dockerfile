# ===== 后厨边缘推理服务 =====
# 构建：docker build -f deploy/jetson/Dockerfile -t hotpot-kitchen .
# 运行：cd deploy/jetson && docker compose up -d
#
# 模型通过卷挂载（不进镜像）：/opt/hotpot-infer/models → /models
# llama-server 通过卷挂载（不进镜像）：/opt/hotpot-infer/bin → /opt/hotpot-infer/bin

FROM nvcr.io/nvidia/l4t-pytorch:r35.4.1-pth2.0-py3

ENV DEBIAN_FRONTEND=noninteractive \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONUNBUFFERED=1

WORKDIR /workspace

# 基础依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    libglib2.0-0 curl \
    && rm -rf /var/lib/apt/lists/*

# Python 依赖
RUN pip install --no-cache-dir \
    fastapi uvicorn[standard] \
    opencv-python-headless \
    httpx pyyaml \
    ultralytics

# 创建挂载点
RUN mkdir -p /models /data /opt/hotpot-infer/bin

HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
    CMD curl -f http://localhost:9200/health || exit 1

EXPOSE 9200

# 不 CMD — 由 deploy.sh 通过 docker exec 启动服务
CMD ["sleep", "infinity"]
