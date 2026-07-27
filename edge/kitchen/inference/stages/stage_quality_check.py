"""
K31 出品质检 (Output Quality Check)
吸收来源: Domino's DOM Pizza Checker
功能: 每道菜出后厨前 YOLO+CLIP 做最后一眼品控

架构: 独立 stage，嵌入 kitchen inference pipeline
- YOLO 检测菜品位置 + 分类
- CLIP 语义判断: 摆盘完整度 / 份量 / 异物
- <3秒内推送到出菜口告警
"""

import time
import json
import logging
import math
from dataclasses import dataclass, field
from typing import Optional, List, Tuple

logger = logging.getLogger("stage.quality_check")

# ── CLIP 可用性全局标记 ─────────────────────────────────────────────
# 由 edge.agent.modules 在启动时根据 clip_infer 是否加载成功来设置。
# False 时所有质检方法使用 YOLO-rule fallback 并标记 untrusted=True。
_clip_available: bool = False

def set_clip_available(available: bool) -> None:
    """由模块加载器调用，标记 CLIP 推理是否可用。"""
    global _clip_available
    _clip_available = available
    if available:
        logger.info("CLIP 推理可用，出品质检使用 CLIP 语义判断")
    else:
        logger.warning("CLIP 推理不可用，出品质检降级为 YOLO-rule fallback（untrusted）")

# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------

@dataclass
class QualityCheckConfig:
    """品检配置 — 阈值按火锅品类可调"""
    enabled: bool = True
    max_check_time_ms: int = 3000          # 硬上限 3 秒
    plating_score_min: float = 0.65        # 摆盘完整度最低分 (CLIP cosine)
    portion_ratio_min: float = 0.5         # 份量最低比例 (vs 标准份量)
    foreign_object_confidence: float = 0.7 # 异物检测置信度
    # ── YOLO fallback 阈值（CLIP 不可用时启用） ──
    fallback_dish_area_ratio_min: float = 0.35  # YOLO 检测框占比最低值
    fallback_dish_count_min: int = 1            # 至少检测到 1 个食材目标
    fallback_unknown_det_conf_threshold: float = 0.55  # 未知高置信检测视为异物告警
    
    # YOLO 菜品类别 (火锅常见)
    dish_classes: list = field(default_factory=lambda: [
        "meat_plate", "vegetable_plate", "seafood_plate",
        "tofu_plate", "staple_bowl", "sauce_dish", "drink"
    ])


# ---------------------------------------------------------------------------
# 品检结果
# ---------------------------------------------------------------------------

@dataclass
class QualityResult:
    """单道菜品质检结果"""
    dish_id: str
    dish_class: str
    timestamp: float

    passed: bool = True
    plating_score: float = 1.0
    portion_ratio: float = 1.0
    foreign_objects: list = field(default_factory=list)

    alert_level: str = "none"         # none / warning / critical
    alert_message: str = ""
    check_time_ms: float = 0.0
    untrusted: bool = False           # CLIP 不可用时标记为 untrusted
    inference_source: str = "clip"    # "clip" | "yolo_fallback"

    def to_event(self, store_id: str = "") -> dict:
        return {
            "type": "quality_check",
            "store_id": store_id,
            "dish_id": self.dish_id,
            "dish_class": self.dish_class,
            "passed": self.passed,
            "plating_score": round(self.plating_score, 3),
            "portion_ratio": round(self.portion_ratio, 3),
            "foreign_objects": self.foreign_objects,
            "alert_level": self.alert_level,
            "alert_message": self.alert_message,
            "check_time_ms": round(self.check_time_ms, 1),
            "untrusted": self.untrusted,
            "inference_source": self.inference_source,
            "timestamp": self.timestamp,
        }


# ---------------------------------------------------------------------------
# 品检引擎
# ---------------------------------------------------------------------------

