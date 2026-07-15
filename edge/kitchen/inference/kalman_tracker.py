#!/usr/bin/env python3
"""Kalman 多目标跟踪器 — 稳定检测框，减少帧间抖动

基于恒速模型 (Constant Velocity):
  状态向量 x = [cx, cy, w, h, vx, vy, vw, vh]
  测量向量 z = [cx, cy, w, h]

用法:
  tracker = KalmanTracker(max_age=5, min_hits=3, iou_thresh=0.3)
  tracks = tracker.update(detections)  # detections = [{"bbox":[x1,y1,x2,y2],...}]
"""

import numpy as np
from typing import List, Dict, Optional


class KalmanBoxTracker:
    """单个目标的 Kalman 滤波器跟踪器 (8维状态，4维观测)."""

    def __init__(self, bbox: List[float]):
        # 8维状态: [cx, cy, w, h, vx, vy, vw, vh]
        self.kf = KalmanFilter(dim_x=8, dim_z=4)
        self.kf.F = np.array([
            [1, 0, 0, 0, 1, 0, 0, 0],
            [0, 1, 0, 0, 0, 1, 0, 0],
            [0, 0, 1, 0, 0, 0, 1, 0],
            [0, 0, 0, 1, 0, 0, 0, 1],
            [0, 0, 0, 0, 1, 0, 0, 0],
            [0, 0, 0, 0, 0, 1, 0, 0],
            [0, 0, 0, 0, 0, 0, 1, 0],
            [0, 0, 0, 0, 0, 0, 0, 1],
        ])
        self.kf.H = np.array([
            [1, 0, 0, 0, 0, 0, 0, 0],
            [0, 1, 0, 0, 0, 0, 0, 0],
            [0, 0, 1, 0, 0, 0, 0, 0],
            [0, 0, 0, 1, 0, 0, 0, 0],
        ])

        # 过程噪声 (位置变化较小，速度变化较大)
        self.kf.Q[4:, 4:] *= 0.01
        self.kf.Q[:4, :4] *= 0.001
        # 测量噪声
        self.kf.R *= 0.1

        cx, cy, w, h = self._xyxy_to_cxcywh(bbox)
        self.kf.x[:4] = np.array([[cx], [cy], [w], [h]])

        self.hits = 1          # 成功匹配次数
        self.age = 0           # 创建后的帧数
        self.time_since_update = 0


    def predict(self) -> np.ndarray:
        """预测下一帧位置，返回 [x1,y1,x2,y2]."""
        self.kf.predict()
        self.age += 1
        self.time_since_update += 1
        return self.get_state()


    def update(self, bbox: List[float]):
        """用新检测更新 Kalman 滤波器."""
        self.time_since_update = 0
        self.hits += 1
        cx, cy, w, h = self._xyxy_to_cxcywh(bbox)
        self.kf.update(np.array([[cx], [cy], [w], [h]]))


    def get_state(self) -> np.ndarray:
        """返回当前估计位置 [x1,y1,x2,y2]."""
        cx, cy, w, h = self.kf.x[:4].flatten()
        x1 = cx - w / 2
        y1 = cy - h / 2
        x2 = cx + w / 2
        y2 = cy + h / 2
        return np.array([x1, y1, x2, y2])


    @staticmethod
    def _xyxy_to_cxcywh(bbox):
        x1, y1, x2, y2 = bbox[:4]
        cx = (x1 + x2) / 2
        cy = (y1 + y2) / 2
        w = x2 - x1
        h = y2 - y1
        return cx, cy, w, h


class KalmanFilter:
    """轻量 KalmanFilter (不依赖 filterpy)."""

    def __init__(self, dim_x: int, dim_z: int):
        self.dim_x = dim_x
        self.dim_z = dim_z
        self.x = np.zeros((dim_x, 1))        # 状态
        self.P = np.eye(dim_x) * 1000       # 协方差
        self.Q = np.eye(dim_x)               # 过程噪声
        self.R = np.eye(dim_z)               # 测量噪声
        self.F = np.eye(dim_x)               # 状态转移
        self.H = np.zeros((dim_z, dim_x))    # 观测矩阵
        self.I = np.eye(dim_x)


    def predict(self):
        self.x = self.F @ self.x
        self.P = self.F @ self.P @ self.F.T + self.Q


    def update(self, z: np.ndarray):
        y = z - self.H @ self.x                     # 残差
        S = self.H @ self.P @ self.H.T + self.R     # 残差协方差
        K = self.P @ self.H.T @ np.linalg.inv(S)    # Kalman 增益
        self.x = self.x + K @ y
        self.P = (self.I - K @ self.H) @ self.P


