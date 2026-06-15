Hotpot Edge RKNN Deployment Guide
===================================

ONNX model: /home/liuwz/Detect_Inference_Project/MODEL/detect.onnx
Target SoC: rk3566

Steps (on development machine with rknn-toolkit2):
1. cd /home/liuwz/Detect_Inference_Project
2. Convert ONNX to RKNN using project scripts (see DETECT_rknn.py / DETECT_rknn3566.py)
3. Copy .rknn file to edge device: /home/liuwz/hotpot_smart_ops/edge/rknn_deploy/output/

Steps (on RK3566/RK3588 edge device):
1. Install rknn-lite / rknpu runtime
2. python /home/liuwz/Detect_Inference_Project/DETECT_rknn3566.py --model /home/liuwz/hotpot_smart_ops/edge/rknn_deploy/output/hotpot_detect.rknn
3. Integrate with hotpot_detector.py via --backend onnx (future) or sidecar HTTP

PoC note: mock backend runs without RKNN hardware for demo.