class DishQualityChecker:
    """
    出品质检引擎
    用法:
        checker = DishQualityChecker(config)
        result = checker.check(frame, dish_id="D001", dish_class="meat_plate")
        if not result.passed:
            push_alert(result.to_event())
    """

    def __init__(self, config: Optional[QualityCheckConfig] = None):
        self.config = config or QualityCheckConfig()

    def check(self, frame, dish_id: str = "",
              dish_class: str = "unknown") -> QualityResult:
        """
        对一张菜品图像做质检，返回 QualityResult。
        实际推理由 edge.agent.modules 调用时注入。
        """
        t0 = time.time()
        result = QualityResult(
            dish_id=dish_id,
            dish_class=dish_class,
            timestamp=t0,
        )

        # --- 判断推理来源 ---
        uses_clip = self._has_clip_scores(frame)
        result.untrusted = not uses_clip
        result.inference_source = "clip" if uses_clip else "yolo_fallback"

        if not uses_clip and _clip_available:
            # CLIP 引擎可用但当前 frame 未被预处理 → 记录异常
            logger.warning(
                "质检: CLIP 可用但 frame 未携带 CLIP 分数，降级为 YOLO fallback (dish=%s)",
                dish_id,
            )

        # --- YOLO 检测 (由调用方注入 bbox/detections) ---
        detections = getattr(frame, "detections", [])
        yolo_passed = len(detections) > 0

        # --- 三连质检 ---
        plating_ok = self._check_plating(frame)
        portion_ok = self._check_portion(frame)
        foreign_ok, foreign_list = self._check_foreign_objects(frame)

        # 汇总
        result.plating_score = plating_ok
        result.portion_ratio = portion_ok
        result.foreign_objects = foreign_list

        all_ok = yolo_passed and (plating_ok >= self.config.plating_score_min) \
                 and (portion_ok >= self.config.portion_ratio_min) \
                 and foreign_ok

        result.passed = all_ok

        # --- 告警分级 ---
        if not all_ok:
            issues = []
            if plating_ok < self.config.plating_score_min:
                issues.append(f"摆盘异常(得分{plating_ok:.2f}<{self.config.plating_score_min})")
            if portion_ok < self.config.portion_ratio_min:
                issues.append(f"份量不足({portion_ok:.0%}<{self.config.portion_ratio_min:.0%})")
            if not foreign_ok:
                issues.append(f"疑似异物: {foreign_list}")
            if result.untrusted:
                issues.append("[注意: 使用YOLO fallback，结果仅供参考]")

            result.alert_message = "; ".join(issues)

            # 异物 = critical, 其他 = warning
            if not foreign_ok:
                result.alert_level = "critical"
            else:
                result.alert_level = "warning"

        result.check_time_ms = (time.time() - t0) * 1000

        # 超时告警
        if result.check_time_ms > self.config.max_check_time_ms:
            logger.warning(
                "质检超时: dish=%s time=%.0fms limit=%dms source=%s",
                dish_id, result.check_time_ms, self.config.max_check_time_ms,
                result.inference_source,
            )

        return result

    # ------------------------------------------------------------------
    # 内部检测方法 (CLIP 优先 → YOLO-rule fallback)
    # ------------------------------------------------------------------

    def _has_clip_scores(self, frame) -> bool:
        """检查 frame 是否已被 CLIP 模块预处理过。"""
        return (_clip_available and
                hasattr(frame, "clip_plating_score") and
                hasattr(frame, "clip_portion_ratio"))

    def _check_plating(self, frame) -> float:
        """
        摆盘完整性评分 0-1。

        - CLIP 可用: 使用 CLIP 语义对比 "well-plated hotpot dish" vs "messy dish"
        - CLIP 不可用: 使用 YOLO 检测框面积与图像面积的比例作为 heuristic
        """
        if self._has_clip_scores(frame):
            score = float(getattr(frame, "clip_plating_score", 0.0))
            logger.debug("plating score (CLIP): %.3f", score)
            return score

        # ── YOLO fallback ──
        return self._fallback_plating_check(frame)

    def _check_portion(self, frame) -> float:
        """
        份量比例 0-1。

        - CLIP 可用: 对比当前帧 CLIP embedding vs 标准份量模板
        - CLIP 不可用: 使用所有 dish_classes 检测框的总面积 / 图像面积
        """
        if self._has_clip_scores(frame):
            ratio = float(getattr(frame, "clip_portion_ratio", 0.0))
            logger.debug("portion ratio (CLIP): %.3f", ratio)
            return ratio

        # ── YOLO fallback ──
        return self._fallback_portion_check(frame)

    def _check_foreign_objects(self, frame) -> Tuple[bool, List[str]]:
        """
        异物检测。

        - CLIP 可用: CLIP 零样本 "foreign object in food: hair, plastic, metal, insect"
        - CLIP 不可用: 检查是否有高置信度但不在 dish_classes 中的 YOLO 检测
        """
        if _clip_available and hasattr(frame, "foreign_objects"):
            foreign = getattr(frame, "foreign_objects", [])
            return (len(foreign) == 0, list(foreign))

        # ── YOLO fallback ──
        return self._fallback_foreign_check(frame)

    # ── YOLO-rule fallback 实现 ─────────────────────────────────────

    def _fallback_plating_check(self, frame) -> float:
        """
        基于 YOLO 检测框的摆盘完整性 heuristic。

        规则:
        - 检测到的 dish_classes 目标数 >= fallback_dish_count_min → 基础 0.5
        - 所有 dish 检测框总面积 / 图像面积越接近理想值(0.15-0.35)分数越高
        - 如果没有 YOLO 检测结果，返回 0.0 并在日志中明确标记 untrusted
        """
        detections = getattr(frame, "detections", [])
        if not detections:
            logger.warning("质检(fallback·摆盘): 无 YOLO 检测结果，返回 0.0 (untrusted)")
            return 0.0

        dish_dets = [
            d for d in detections
            if hasattr(d, "class_name") and d.class_name in self.config.dish_classes
        ]
        if len(dish_dets) < self.config.fallback_dish_count_min:
            logger.warning(
                "质检(fallback·摆盘): 检测到 %d 个菜品目标 < 最低 %d",
                len(dish_dets), self.config.fallback_dish_count_min,
            )
            return max(0.0, 0.4 * len(dish_dets) / self.config.fallback_dish_count_min)

        # 计算 dish 检测框总面积占比
        img_area = getattr(frame, "width", 640) * getattr(frame, "height", 480)
        total_dish_area = 0.0
        for d in dish_dets:
            w = getattr(d, "width", 0) or (getattr(d, "bbox", [0, 0, 0, 0])[2] - getattr(d, "bbox", [0, 0, 0, 0])[0])
            h = getattr(d, "height", 0) or (getattr(d, "bbox", [0, 0, 0, 0])[3] - getattr(d, "bbox", [0, 0, 0, 0])[1])
            total_dish_area += w * h

        area_ratio = total_dish_area / max(img_area, 1)
        # 理想区域比约为 0.15-0.35（画面中菜品约占 15-35%）
        ideal_ratio = 0.25
        ratio_score = max(0.0, 1.0 - abs(area_ratio - ideal_ratio) / ideal_ratio)
        score = 0.4 + 0.5 * ratio_score  # 范围 0.4-0.9
        logger.debug("质检(fallback·摆盘): area_ratio=%.3f score=%.3f", area_ratio, score)
        return round(min(0.9, score), 3)

    def _fallback_portion_check(self, frame) -> float:
        """
        基于 YOLO 检测框的份量比例 heuristic。

        规则:
        - 检测到 dish_classes 中有检测框 → 0.6 起步
        - 检测框总面积占比越接近标准，分数越高
        - dish 类别数越多 → 分数略高（说明食材种类齐全）
        """
        detections = getattr(frame, "detections", [])
        if not detections:
            logger.warning("质检(fallback·份量): 无 YOLO 检测结果，返回 0.0 (untrusted)")
            return 0.0

        dish_dets = [
            d for d in detections
            if hasattr(d, "class_name") and d.class_name in self.config.dish_classes
        ]
        if not dish_dets:
            return 0.3  # 有检测但无菜品 → 可能画面异常

        # 检测框面积占比
        img_area = getattr(frame, "width", 640) * getattr(frame, "height", 480)
        total_area = sum(
            (getattr(d, "width", 50) * getattr(d, "height", 50))
            for d in dish_dets
        )
        area_ratio = total_area / max(img_area, 1)

        # dish 类别数量作为多样性加分
        unique_classes = len(set(
            d.class_name for d in dish_dets if hasattr(d, "class_name")
        ))
        diversity_bonus = min(0.15, 0.05 * unique_classes)

        # 归一化份量分数
        target_ratio = self.config.fallback_dish_area_ratio_min * 1.5
        ratio_score = min(1.0, area_ratio / max(target_ratio, 0.01))
        score = 0.45 + 0.4 * ratio_score + diversity_bonus
        logger.debug(
            "质检(fallback·份量): area=%.3f ratio=%.3f classes=%d score=%.3f",
            area_ratio, ratio_score, unique_classes, score,
        )
        return round(min(0.9, score), 3)

    def _fallback_foreign_check(self, frame) -> Tuple[bool, List[str]]:
        """
        基于 YOLO 检测的异物 heuristic。

        规则:
        - 高置信度(>=fallback_unknown_det_conf_threshold)但不在 dish_classes 中的检测
        - 且不在已知安全类别(如 person, chair 等)中 → 标记为疑似异物
        """
        detections = getattr(frame, "detections", [])
        if not detections:
            return (True, [])

        # 已知安全类别（非食材但也不构成异物告警）
        safe_classes = {
            "person", "chair", "table", "bottle", "cup", "bowl",
            "knife", "spoon", "fork", "refrigerator", "oven", "sink",
        }
        suspect: List[str] = []
        for d in detections:
            cls = getattr(d, "class_name", "")
            conf = getattr(d, "confidence", getattr(d, "conf", 0.0))
            if (conf >= self.config.fallback_unknown_det_conf_threshold
                    and cls not in self.config.dish_classes
                    and cls not in safe_classes
                    and cls != ""):
                suspect.append(f"{cls}({conf:.2f})")
                logger.warning(
                    "质检(fallback·异物): 疑似异物 %s conf=%.2f",
                    cls, conf,
                )

        return (len(suspect) == 0, suspect)


