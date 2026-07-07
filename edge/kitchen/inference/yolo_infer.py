#!/usr/bin/env python3
"""yolo26_infer.py — TensorRT YOLO26_L inference on Jetson Orin.

推理规则（阈值）→ rules.py
推理内容（TRT 引擎/后处理/分类器）→ 本文件

Converts ONNX → TensorRT engine on first run, caches .engine file.
Outputs bounding boxes in YOLO format: [x1,y1,x2,y2,conf,cls]
"""

import os
import sys
import time
import json
import numpy as np
from pathlib import Path

from .rules import YOLO_CONF_THRESH, YOLO_IOU_THRESH

MODEL_DIR = os.environ.get("MODEL_DIR", "/root/models")
ONNX_PATH = os.path.join(MODEL_DIR, "yolo26l.onnx")
ENGINE_PATH = os.path.join(MODEL_DIR, "yolo26l.engine")

# ── TensorRT setup ──────────────────────────────────────────────────
import tensorrt as trt

TRT_LOGGER = trt.Logger(trt.Logger.WARNING)

def build_engine(onnx_path, engine_path, fp16=True):
    """Build TensorRT engine from ONNX, cache to disk."""
    builder = trt.Builder(TRT_LOGGER)
    network = builder.create_network(1 << int(trt.NetworkDefinitionCreationFlag.EXPLICIT_BATCH))
    parser = trt.OnnxParser(network, TRT_LOGGER)

    with open(onnx_path, "rb") as f:
        if not parser.parse(f.read()):
            for i in range(parser.num_errors):
                print(f"  ONNX parse error: {parser.get_error(i)}")
            raise RuntimeError("ONNX parsing failed")

    config = builder.create_builder_config()
    config.set_memory_pool_limit(trt.MemoryPoolType.WORKSPACE, 2 << 30)  # 2GB

    if fp16:
        config.set_flag(trt.BuilderFlag.FP16)

    profile = builder.create_optimization_profile()
    profile.set_shape("images", (1, 3, 640, 640), (1, 3, 640, 640), (4, 3, 640, 640))
    config.add_optimization_profile(profile)

    print(f"[engine] Building TensorRT engine (fp16={fp16})...")
    t0 = time.time()
    engine = builder.build_serialized_network(network, config)
    if engine is None:
        raise RuntimeError("Engine build failed")

    with open(engine_path, "wb") as f:
        f.write(engine)
    print(f"[engine] Built in {time.time()-t0:.1f}s, saved to {engine_path}")
    return engine


def load_engine(engine_path):
    """Load cached or build new engine."""
    if os.path.exists(engine_path):
        print(f"[engine] Loading cached engine: {engine_path}")
        with open(engine_path, "rb") as f:
            return f.read()
    return build_engine(ONNX_PATH, engine_path)


# ── YOLO post-processing ────────────────────────────────────────────
def nms(boxes, scores, iou_thresh=YOLO_IOU_THRESH):
    """Simple NMS."""
    if len(boxes) == 0:
        return []
    x1 = boxes[:, 0]; y1 = boxes[:, 1]; x2 = boxes[:, 2]; y2 = boxes[:, 3]
    areas = (x2 - x1) * (y2 - y1)
    order = scores.argsort()[::-1]
    keep = []
    while order.size > 0:
        i = order[0]; keep.append(i)
        if order.size == 1:
            break
        xx1 = np.maximum(x1[i], x1[order[1:]])
        yy1 = np.maximum(y1[i], y1[order[1:]])
        xx2 = np.minimum(x2[i], x2[order[1:]])
        yy2 = np.minimum(y2[i], y2[order[1:]])
        w = np.maximum(0, xx2 - xx1)
        h = np.maximum(0, yy2 - yy1)
        inter = w * h
        iou = inter / (areas[i] + areas[order[1:]] - inter + 1e-6)
        order = order[1:][iou < iou_thresh]
    return keep


