"""
K32 动态告警阈值 (Adaptive Alert Thresholds)
吸收来源: Walmart Missed Scan Detection
功能: 按门店营业时段 + 学习期自动调整告警灵敏度

架构:
- TimeSlotManager: 管理时段划分和灵敏度
- StoreProfile: 门店个性化阈值 profile
- AdaptiveAlertEngine: 统一入口，根据时间+门店返回当前阈值
"""

import time
import json
import logging
from datetime import datetime, time as dt_time
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional
from pathlib import Path

logger = logging.getLogger("adaptive_alert")

# ---------------------------------------------------------------------------
# 时段定义
# ---------------------------------------------------------------------------

class AlertSensitivity(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    MINIMAL = "minimal"


@dataclass
class TimeSlot:
    """营业时段"""
    name: str
    start: dt_time
    end: dt_time
    sensitivity: AlertSensitivity
    description: str = ""


# 火锅店典型时段
DEFAULT_TIME_SLOTS = [
    TimeSlot("午市高峰",  dt_time(11, 0), dt_time(14, 0), AlertSensitivity.HIGH,
             "人流密集，异常容忍度低"),
    TimeSlot("午市备料",  dt_time(14, 0), dt_time(17, 0), AlertSensitivity.LOW,
             "备菜期，减少误报"),
    TimeSlot("晚市高峰",  dt_time(17, 0), dt_time(22, 0), AlertSensitivity.HIGH,
             "全天最高峰，所有检测全开"),
    TimeSlot("宵夜时段",  dt_time(22, 0), dt_time(2,  0), AlertSensitivity.MEDIUM,
             "次高峰，但后厨人员减少"),
    TimeSlot("深夜休市",  dt_time(2,  0), dt_time(11, 0), AlertSensitivity.MINIMAL,
             "无人时段，仅保留IoT告警"),
]


# ---------------------------------------------------------------------------
# 门店学习期 profile
# ---------------------------------------------------------------------------

@dataclass
class StoreProfile:
    """门店个性化阈值 profile"""
    store_id: str
    learning_period_days: int = 30              # 学习期天数
    first_seen: float = field(default_factory=time.time)

    # 学习期内累计的基线数据
    alert_counts: dict = field(default_factory=dict)   # {event_type: count}
    alert_baseline_per_hour: dict = field(default_factory=dict)

    # 个性化乘数 (学习期后生效)
    threshold_multiplier: float = 1.0           # >1 = 更宽松, <1 = 更严格

    def is_learning(self) -> bool:
        return (time.time() - self.first_seen) < (self.learning_period_days * 86400)

    def record_alert(self, event_type: str):
        self.alert_counts[event_type] = self.alert_counts.get(event_type, 0) + 1

    def finish_learning(self):
        """学习期结束：基于收集到的基线计算个性化乘数"""
        total = sum(self.alert_counts.values())
        if total > 0:
            # 如果这家店告警特别多，适当放宽阈值(乘数>1)
            # 如果告警特别少，可以收紧(乘数<1)但保持最低乘数
            avg_per_day = total / max(self.learning_period_days, 1)
            if avg_per_day > 50:
                self.threshold_multiplier = 1.3   # 放宽30%
            elif avg_per_day < 10:
                self.threshold_multiplier = 0.9   # 收紧10%
            else:
                self.threshold_multiplier = 1.0   # 维持标准

            logger.info(
                "Store %s learning complete: avg=%.1f alerts/day, multiplier=%.2f",
                self.store_id, avg_per_day, self.threshold_multiplier,
            )


# ---------------------------------------------------------------------------
# 自适应引擎
# ---------------------------------------------------------------------------

class TimeSlotManager:
    """时段管理器 — 判断当前处于哪个时段"""

    def __init__(self, slots: Optional[list] = None):
        self.slots = slots or DEFAULT_TIME_SLOTS

    def get_current_slot(self, now: Optional[datetime] = None) -> TimeSlot:
        """返回当前时段"""
        t = (now or datetime.now()).time()
        for slot in self.slots:
            if self._in_slot(t, slot):
                return slot
        # fallback
        return self.slots[0]

    @staticmethod
    def _in_slot(t: dt_time, slot: TimeSlot) -> bool:
        """处理跨午夜时段 (如 22:00-02:00)"""
        if slot.start <= slot.end:
            return slot.start <= t <= slot.end
        else:
            return t >= slot.start or t <= slot.end


@dataclass
class ThresholdSet:
    """一组告警阈值"""
    # 废料检测
    waste_min_interval_sec: float = 30.0      # 两次告警最小间隔
    waste_count_threshold: int = 3            # N次/分钟才告警

    # 桌态检测
    table_empty_min_sec: float = 300.0        # 空桌>N秒才提醒
    table_needs_clean_min_dishes: int = 3

    # SOP 合规
    sop_violation_grace_sec: float = 60.0     # 违规宽限期 (秒)
    sop_repeat_window_sec: float = 600.0      # 同工位重复告警窗口

    # IoT 食安
    temp_deviation_grace_sec: float = 300.0   # 温度偏离宽限期 (5min)
    temp_hysteresis_c: float = 1.0            # 温度回滞

    # 员工行为
    service_response_max_sec: float = 180.0   # 服务响应最长等待
    attendance_grace_min: float = 5.0         # 到岗宽限分钟数

    def apply_sensitivity(self, sens: AlertSensitivity,
                          multiplier: float = 1.0) -> "ThresholdSet":
        """按灵敏度和门店乘数调整所有阈值"""
        m = multiplier
        if sens == AlertSensitivity.HIGH:
            # 收紧所有阈值 → 更容易告警
            return ThresholdSet(
                waste_min_interval_sec=self.waste_min_interval_sec * 0.5 * m,
                waste_count_threshold=max(1, int(self.waste_count_threshold * 0.5 / m)),
                table_empty_min_sec=self.table_empty_min_sec * 0.5 * m,
                table_needs_clean_min_dishes=max(2, int(self.table_needs_clean_min_dishes * 0.7 / m)),
                sop_violation_grace_sec=self.sop_violation_grace_sec * 0.3 * m,
                sop_repeat_window_sec=self.sop_repeat_window_sec * 1.5 / m,
                temp_deviation_grace_sec=self.temp_deviation_grace_sec * 0.5 * m,
                temp_hysteresis_c=self.temp_hysteresis_c * 0.5 * m,
                service_response_max_sec=self.service_response_max_sec * 0.7 * m,
                attendance_grace_min=self.attendance_grace_min * 0.5 * m,
            )
        elif sens == AlertSensitivity.MEDIUM:
            return ThresholdSet(
                waste_min_interval_sec=self.waste_min_interval_sec * 0.8 * m,
                waste_count_threshold=self.waste_count_threshold,
                table_empty_min_sec=self.table_empty_min_sec * 0.8 * m,
                table_needs_clean_min_dishes=self.table_needs_clean_min_dishes,
                sop_violation_grace_sec=self.sop_violation_grace_sec * 0.7 * m,
                sop_repeat_window_sec=self.sop_repeat_window_sec * m,
                temp_deviation_grace_sec=self.temp_deviation_grace_sec * 0.8 * m,
                temp_hysteresis_c=self.temp_hysteresis_c * 0.8 * m,
                service_response_max_sec=self.service_response_max_sec * 0.9 * m,
                attendance_grace_min=self.attendance_grace_min * 0.8 * m,
            )
        elif sens == AlertSensitivity.LOW:
            # 放宽 → 减少误报
            return ThresholdSet(
                waste_min_interval_sec=self.waste_min_interval_sec * 1.5 / m,
                waste_count_threshold=self.waste_count_threshold + 1,
                table_empty_min_sec=self.table_empty_min_sec * 1.5 / m,
                table_needs_clean_min_dishes=self.table_needs_clean_min_dishes + 1,
                sop_violation_grace_sec=self.sop_violation_grace_sec * 2.0 / m,
                sop_repeat_window_sec=self.sop_repeat_window_sec * 0.5 * m,
                temp_deviation_grace_sec=self.temp_deviation_grace_sec * 1.5 / m,
                temp_hysteresis_c=self.temp_hysteresis_c * 1.5 / m,
                service_response_max_sec=self.service_response_max_sec * 1.3 / m,
                attendance_grace_min=self.attendance_grace_min * 1.5 / m,
            )
        else:  # MINIMAL — 只保留IoT
            return ThresholdSet(
                waste_min_interval_sec=9999,
                waste_count_threshold=999,
                table_empty_min_sec=99999,
                table_needs_clean_min_dishes=999,
                sop_violation_grace_sec=99999,
                sop_repeat_window_sec=0,
                temp_deviation_grace_sec=self.temp_deviation_grace_sec * 2.0,
                temp_hysteresis_c=self.temp_hysteresis_c * 2.0,
                service_response_max_sec=99999,
                attendance_grace_min=999,
            )


class AdaptiveAlertEngine:
    """
    统一入口: 根据当前时间 + 门店 profile 返回自适应阈值

    用法:
        engine = AdaptiveAlertEngine(store_id="S001")
        thresh = engine.get_thresholds()
        if violation_duration > thresh.sop_violation_grace_sec:
            alert()
    """

    def __init__(self, store_id: str,
                 profile_dir: str = "/data/hotpot/profiles"):
        self.store_id = store_id
        self.slot_mgr = TimeSlotManager()
        self.profile = self._load_profile(Path(profile_dir))
        self.base_thresholds = ThresholdSet()

    def get_thresholds(self) -> ThresholdSet:
        """核心API: 返回当前时刻的自适应阈值"""
        now = datetime.now()
        slot = self.slot_mgr.get_current_slot(now)

        # 学习期内 → 用 LOW 灵敏度 (宽容，收集基线)
        if self.profile.is_learning():
            effective_sens = AlertSensitivity.LOW
            logger.debug(
                "Store %s in learning (day %d/%d), using LOW sensitivity",
                self.store_id,
                int((time.time() - self.profile.first_seen) / 86400),
                self.profile.learning_period_days,
            )
        else:
            effective_sens = slot.sensitivity

        thresholds = self.base_thresholds.apply_sensitivity(
            effective_sens,
            multiplier=self.profile.threshold_multiplier,
        )

        logger.debug(
            "Store=%s slot=%s sens=%s multiplier=%.2f",
            self.store_id, slot.name, effective_sens.value,
            self.profile.threshold_multiplier,
        )

        return thresholds

    def record_event(self, event_type: str):
        """记录一次告警事件 → 用于学习期数据收集"""
        self.profile.record_alert(event_type)

    def check_learning_complete(self):
        """检查学习期是否到期并完成"""
        if self.profile.is_learning():
            days_elapsed = (time.time() - self.profile.first_seen) / 86400
            if days_elapsed >= self.profile.learning_period_days:
                self.profile.finish_learning()
                self._save_profile()
                return True
        return False

    def _load_profile(self, profile_dir: Path) -> StoreProfile:
        """从磁盘加载门店 profile"""
        profile_file = profile_dir / f"{self.store_id}.json"
        if profile_file.exists():
            try:
                data = json.loads(profile_file.read_text())
                return StoreProfile(
                    store_id=data.get("store_id", self.store_id),
                    learning_period_days=data.get("learning_period_days", 30),
                    first_seen=data.get("first_seen", time.time()),
                    alert_counts=data.get("alert_counts", {}),
                    threshold_multiplier=data.get("threshold_multiplier", 1.0),
                )
            except Exception:
                logger.warning("Failed to load profile for %s, using default", self.store_id)
        return StoreProfile(store_id=self.store_id)

    def _save_profile(self):
        """保存门店 profile 到磁盘"""
        profile_dir = Path("/data/hotpot/profiles")
        profile_dir.mkdir(parents=True, exist_ok=True)
        pf = profile_dir / f"{self.store_id}.json"
        data = {
            "store_id": self.store_id,
            "learning_period_days": self.profile.learning_period_days,
            "first_seen": self.profile.first_seen,
            "alert_counts": self.profile.alert_counts,
            "threshold_multiplier": self.profile.threshold_multiplier,
        }
        pf.write_text(json.dumps(data, indent=2, ensure_ascii=False))
        logger.info("Profile saved for store %s", self.store_id)


# ---------------------------------------------------------------------------
# 部署标准化 Playbook 数据结构 (McDonald's 部署模式)
# ---------------------------------------------------------------------------

@dataclass
class DeployStep:
    """单步部署指导"""
    step_id: int
    duration_min: float          # 预估耗时(分钟)
    title: str
    instruction: str              # 微信推送内容
    auto_action: str = ""         # 自动执行的动作描述
    success_signal: str = ""      # 完成标志


DEPLOYMENT_PLAYBOOK = [
    DeployStep(1, 0, "盒子到货", "快递已签收，请扫码关注火瞳公众号"),
    DeployStep(2, 2, "公众号绑定", "扫码成功！正在为您推送部署视频(2分钟)"),
    DeployStep(3, 3, "开箱插电", "请拆开包装，将盒子插上电源。绿灯亮起表示已开机。",
               auto_action="盒子自启，启动推理服务"),
    DeployStep(4, 3, "摄像头发现", "正在扫描门店网络中的摄像头...",
               auto_action="mDNS/ONVIF 扫描局域网IPC",
               success_signal="发现N路摄像头"),
    DeployStep(5, 2, "确认摄像头", "检测到{N}路摄像头，是否全部接入？请回复'是'确认。",
               success_signal="用户确认"),
    DeployStep(6, 5, "IoT配对", "请将蓝牙温度计①贴到冷柜1号...",
               success_signal="全部传感器已配对"),
    DeployStep(7, 5, "系统自检", "正在自检...",
               auto_action="推理测试 + Hub连通性 + 存储检查",
               success_signal="自检全部通过"),
    DeployStep(8, 5, "学习期开始", "火瞳已就绪！正在学习你的后厨。未来30天将以宽松模式运行。",
               success_signal="首条检测记录已生成"),
    DeployStep(9, 5, "部署完成", "恭喜！火瞳部署完成。Dashboard 已生成第一条记录。",
               success_signal="微信 + Dashboard 双重确认"),
]

DEPLOY_TOTAL_MINUTES = sum(s.duration_min for s in DEPLOYMENT_PLAYBOOK)


def get_deploy_progress(summary_only: bool = False) -> dict:
    """返回部署进度 (供微信/Dashboard消费)"""
    return {
        "total_minutes": DEPLOY_TOTAL_MINUTES,
        "steps": [
            {
                "id": s.step_id,
                "title": s.title,
                "duration_min": s.duration_min,
                "instruction": s.instruction if not summary_only else "",
            }
            for s in DEPLOYMENT_PLAYBOOK
        ],
    }
