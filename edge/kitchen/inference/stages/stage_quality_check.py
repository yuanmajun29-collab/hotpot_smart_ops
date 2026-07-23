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
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger("stage.quality_check")

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

        # --- YOLO 检测 (由调用方注入 bbox/detections) ---
        # 这里接收外部推理结果
        detections = getattr(frame, "detections", [])
        yolo_passed = len(detections) > 0

        # --- CLIP 语义判断 ---
        # 三连检测:
        #   1. 摆盘完整性 (plating)
        #   2. 份量比例 (portion)
        #   3. 异物检测 (foreign_objects)
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

        # 告警分级
        if not all_ok:
            issues = []
            if plating_ok < self.config.plating_score_min:
                issues.append(f"摆盘异常(得分{plating_ok:.2f}<{self.config.plating_score_min})")
            if portion_ok < self.config.portion_ratio_min:
                issues.append(f"份量不足({portion_ok:.0%}<{self.config.portion_ratio_min:.0%})")
            if not foreign_ok:
                issues.append(f"疑似异物: {foreign_list}")

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
                "质检超时: dish=%s time=%.0fms limit=%dms",
                dish_id, result.check_time_ms, self.config.max_check_time_ms,
            )

        return result

    # ------------------------------------------------------------------
    # 内部检测方法 (实际由 CLIP 引擎执行，这里为接口层)
    # ------------------------------------------------------------------

    def _check_plating(self, frame) -> float:
        """
        摆盘完整性评分 0-1。
        CLIP 提示词: "A well-plated hotpot dish" vs "A messy hotpot dish"
        返回 cosine similarity 归一化到 0-1。
        """
        # 由调用方通过 CLIP 引擎注入结果
        return getattr(frame, "clip_plating_score", 0.85)

    def _check_portion(self, frame) -> float:
        """
        份量比例 0-1。
        对比当前帧中菜品区域 vs 标准份量模板。
        """
        return getattr(frame, "clip_portion_ratio", 0.80)

    def _check_foreign_objects(self, frame) -> tuple:
        """
        异物检测。
        CLIP 提示词: "Foreign object in food: hair, plastic, metal, insect"
        返回 (是否通过, [异物列表])
        """
        foreign = getattr(frame, "foreign_objects", [])
        return (len(foreign) == 0, foreign)


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
