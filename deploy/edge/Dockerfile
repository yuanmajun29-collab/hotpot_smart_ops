# ===== 边缘盒子统一容器 =====
# 一个容器跑全部：agent server + 前厅推理 + 后厨推理 + IPC 抓帧
# 部署：docker compose up -d

FROM nvcr.io/nvidia/l4t-pytorch:r36.4.0-pth2.5-py3

WORKDIR /app

# ─── Python 依赖 ───
RUN pip install --no-cache-dir \
    fastapi uvicorn[standard] \
    opencv-python-headless \
    httpx pyyaml \
    ultralytics

# ─── 全部应用代码 ───
COPY edge/ ./

# ─── 启动脚本（按需切模式） ───
COPY deploy/edge/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# ─── 模型 / 数据挂载点 ───
RUN mkdir -p /opt/hotpot-infer/bin /opt/hotpot-infer/models /opt/hotpot-infer/data

HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
    CMD curl -f http://localhost:9100/health || exit 1

EXPOSE 9100

ENV PYTHONPATH=/app:$PYTHONPATH

ENTRYPOINT ["/entrypoint.sh"]
