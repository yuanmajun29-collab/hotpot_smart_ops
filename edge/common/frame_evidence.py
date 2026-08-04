"""
帧新鲜度检测与证据哈希模块 (P1-04)

功能:
1. 帧新鲜度检测 — 丢弃超过 max_age_ms 的过期帧
2. 证据哈希计算 — SHA256 帧指纹，用于溯源和去重
3. 时间戳单调性校验 — 检测帧时间戳回退/跳跃异常
4. 帧元数据封装 — 标准化的 EvidenceRef 数据结构

使用方式:
    from edge.common.frame_evidence import FrameEvidenceValidator

    validator = FrameEvidenceValidator(max_age_ms=3000)

    # 验证帧是否有效
    result = validator.validate(frame_data, capture_time, camera_id, frame_index)
    if not result.is_valid:
        logger.warning("帧被拒绝: %s", result.reject_reason)
        return None

    # 使用证据引用
    evidence_ref = result.evidence_ref
"""

from __future__ import annotations

import hashlib
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


@dataclass
class EvidenceRef:
    """视觉证据引用 (对齐 P0-B UnifiedEdgeEvent.EvidenceRef)

    Attributes:
        type: 证据类型 (image/jpeg, image/png)
        url: 存储路径或URL (本地路径格式: file:///opt/.../.cache/frame_xxx.jpg)
        hash_sha256: 帧内容SHA256哈希 (16进制, 前64字符)
        captured_at: ISO8601捕获时间戳
        camera_id: 摄像头标识
        frame_index: 帧序号 (单调递增)
        size_bytes: 原始大小
        freshness_ms: 帧年龄 (毫秒, 从捕获到验证的时间差)
    """
    type: str = "image/jpeg"
    url: str = ""
    hash_sha256: str = ""
    captured_at: str = ""
    camera_id: str = ""
    frame_index: int = 0
    size_bytes: int = 0
    freshness_ms: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": self.type,
            "url": self.url,
            "hash_sha256": self.hash_sha256,
            "captured_at": self.captured_at,
            "camera_id": self.camera_id,
            "frame_index": self.frame_index,
            "size_bytes": self.size_bytes,
            "freshness_ms": self.freshness_ms,
        }


@dataclass
class FrameValidationResult:
    """帧验证结果"""
    is_valid: bool
    evidence_ref: Optional[EvidenceRef] = None
    reject_reason: str = ""
    reject_code: str = ""  # EXPIRED / HASH_DUPLICATE / TIMESTAMP_BACKWARDS / JUMP_DETECTED / OK
    processing_latency_ms: int = 0