def iou(bbox1: np.ndarray, bbox2: np.ndarray) -> float:
    """计算两个 bbox 的 IoU."""
    x1 = max(bbox1[0], bbox2[0])
    y1 = max(bbox1[1], bbox2[1])
    x2 = min(bbox1[2], bbox2[2])
    y2 = min(bbox1[3], bbox2[3])
    inter = max(0, x2 - x1) * max(0, y2 - y1)
    area1 = (bbox1[2] - bbox1[0]) * (bbox1[3] - bbox1[1])
    area2 = (bbox2[2] - bbox2[0]) * (bbox2[3] - bbox2[1])
    return inter / (area1 + area2 - inter + 1e-6)


class KalmanTracker:
    """多目标 Kalman 跟踪器."""

    def __init__(self, max_age: int = 5, min_hits: int = 3, iou_thresh: float = 0.3):
        self.max_age = max_age
        self.min_hits = min_hits
        self.iou_thresh = iou_thresh
        self.trackers: List[KalmanBoxTracker] = []
        self.next_id = 0


    def update(self, detections: List[dict]) -> List[dict]:
        """更新跟踪器，返回带 tracker_id 的检测结果列表.

        detections: [{"bbox":[x1,y1,x2,y2], "confidence":..., "class":...}]
        返回带 "tracker_id" 和 "smoothed_bbox" 的列表.
        """
        # Step 1: 所有 tracker 预测
        predictions = []
        for t in self.trackers:
            pred = t.predict()
            predictions.append(pred)

        # Step 2: 匈牙利匹配 (贪心 IoU)
        det_bboxes = np.array([d["bbox"][:4] for d in detections])
        matched_t = set()
        matched_d = set()

        if len(predictions) > 0 and len(det_bboxes) > 0:
            iou_matrix = np.zeros((len(predictions), len(det_bboxes)))
            for i, pred in enumerate(predictions):
                for j, det in enumerate(det_bboxes):
                    iou_matrix[i, j] = iou(pred, det)

            # 贪心匹配
            for _ in range(min(len(predictions), len(det_bboxes))):
                if iou_matrix.size == 0:
                    break
                idx = np.unravel_index(iou_matrix.argmax(), iou_matrix.shape)
                if iou_matrix[idx] < self.iou_thresh:
                    break
                t_idx, d_idx = idx
                if t_idx in matched_t or d_idx in matched_d:
                    iou_matrix[t_idx, d_idx] = 0
                    continue
                matched_t.add(t_idx)
                matched_d.add(d_idx)

                # 用新检测更新 tracker
                self.trackers[t_idx].update(det_bboxes[d_idx].tolist())
                iou_matrix[t_idx, :] = 0
                iou_matrix[:, d_idx] = 0

        # Step 3: 未匹配的新检测 → 新建 tracker
        for i in range(len(detections)):
            if i not in matched_d:
                t = KalmanBoxTracker(det_bboxes[i].tolist())
                self.trackers.append(t)

        # Step 4: 构建输出 (带 tracker_id)
        results = []
        # 为每个已确认的 tracker 输出
        active_trackers = []
        for t in self.trackers:
            if t.hits >= self.min_hits and t.time_since_update <= self.max_age:
                active_trackers.append(t)
                # 取当前状态
                state = t.get_state()
                # 找到最近的匹配检测
                results.append({
                    "tracker_id": id(t) % 10000,  # 用对象 id 模 10000
                    "smoothed_bbox": state.tolist(),
                    "hits": t.hits,
                    "age": t.age,
                })

        # 清理超时的 tracker
        self.trackers = [t for t in self.trackers if t.time_since_update <= self.max_age]

        # 合并检测结果
        merged = []
        for i, det in enumerate(detections):
            entry = dict(det)
            # 尝试关联 tracker
            det_bbox = np.array(det["bbox"][:4])
            best_iou = 0
            best_t = None
            for t in active_trackers:
                i = iou(det_bbox, t.get_state())
                if i > best_iou:
                    best_iou = i
                    best_t = t
            if best_t and best_iou >= self.iou_thresh:
                entry["tracker_id"] = id(best_t) % 10000
                entry["smoothed_bbox"] = best_t.get_state().tolist()
            else:
                entry["tracker_id"] = -1
            merged.append(entry)

        return merged


# ─── 测试 ───
if __name__ == "__main__":
    print("=== Kalman 跟踪器测试 ===")

    tracker = KalmanTracker(max_age=3, min_hits=1, iou_thresh=0.2)

    # 模拟连续 3 帧
    frames = [
        [{"bbox": [100, 100, 200, 200], "confidence": 0.9, "class": 2}],
        [{"bbox": [102, 98, 198, 202], "confidence": 0.85, "class": 2}],
        [{"bbox": [105, 95, 195, 205], "confidence": 0.88, "class": 2}],
    ]

    for i, frame in enumerate(frames):
        results = tracker.update(frame)
        print(f"\n帧 {i+1}:")
        for r in results:
            print(f"  tracker_id={r.get('tracker_id')} "
                  f"raw={[round(x,1) for x in r['bbox']]} "
                  f"smoothed={[round(x,1) for x in r.get('smoothed_bbox', r['bbox'])]}")

    print("\n✅ Kalman 滤波已平滑检测框抖动")
