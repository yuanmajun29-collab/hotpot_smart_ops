# ===== 边缘 agent 统一推理服务 =====
# 合并原 kitchen + front-hall 为单入口，端口 9100
# 基础镜像：l4t-pytorch（Jetson GPU，预装 CUDA/PyTorch）
# 部署：docker build -t hotpot-edge-agent . && docker run --runtime=nvidia -p 9100:9100 hotpot-edge-agent

FROM nvcr.io/nvidia/l4t-pytorch:r36.4.0-pth2.5-py3

WORKDIR /app

# ─── Python 依赖 ───
RUN pip install --no-cache-dir \
    fastapi uvicorn[standard] \
    opencv-python-headless \
    httpx \
    pyyaml \
    ultralytics

# ─── 应用代码 ───
COPY edge/agent/server.py ./
COPY edge/agent/config.py ./
COPY edge/agent/modules/ ./modules/
COPY edge/shared/detector/ ./detector/

# ─── 模型卷挂载点（运行时注入） ───
RUN mkdir -p /opt/hotpot-infer/bin /opt/hotpot-infer/models /opt/hotpot-infer/config

# ─── 健康检查 ───
HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
    CMD curl -f http://localhost:9100/health || exit 1

EXPOSE 9100

# 入口：python3 server.py（依赖 edge/ 包路径，需在项目根目录运行或设 PYTHONPATH）
ENV PYTHONPATH=/app:$PYTHONPATH

CMD ["python3", "server.py"]
