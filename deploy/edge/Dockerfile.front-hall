# ===== 前厅边缘推理服务 =====
# 功能：桌台状态识别、客流统计、前厅监控摄像头推理
# 部署：docker compose up -d front-hall
# 基础镜像：l4t-pytorch（Jetson GPU）

FROM nvcr.io/nvidia/l4t-pytorch:r34.1.1-pth1.12-py3

WORKDIR /app

RUN pip install --no-cache-dir \
    fastapi uvicorn[standard] \
    opencv-python-headless \
    onnxruntime-gpu \
    paho-mqtt \
    httpx \
    pyyaml

# 前厅代码
COPY server.py store_forward.py ./
COPY table_state.onnx ./models/
COPY stream/ ./stream/
COPY iot_mock/ ./iot_mock/

# 共用检测器（从 shared/ 注入，含 YOLO ONNX backend）
COPY detector/ ./detector/

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD curl -f http://localhost:9100/health || exit 1

EXPOSE 9100

CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "9100"]
