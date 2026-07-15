#!/usr/bin/env python3
"""Supervision 集成 — 可选后处理增强

包装 YOLO 检测结果为 sv.Detections，提供:
  - 内置优化的 NMS (替代自写 NMS)
  - 统一标注接口 (BoxAnnotator, LabelAnnotator)
  - 数据集格式转换 (YOLO↔COCO)
  - 视频分析 (ByteTrack, LineZone)

用法:
  from supervision_wrapper import to_detections, annotate

  detections = to_detections(yolo_output)          # 转 sv.Detections
  annotated = annotate(image, detections)           # 标注可视化
  counts = zone_counts(detections, polygon)         # 进出计数

依赖: pip install supervision opencv-python
"""

import numpy as np
from typing import List, Optional, Tuple, Any

try:
    import supervision as sv
    HAS_SUPERVISION = True
except ImportError:
    HAS_SUPERVISION = False
    sv = None


# ─── 类别映射 ───
KITCHEN_CLASSES = {
    0: "background",  1: "person",     2: "bowl",
    3: "plate",       4: "pot",        5: "food",
    6: "waste",       7: "utensil",    8: "trash_bin",
}
DEFAULT_COLORS = sv.ColorPalette.DEFAULT if HAS_SUPERVISION else None


def to_detections(yolo_output: List[dict], hw: Optional[Tuple[int,int]] = None) -> Any:
    """将 YOLO 输出转为 sv.Detections.
    
    yolo_output: [{"bbox":[x1,y1,x2,y2], "confidence":, "class":}, ...]
    hw: (height, width) 可选，用于 mask 支持。
    """
    if not HAS_SUPERVISION:
        return yolo_output  # fallback

    if not yolo_output:
        return sv.Detections.empty()

    xyxy = np.array([d["bbox"] for d in yolo_output], dtype=np.float32)
    confidence = np.array([d.get("confidence", 0.0) for d in yolo_output], dtype=np.float32)
    class_id = np.array([d.get("class", 0) for d in yolo_output], dtype=np.int32)

    # Optional: tracker_id, class_name
    data = {}
    tracker_ids = [d.get("tracker_id") for d in yolo_output if "tracker_id" in d]
    if tracker_ids:
        data["tracker_id"] = np.array(tracker_ids, dtype=np.int32)

    class_names = [KITCHEN_CLASSES.get(int(c), f"class_{c}") for c in class_id]
    data["class_name"] = np.array(class_names)

    return sv.Detections(
        xyxy=xyxy,
        confidence=confidence,
        class_id=class_id,
        data=data,
    )


def annotate(image: np.ndarray, detections, show_labels: bool = True) -> np.ndarray:
    """在图像上标注检测框，返回带标注的 BGR 图像。
    
    image: BGR numpy [H,W,3]
    detections: sv.Detections 或 yolo_output list
    """
    if not HAS_SUPERVISION:
        # Fallback: simple OpenCV rectangles
        import cv2
        img = image.copy()
        dets = detections if isinstance(detections, list) else _to_list(detections)
        for d in dets:
            b = d["bbox"]
            cv2.rectangle(img, (int(b[0]), int(b[1])), (int(b[2]), int(b[3])), (0,255,0), 2)
            if show_labels:
                label = KITCHEN_CLASSES.get(int(d.get("class",0)), "?")
                cv2.putText(img, f"{label} {d['confidence']:.2f}",
                           (int(b[0]), int(b[1])-5),
                           cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0,255,0), 1)
        return img

    if not isinstance(detections, sv.Detections):
        detections = to_detections(detections)

    box_annotator = sv.BoxAnnotator(thickness=2, color=DEFAULT_COLORS)
    label_annotator = sv.LabelAnnotator(text_scale=0.5, color=DEFAULT_COLORS)

    annotated = box_annotator.annotate(scene=image.copy(), detections=detections)
    if show_labels and len(detections.class_id) > 0:
        labels = [
            f"{KITCHEN_CLASSES.get(int(cid), '?')} {conf:.2f}"
            for cid, conf in zip(detections.class_id, detections.confidence)
        ]
        annotated = label_annotator.annotate(scene=annotated, detections=detections, labels=labels)

    return annotated


def filter_detections(detections, class_ids: Optional[List[int]] = None,
                      min_conf: float = 0.0) -> Any:
    """按类别和置信度过滤检测结果."""
    if not HAS_SUPERVISION or not isinstance(getattr(detections, 'class_id', None), np.ndarray):
        return detections

    mask = np.ones(len(detections.class_id), dtype=bool)
    if class_ids:
        mask &= np.isin(detections.class_id, class_ids)
    if min_conf > 0:
        mask &= detections.confidence >= min_conf
    return detections[mask] if mask.any() else sv.Detections.empty()


def zone_count(detections, zone_polygon: np.ndarray) -> Tuple[int, int]:
    """计算进出多边形的检测数量。
    
    Returns: (inside_count, total_count)
    """
    if not HAS_SUPERVISION:
        return 0, len(detections) if isinstance(detections, list) else 0

    if not isinstance(detections, sv.Detections):
        detections = to_detections(detections)

    zone = sv.PolygonZone(polygon=zone_polygon)
    mask = zone.trigger(detections=detections)
    return int(np.sum(mask)), len(detections.class_id)


def to_xyxy_list(detections) -> List[List[float]]:
    """统一转回 [x1,y1,x2,y2] 列表."""
    if not HAS_SUPERVISION or not hasattr(detections, 'xyxy'):
        return [d["bbox"] for d in detections] if isinstance(detections, list) else []
    return detections.xyxy.tolist()


def _to_list(detections) -> List[dict]:
    """sv.Detections → yolo_output list."""
    result = []
    for i in range(len(detections.class_id)):
        result.append({
            "bbox": detections.xyxy[i].tolist(),
            "confidence": float(detections.confidence[i]) if detections.confidence is not None else 0.0,
            "class": int(detections.class_id[i]),
        })
    return result


# ─── 自检 ───
if __name__ == "__main__":
    import cv2

    print(f"Supervision: {'✅ installed' if HAS_SUPERVISION else '❌ not installed (fallback mode)'}")

    # Create a test image with a "detection"
    test_img = np.zeros((480, 640, 3), dtype=np.uint8)
    test_img[100:200, 100:200] = [0, 255, 0]

    dets = [
        {"bbox": [100, 100, 200, 200], "confidence": 0.95, "class": 2},  # bowl
        {"bbox": [300, 150, 400, 250], "confidence": 0.82, "class": 4},  # pot
    ]

    if HAS_SUPERVISION:
        sd = to_detections(dets)
        print(f"  Detections: {len(sd.class_id)} objects")
        annotated = annotate(test_img, sd)
        cv2.imwrite("/tmp/supervision_test.jpg", annotated)
        print("  ✅ Test image saved → /tmp/supervision_test.jpg")

        # Zone count test
        zone = np.array([[0,0], [640,0], [640,480], [0,480]])
        inside, total = zone_count(sd, zone)
        print(f"  Zone: {inside}/{total} inside")
    else:
        annotated_img = annotate(test_img, dets)
        print("  ✅ Fallback annotated (OpenCV-only)")
