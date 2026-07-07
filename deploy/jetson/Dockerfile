# ===== 后厨边缘推理服务（含 llama.cpp 编译）=====
# 构建（源码端 Mac）：
#   docker build -f deploy/jetson/Dockerfile -t hotpot-kitchen .
# 产出完整镜像（含 llama-server 二进制 + Python 代码），推板端即可用。
#
# 模型通过卷挂载（不进镜像）：/opt/hotpot-infer/models → /models

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
    libglib2.0-0 curl \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir \
    fastapi uvicorn[standard] \
    opencv-python-headless \
    httpx pyyaml \
    ultralytics

# 从 Stage 1 复制编译好的 llama-server
COPY --from=llama-builder /opt/llama-server-cuda /opt/hotpot-infer/bin/llama-server-cuda
# COPY --from=llama-builder /opt/*.so /opt/hotpot-infer/bin/

RUN mkdir -p /models /data /opt/hotpot-infer/bin

HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
    CMD curl -f http://localhost:9200/health || exit 1

EXPOSE 9200
CMD ["sleep", "infinity"]