# ---------------------------------------------------------------------------
# 批量品检 (每小时汇总)
# ---------------------------------------------------------------------------

class QualitySummary:
    """每小时品控统计"""

    def __init__(self, store_id: str):
        self.store_id = store_id
        self.total_checks = 0
        self.passed = 0
        self.warnings = 0
        self.criticals = 0
        self.by_dish_class: dict = {}
        self.avg_check_time_ms = 0.0

    def record(self, result: QualityResult):
        self.total_checks += 1
        if result.passed:
            self.passed += 1
        if result.alert_level == "warning":
            self.warnings += 1
        elif result.alert_level == "critical":
            self.criticals += 1

        cls = result.dish_class
        if cls not in self.by_dish_class:
            self.by_dish_class[cls] = {"total": 0, "passed": 0}
        self.by_dish_class[cls]["total"] += 1
        if result.passed:
            self.by_dish_class[cls]["passed"] += 1

        n = self.total_checks
        self.avg_check_time_ms = (
            (self.avg_check_time_ms * (n - 1) + result.check_time_ms) / n
        )

    def to_report(self) -> dict:
        pass_rate = self.passed / max(self.total_checks, 1)
        return {
            "store_id": self.store_id,
            "total_checks": self.total_checks,
            "passed": self.passed,
            "warnings": self.warnings,
            "criticals": self.criticals,
            "pass_rate": round(pass_rate, 3),
            "avg_check_time_ms": round(self.avg_check_time_ms, 1),
            "by_dish_class": self.by_dish_class,
        }