class FrameEvidenceValidator:
    """帧证据验证器

    职责:
    - 新鲜度检查: 帧从捕获到处理的延迟不超过阈值
    - 哈希计算: SHA256 内容指纹用于去重和溯源
    - 时间戳校验: 单调递增，检测回退和异常跳跃
    - 元数据封装: 生成标准 EvidenceRef 对象
    """

    def __init__(
        self,
        max_age_ms: int = 3000,
        enable_hash_dedup: bool = True,
        enable_timestamp_check: bool = True,
        jump_threshold_ms: int = 5000,  # 时间戳跳跃阈值(正方向)
        cache_size: int = 1000,  # 最近N帧哈希缓存(用于去重)
    ):
        self.max_age_ms = max_age_ms
        self.enable_hash_dedup = enable_hash_dedup
        self.enable_timestamp_check = enable_timestamp_check
        self.jump_threshold_ms = jump_threshold_ms

        # 去重缓存: {hash_sha256 -> frame_index}
        self._hash_cache: Dict[str, int] = {}
        self._cache_size = cache_size

        # 每个摄像头最后帧的时间戳 (用于单调性检查)
        # {camera_id -> (frame_index, timestamp_iso)}
        self._last_timestamp: Dict[str, tuple] = {}

        # 统计
        self._stats = {
            "total_validated": 0,
            "accepted": 0,
            "rejected_expired": 0,
            "rejected_duplicate": 0,
            "rejected_backwards": 0,
            "rejected_jump": 0,
        }

    def validate(
        self,
        frame_data: bytes,
        capture_time: Optional[datetime] = None,
        camera_id: str = "",
        frame_index: int = 0,
    ) -> FrameValidationResult:
        """验证帧并生成证据引用

        Args:
            frame_data: 原始帧数据 (JPEG/PNG bytes)
            capture_time: 帧捕获时间 (默认用当前时间)
            camera_id: 摄像头ID
            frame_index: 帧序号

        Returns:
            FrameValidationResult 包含验证结果和 EvidenceRef
        """
        start = time.time()
        self._stats["total_validated"] += 1

        # 默认捕获时间为当前
        if capture_time is None:
            capture_time = datetime.now(timezone.utc)

        # 计算帧年龄 (新鲜度)
        now = datetime.now(timezone.utc)
        age_ms = int((now - capture_time).total_seconds() * 1000)

        if age_ms > self.max_age_ms:
            self._stats["rejected_expired"] += 1
            return FrameValidationResult(
                is_valid=False,
                reject_reason=f"帧已过期: 年龄={age_ms}ms > 阈值={self.max_age_ms}ms",
                reject_code="EXPIRED",
                processing_latency_ms=int((time.time() - start) * 1000),
            )

        # 计算内容哈希
        content_hash = hashlib.sha256(frame_data).hexdigest()

        # 哈希去重
        if self.enable_hash_dedup:
            if content_hash in self._hash_cache:
                self._stats["rejected_duplicate"] += 1
                return FrameValidationResult(
                    is_valid=False,
                    reject_reason=f"重复帧: hash={content_hash[:16]}..., 上次帧索引={self._hash_cache[content_hash]}",
                    reject_code="HASH_DUPLICATE",
                    processing_latency_ms=int((time.time() - start) * 1000),
                )

            # 更新缓存 (LRU 简单实现: 超过大小清空一半)
            if len(self._hash_cache) >= self._cache_size:
                keys_to_remove = list(self._hash_cache.keys())[:self._cache_size // 2]
                for k in keys_to_remove:
                    del self._hash_cache[k]
            self._hash_cache[content_hash] = frame_index

        # 时间戳单调性检查
        if self.enable_timestamp_check and camera_id:
            last = self._last_timestamp.get(camera_id)
            if last is not None:
                last_idx, last_ts = last

                # 检查时间戳回退
                if capture_time < datetime.fromisoformat(last_ts):
                    self._stats["rejected_backwards"] += 1
                    return FrameValidationResult(
                        is_valid=False,
                        reject_reason=f"时间戳回退: 当前={capture_time.isoformat()} < 上次={last_ts}",
                        reject_code="TIMESTAMP_BACKWARDS",
                        processing_latency_ms=int((time.time() - start) * 1000),
                    )

                # 检查时间戳正向跳跃过大
                gap_ms = (capture_time - datetime.fromisoformat(last_ts)).total_seconds() * 1000
                if gap_ms > self.jump_threshold_ms and frame_index > last_idx + 1:
                    # 不拒绝但记录警告 (可能是丢帧恢复)
                    logger.warning(
                        "[FrameEvidence] %s 帧时间戳跳跃: %.0fms (帧 %d→%d)",
                        camera_id, gap_ms, last_idx, frame_index,
                    )

            self._last_timestamp[camera_id] = (frame_index, capture_time.isoformat())

        # ✅ 通过所有检查 — 构造 EvidenceRef
        self._stats["accepted"] += 1

        # 生成存储URL (标准格式)
        safe_camera = camera_id.replace("/", "_").replace(":", "_")
        url = f"file:///tmp/hotpot/evidence/{safe_camera}/{frame_index}_{content_hash[:12]}.jpg"

        evidence = EvidenceRef(
            type="image/jpeg",
            url=url,
            hash_sha256=content_hash,
            captured_at=capture_time.isoformat(),
            camera_id=camera_id,
            frame_index=frame_index,
            size_bytes=len(frame_data),
            freshness_ms=age_ms,
        )

        return FrameValidationResult(
            is_valid=True,
            evidence_ref=evidence,
            reject_code="OK",
            processing_latency_ms=int((time.time() - start) * 1000),
        )

    def get_stats(self) -> Dict[str, Any]:
        """获取验证统计"""
        total = self._stats["total_validated"]
        accepted = self._stats["accepted"]
        return {
            **self._stats,
            "accept_rate": round(accepted / max(total, 1) * 100, 1),
            "cache_size": len(self._hash_cache),
            "tracked_cameras": len(self._last_timestamp),
        }

    def reset_stats(self):
        """重置统计计数器"""
        self._stats = {
            "total_validated": 0,
            "accepted": 0,
            "rejected_expired": 0,
            "rejected_duplicate": 0,
            "rejected_backwards": 0,
            "rejected_jump": 0,
        }

    def clear_cache(self):
        """清除哈希缓存"""
        self._hash_cache.clear()
        self._last_timestamp.clear()


# ── 便捷工厂函数 ──

def create_validator_from_config(config: Dict[str, Any]) -> FrameEvidenceValidator:
    """从IPC配置创建验证器实例

    Args:
        config: 摄像头配置字典 (来自 ipc_config_*.yml)
            需要: frame_freshness_max_age_ms, model_profile 等
    """
    max_age = config.get("frame_freshness_max_age_ms", 3000)
    profile = config.get("model_profile", "default")

    # 根据模型类型调整参数
    profile_settings = {
        "hotpot_waste_v2": {"max_age_ms": 2000, "cache_size": 500},   # 废料检测需要更新鲜的帧
        "table_state_v1": {"max_age_ms": 5000, "cache_size": 2000},     # 翻台检测可以容忍稍旧的帧
        "staff_behavior": {"max_age_ms": 1500, "cache_size": 800},      # 行为检测需要高实时性
        "default": {"max_age_ms": max_age, "cache_size": 1000},
    }

    settings = profile_settings.get(profile, profile_settings["default"])

    return FrameEvidenceValidator(
        max_age_ms=settings["max_age_ms"],
        cache_size=settings["cache_size"],
    )


# 模块自测
if __name__ == "__main__":
    import sys

    print("=" * 60)
    print("FrameEvidenceValidator 自测")
    print("=" * 60)

    v = FrameEvidenceValidator(max_age_ms=3000)

    # 测试1: 正常帧应该通过
    fake_frame = b"\xff\xd8\xff\xe0\x00JFIF" + b"\x00" * 100  # 模拟JPEG头
    r1 = v.validate(fake_frame, camera_id="cam01", frame_index=1)
    assert r1.is_valid, f"测试1失败: {r1.reject_reason}"
    assert r1.evidence_ref.hash_sha256, "测试1: 缺少哈希"
    print(f"✅ 测试1 正常帧通过: hash={r1.evidence_ref.hash_sha256[:16]}...")

    # 测试2: 重复帧应被拒绝
    r2 = v.validate(fake_frame, camera_id="cam01", frame_index=2)
    assert not r2.is_valid, "测试2: 重复帧应该被拒绝"
    assert r2.reject_code == "HASH_DUPLICATE", f"测试2: 错误的拒绝码: {r2.reject_code}"
    print(f"✅ 测试2 重复帧被正确拒绝: {r2.reject_reason}")

    # 测试3: 过期帧应被拒绝
    old_time = datetime.now(timezone.utc) - timedelta(seconds=5)  # 5秒前
    r3 = v.validate(b"\xff\xd8" + b"\x00" * 50, capture_time=old_time, camera_id="cam02", frame_index=10)
    assert not r3.is_valid, "测试3: 过期帧应该被拒绝"
    assert r3.reject_code == "EXPIRED", f"测试3: 错误的拒绝码: {r3.reject_code}"
    print(f"✅ 测试3 过期帧被正确拒绝: {r3.reject_reason}")

    # 测试4: 时间戳回退应被拒绝
    # 先提交一个未来时间戳的帧 (设置 cam03 的最后时间基准)
    base_time = datetime.now(timezone.utc) + timedelta(seconds=10)
    r4_ok = v.validate(b"\xff\xd8" + b"\x01" * 50, capture_time=base_time, camera_id="cam03", frame_index=20)
    assert r4_ok.is_valid, f"测试4a失败: {r4_ok.reject_reason}"

    # 再提交一个比 base_time 早但在新鲜度阈值内的帧 → 应被检测为回退
    # past_time = base_time - 2s，年龄约 2s < 3s 阈值，但时间戳比 base_time 早
    back_time = base_time - timedelta(seconds=2)
    r4_fail = v.validate(b"\xff\xd8" + b"\x02" * 50, capture_time=back_time, camera_id="cam03", frame_index=21)
    assert not r4_fail.is_valid, "测试4b: 回退帧应该被拒绝"
    assert r4_fail.reject_code == "TIMESTAMP_BACKWARDS", f"测试4b: 期望 TIMESTAMP_BACKWARDS, 实际 {r4_fail.reject_code}: {r4_fail.reject_reason}"
    print(f"✅ 测试4 时间戳回退被正确检测")

    # 统计
    stats = v.get_stats()
    print(f"\n📊 统计: {stats}")

    print("\n" + "=" * 60)
    print("🎉 全部自测通过!")
    print("=" * 60)