def postprocess(output, img_w, img_h, conf_thresh=YOLO_CONF_THRESH, iou_thresh=YOLO_IOU_THRESH):
    """Parse YOLO output → list of [x1,y1,x2,y2,conf,cls]."""
    # output shape: (1, 84, 8400) for COCO 80-class
    output = output[0]  # [84, 8400]
    boxes = []
    for i in range(output.shape[1]):
        row = output[:, i]
        conf = row[4:].max()
        if conf < conf_thresh:
            continue
        cls = int(row[4:].argmax())
        cx, cy, w, h = row[:4]
        # scale to image coordinates
        cx = cx / 640 * img_w
        cy = cy / 640 * img_h
        w = w / 640 * img_w
        h = h / 640 * img_h
        x1 = cx - w / 2
        y1 = cy - h / 2
        x2 = cx + w / 2
        y2 = cy + h / 2
        boxes.append([x1, y1, x2, y2, float(conf), cls])

    if not boxes:
        return []
    boxes = np.array(boxes)
    # NMS per class
    keep_idx = []
    for cls in np.unique(boxes[:, 5]):
        cls_mask = boxes[:, 5] == cls
        cls_boxes = boxes[cls_mask]
        cls_scores = cls_boxes[:, 4]
        keep = nms(cls_boxes[:, :4], cls_scores, iou_thresh)
        keep_idx.extend(np.where(cls_mask)[0][keep])
    return boxes[keep_idx].tolist()


# ── Inference ───────────────────────────────────────────────────────
class YOLO26:
    def __init__(self, engine_path=ENGINE_PATH):
        engine_data = load_engine(engine_path)
        self.runtime = trt.Runtime(TRT_LOGGER)
        self.engine = self.runtime.deserialize_cuda_engine(engine_data)
        self.context = self.engine.create_execution_context()
        # Allocate buffers
        self.inputs, self.outputs, self.bindings = [], [], []
        self.stream = None  # will use default stream
        for i in range(self.engine.num_io_tensors):
            name = self.engine.get_tensor_name(i)
            shape = self.engine.get_tensor_shape(name)
            dtype = trt.nptype(self.engine.get_tensor_dtype(name))
            size = trt.volume(shape)
            buf = np.empty(shape, dtype=dtype) if i == 0 else np.empty(size, dtype=dtype)
            if self.engine.get_tensor_mode(name) == trt.TensorIOMode.INPUT:
                self.inputs.append(buf)
            else:
                self.outputs.append(buf)
            self.bindings.append(buf.ctypes.data)

    def detect(self, image_bgr, conf=YOLO_CONF_THRESH, iou=YOLO_IOU_THRESH):
        """Run detection on BGR image (numpy [H,W,3]).
        Returns list of dicts: {bbox:[x1,y1,x2,y2], confidence, class}.
        """
        import cv2
        h, w = image_bgr.shape[:2]
        # Preprocess
        img = cv2.resize(image_bgr, (640, 640))
        img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        img = img.astype(np.float32) / 255.0
        img = img.transpose(2, 0, 1)[np.newaxis, ...]  # [1,3,640,640]
        np.copyto(self.inputs[0], img)

        # Run
        self.context.execute_v2(self.bindings)

        # Postprocess
        results = postprocess(self.outputs[0], w, h, conf, iou)
        return [{"bbox": r[:4], "confidence": r[4], "class": int(r[5])} for r in results]


# ── CLI ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import cv2
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <image_path> [conf_thresh] [iou_thresh]")
        sys.exit(1)

    img_path = sys.argv[1]
    conf = float(sys.argv[2]) if len(sys.argv) > 2 else 0.25
    iou = float(sys.argv[3]) if len(sys.argv) > 3 else 0.45

    img = cv2.imread(img_path)
    if img is None:
        print(f"ERROR: cannot read {img_path}")
        sys.exit(1)

    print(f"[yolo26] Loading engine...")
    t0 = time.time()
    detector = YOLO26()
    print(f"[yolo26] Init: {time.time()-t0:.1f}s")

    t1 = time.time()
    dets = detector.detect(img, conf=conf, iou=iou)
    dt = time.time() - t1
    print(f"[yolo26] Inference: {dt*1000:.0f}ms, {len(dets)} detections")
    print(json.dumps(dets, indent=2, ensure_ascii=False))
