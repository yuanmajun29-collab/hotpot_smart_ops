#!/usr/bin/env python3
"""
确定性记分牌 — Agent + VLM 之间的唯一交接面

核心理念（来自 Agent+VLM 工业落地实践）：
  VLM 和 Agent 不直接对话，共同读一块确定性记分牌。
  - CV/几何层做一票否决（零模型调用，不幻觉）
  - 文字层/规则层直接抽取（不让 VLM 猜）
  - Agent 基于指标编排，不基于 VLM "感想"

使用方式:
  from edge.common.scoreboard import Scoreboard, Verdict

  sb = Scoreboard(scene="kitchen")
  sb.record_yolo(detections=..., conf=0.85)       # 确定性检测
  sb.record_clip(classifications=..., conf=0.6)    # CLIP 分类
  sb.record_vlm(vlm_output=..., conf=0.7)          # VLM 语义
  sb.cross_verify()                                 # 交叉验证
  verdict = sb.verdict()                            # 最终裁定

  if verdict == Verdict.PASS:
      publish_to_hub(sb.summary())
  elif verdict == Verdict.UNCERTAIN:
      flag_for_human_review(sb.summary())
  else:  # REJECT
      log_and_retry(sb)
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple
import json
import time


class Verdict(Enum):
    """记分牌最终裁定"""
    PASS = "pass"           # 可信，发布
    UNCERTAIN = "uncertain" # 存疑，人工复核
    REJECT = "reject"       # 不可信，丢弃/重试


@dataclass
class DetectionRecord:
    """单次检测记录 — CV/CLIP/VLM 的统一数据格式"""
    source: str                          # "yolo" | "clip" | "vlm"
    bbox: Optional[Tuple[float, float, float, float]] = None  # x1, y1, x2, y2
    label: str = ""
    confidence: float = 0.0
    extra: Dict[str, Any] = field(default_factory=dict)


@dataclass
class CrossCheck:
    """交叉验证结果"""
    yolo_count: int = 0         # YOLO 检出数
    clip_count: int = 0         # CLIP 分类数
    vlm_count: int = 0          # VLM 声称数
    matched: int = 0            # YOLO∩VLM 匹配数
    extra_vlm: int = 0          # VLM 多报（可能是幻觉）
    missing_vlm: int = 0        # VLM 漏报
    conf_delta: float = 0.0     # YOLO conf - VLM conf 平均差值


class Scoreboard:
    """
    确定性记分牌

    关键设计决策:
    1. YOLO 检出 = 确定性事实（零模型调用，不幻觉）
    2. VLM 输出必须与 YOLO 交叉验证，不匹配的标记为"需复核"
    3. 确定性规则（面积、数量、颜色直方图）直接写入，绕开 VLM
    4. Agent 读取 verdict() 做编排决策，不直接读 VLM 原始输出
    """

    def __init__(self, scene: str = "kitchen", frame_id: str = ""):
        self.scene = scene
        self.frame_id = frame_id or str(int(time.time()))
        self.timestamp = time.time()

        # 各层记录
        self.yolo_records: List[DetectionRecord] = []
        self.clip_records: List[DetectionRecord] = []
        self.vlm_records: List[DetectionRecord] = []

        # 确定性规则结果（不依赖任何模型）
        self.deterministic: Dict[str, Any] = {}

        # 交叉验证
        self.cross_check: Optional[CrossCheck] = None

        # 阈值（可从 rules.py 覆盖）
        self.conf_threshold = 0.25       # 低于此值整体 UNCERTAIN
        self.match_iou_threshold = 0.3   # bbox 匹配 IoU 阈值
        self.extra_vlm_limit = 2         # VLM 多报超过此数 → REJECT

    # ── 记录层 ──

    def record_yolo(self, detections: List[dict]) -> "Scoreboard":
        """记录 YOLO 检出 — 确定性事实层"""
        self.yolo_records = [
            DetectionRecord(
                source="yolo",
                bbox=tuple(d.get("bbox", (0, 0, 0, 0))),
                label=d.get("class_name", d.get("label", "unknown")),
                confidence=d.get("confidence", d.get("conf", 0.0)),
                extra={"class_id": d.get("class_id", -1)}
            )
            for d in detections
        ]
        return self

    def record_clip(self, classifications: List[dict]) -> "Scoreboard":
        """记录 CLIP 分类"""
        self.clip_records = [
            DetectionRecord(
                source="clip",
                bbox=tuple(c.get("bbox", (0, 0, 0, 0))),
                label=c.get("class_name", c.get("label", "unknown")),
                confidence=c.get("confidence", c.get("conf", 0.0)),
            )
            for c in classifications
        ]
        return self

    def record_vlm(self, vlm_items: List[dict]) -> "Scoreboard":
        """记录 VLM 输出 — 自然语言解析后"""
        self.vlm_records = [
            DetectionRecord(
                source="vlm",
                bbox=None,  # VLM 通常不返回精确坐标
                label=item.get("waste_type", item.get("label", "unknown")),
                confidence=item.get("confidence", 0.0),
                extra={
                    "sku": item.get("sku", ""),
                    "reason": item.get("reason", ""),
                    "portion": item.get("estimated_portion", 0),
                }
            )
            for item in vlm_items
        ]
        return self

    # ── 确定性规则层（零模型调用） ──

    def add_deterministic(self, key: str, value: Any) -> "Scoreboard":
        """
        直接写入确定性事实
        例如: sb.add_deterministic("waste_area_pct", 0.15)  # 废弃区面积占比
             sb.add_deterministic("color_dominant", "green")  # 主导颜色
        """
        self.deterministic[key] = value
        return self

    # ── 交叉验证层 ──

    def cross_verify(self) -> "Scoreboard":
        """
        YOLO ↔ VLM 交叉验证
        - YOLO 检出 = ground truth（不幻觉）
        - VLM 声称数 vs YOLO 检出数 → 判断是否幻觉
        """
        cc = CrossCheck()
        cc.yolo_count = len(self.yolo_records)
        cc.vlm_count = len(self.vlm_records)
        cc.clip_count = len(self.clip_records)

        if cc.yolo_count == 0:
            # 空场景: YOLO 说没有，VLM 说有 → 幻觉
            cc.extra_vlm = cc.vlm_count
            cc.missing_vlm = 0
            cc.matched = 0
        else:
            # 有检测: 按数量近似匹配（无 bbox 时用计数比对）
            cc.matched = min(cc.yolo_count, cc.vlm_count)
            cc.extra_vlm = max(0, cc.vlm_count - cc.yolo_count)
            cc.missing_vlm = max(0, cc.yolo_count - cc.vlm_count)

        # 置信度差值
        avg_yolo_conf = sum(r.confidence for r in self.yolo_records) / max(1, cc.yolo_count)
        avg_vlm_conf = sum(r.confidence for r in self.vlm_records) / max(1, cc.vlm_count)
        cc.conf_delta = avg_yolo_conf - avg_vlm_conf

        self.cross_check = cc
        return self

    # ── 最终裁定 ──

    def verdict(self) -> Verdict:
        """基于记分牌所有证据，返回最终裁定"""
        if self.cross_check is None:
            self.cross_verify()
        assert self.cross_check is not None
        cc = self.cross_check

        # REJECT: VLM 明显幻觉
        if cc.extra_vlm > self.extra_vlm_limit:
            return Verdict.REJECT

        # REJECT: YOLO 检出严重不足
        if cc.yolo_count == 0 and cc.vlm_count > 0:
            return Verdict.REJECT

        # UNCERTAIN: 存在差异但不太大
        if cc.extra_vlm > 0 or cc.missing_vlm > 0:
            return Verdict.UNCERTAIN

        # UNCERTAIN: VLM 置信度低于阈值
        avg_vlm_conf = sum(r.confidence for r in self.vlm_records) / max(1, cc.vlm_count)
        if avg_vlm_conf < self.conf_threshold:
            return Verdict.UNCERTAIN

        return Verdict.PASS

    # ── 输出 ──

    def summary(self) -> dict:
        """生成可发布到 Hub 的摘要"""
        if self.cross_check is None:
            self.cross_verify()

        return {
            "frame_id": self.frame_id,
            "scene": self.scene,
            "timestamp": self.timestamp,
            "verdict": self.verdict().value,
            "cross_check": {
                "yolo_count": self.cross_check.yolo_count,
                "vlm_count": self.cross_check.vlm_count,
                "matched": self.cross_check.matched,
                "extra_vlm": self.cross_check.extra_vlm,
                "missing_vlm": self.cross_check.missing_vlm,
                "conf_delta": round(self.cross_check.conf_delta, 3),
            },
            "detections": [
                {
                    "source": r.source,
                    "label": r.label,
                    "confidence": round(r.confidence, 3),
                    "bbox": list(r.bbox) if r.bbox else None,
                    "extra": r.extra,
                }
                for records in [self.yolo_records, self.vlm_records]
                for r in records
            ],
            "deterministic": self.deterministic,
        }

    def to_json(self) -> str:
        return json.dumps(self.summary(), ensure_ascii=False, indent=2)
