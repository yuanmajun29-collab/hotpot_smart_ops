# ===== 边缘推理服务 Dockerfile =====
# 构建:
#   docker build -f deploy/jetson/Dockerfile -t hotpot-kitchen .
#
# 模型通过卷挂载: /opt/hotpot-infer/models → /models
# 数据持久化: /opt/hotpot-infer/data → /data
# IPC 帧: /tmp/ipc_frames

# ── Stage 1: 编译 llama.cpp ──
FROM nvcr.io/nvidia/l4t-cuda:12.2.0-runtime-ubuntu22.04 AS llama-builder

RUN apt-get update && apt-get install -y --no-install-recommends \
    git build-essential cmake ccache \
    && rm -rf /var/lib/apt/lists/*

RUN git clone --depth=1 https://github.com/ggerganov/llama.cpp.git /tmp/llama.cpp && \
    cd /tmp/llama.cpp && \
    mkdir build_cuda && cd build_cuda && \
    cmake .. \
      -DGGML_CUDA=ON \
      -DCMAKE_CUDA_ARCHITECTURES="87" \
      -DGGML_CUDA_FORCE_MMQ=ON \
      -DCMAKE_BUILD_TYPE=Release && \
    make -j4 llama-server && \
    cp bin/llama-server /opt/llama-server-cuda && \
    cp bin/*.so /opt/ 2>/dev/null || true && \
    rm -rf /tmp/llama.cpp/build_cuda

# ── Stage 2: 运行时镜像 ──
FROM nvcr.io/nvidia/l4t-pytorch:r35.4.1-pth2.0-py3

ENV DEBIAN_FRONTEND=noninteractive \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONUNBUFFERED=1

WORKDIR /workspace

RUN apt-get update && apt-get install -y --no-install-recommends \
    libglib2.0-0 curl net-tools \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir \
    fastapi uvicorn[standard] httpx pyyaml \
    opencv-python-headless

# 从 Stage 1 复制编译好的 llama-server + 共享库
COPY --from=llama-builder /opt/llama-server-cuda /opt/hotpot-infer/bin/llama-server-cuda
COPY --from=llama-builder /opt/*.so /opt/hotpot-infer/bin/

# 入口脚本
COPY deploy/jetson/entrypoint.sh /opt/hotpot-infer/bin/entrypoint.sh
RUN chmod +x /opt/hotpot-infer/bin/entrypoint.sh

# 项目源码
COPY edge/ /workspace/edge/
COPY common/ /workspace/common/
COPY hotpot_platform/ /workspace/hotpot_platform/

RUN mkdir -p /models /data /opt/hotpot-infer/bin

ENV PYTHONPATH=/workspace \
    MODEL_DIR=/opt/hotpot-infer/models

HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
    CMD curl -f http://localhost:9100/health || exit 1

EXPOSE 9100 8080

ENTRYPOINT ["/opt/hotpot-infer/bin/entrypoint.sh"]
