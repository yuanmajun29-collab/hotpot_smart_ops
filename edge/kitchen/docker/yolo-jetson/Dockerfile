# YOLO 推理 / 模型验证（Jetson Orin，L4T R34.1.x / JetPack 5.0.1 DP）
# 基础镜像与主机 JetPack 对齐，避免 CUDA/cuDNN 版本错配。
# 参考：https://catalog.ngc.nvidia.com/orgs/nvidia/containers/l4t-pytorch
#
# 与主机不一致时可在构建时覆盖，例如：
#   docker build --build-arg L4T_PYTORCH_IMAGE=nvcr.io/nvidia/l4t-pytorch:r35.x.x-pth2.x-py3 -t yolo-jetson-infer:local .
ARG L4T_PYTORCH_IMAGE=nvcr.io/nvidia/l4t-pytorch:r34.1.1-pth1.12-py3
FROM ${L4T_PYTORCH_IMAGE}

ENV DEBIAN_FRONTEND=noninteractive \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# 使用镜像内已预装的 PyTorch，仅补充推理常用依赖
# 移除镜像预装的 cv2 目录（无 .dist-info，但与 pip 版混用会触发 gapi/GStreamer 循环导入），
# 先单独安装 headless，再对 ultralytics 使用 --no-deps 避免再次拉取 opencv-python。
RUN rm -rf /usr/local/lib/python3.8/dist-packages/cv2 \
    && python3 -m pip install --no-cache-dir --upgrade pip setuptools wheel \
    && python3 -m pip install --no-cache-dir "opencv-python-headless==4.8.1.78" \
    && python3 -c "import cv2; print('cv2', cv2.__version__)" \
    && python3 -m pip install --no-cache-dir "ultralytics>=8.0.0" --no-deps \
    && python3 -m pip install --no-cache-dir \
        matplotlib "pillow>=10.4.0" "numpy>=1.23.0,<2" scipy psutil polars ultralytics-thop \
        pyyaml tqdm requests importlib-resources \
    && python3 -c "import torch, cv2, ultralytics; print('torch', torch.__version__, 'cuda', torch.cuda.is_available()); print('cv2', cv2.__version__, 'ultralytics', ultralytics.__version__)"

WORKDIR /workspace

# 镜像单独运行时的默认入口；compose 会覆盖 command
CMD ["/bin/bash"]
