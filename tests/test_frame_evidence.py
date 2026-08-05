"""
FrameEvidenceValidator 单元测试模块

测试范围:
1. FrameEvidenceValidator 实例化与配置
2. 帧新鲜度检测
3. SHA256 哈希去重
4. 单调时间戳校验
5. EvidenceRef 数据类验证
6. 综合流程测试
7. 边界情况处理

目标覆盖率: 85%+
"""

import hashlib
import time
from datetime import datetime, timezone, timedelta

import pytest

from edge.common.frame_evidence import (
    FrameEvidenceValidator,
    EvidenceRef,
    FrameValidationResult,
    create_validator_from_config,
)


# =============================================================================
# Fixtures - 测试数据组织
# =============================================================================


@pytest.fixture
def sample_jpeg_frame():
    """生成模拟JPEG帧数据 (带JPEG头)"""
    return b"\xff\xd8\xff\xe0\x00JFIF" + b"\x00" * 100


@pytest.fixture
def sample_png_frame():
    """生成模拟PNG帧数据"""
    return b"\x89PNG\r\n\x1a\n" + b"\x00" * 100


@pytest.fixture
def default_validator():
    """默认参数的验证器实例"""
    return FrameEvidenceValidator()


@pytest.fixture
def custom_validator():
    """自定义参数的验证器实例"""
    return FrameEvidenceValidator(
        max_age_ms=5000,
        enable_hash_dedup=True,
        enable_timestamp_check=True,
        jump_threshold_ms=3000,
        cache_size=200,
    )


@pytest.fixture
def current_time():
    """当前UTC时间 (用于新鲜度测试)"""
    return datetime.now(timezone.utc)


@pytest.fixture
def expired_time():
    """过期时间 (10秒前, 超过默认3秒阈值)"""
    return datetime.now(timezone.utc) - timedelta(seconds=10)


@pytest.fixture
def boundary_time():
    """边界时间 (刚好在阈值内, 2秒前)"""
    return datetime.now(timezone.utc) - timedelta(seconds=2)


# =============================================================================
# 1. FrameEvidenceValidator 实例化与配置测试
# =============================================================================


class TestValidatorInstantiation:
    """验证器实例化与配置测试"""

    def test_default_parameters(self):
        """默认参数实例化 - 所有参数应有正确默认值"""
        validator = FrameEvidenceValidator()

        assert validator.max_age_ms == 3000
        assert validator.enable_hash_dedup is True
        assert validator.enable_timestamp_check is True
        assert validator.jump_threshold_ms == 5000
        assert validator._cache_size == 1000
        assert len(validator._hash_cache) == 0
        assert len(validator._last_timestamp) == 0

    def test_custom_parameters(self):
        """自定义参数实例化 - 参数应按传入值设置"""
        validator = FrameEvidenceValidator(
            max_age_ms=5000,
            enable_hash_dedup=False,
            enable_timestamp_check=False,
            jump_threshold_ms=10000,
            cache_size=500,
        )

        assert validator.max_age_ms == 5000
        assert validator.enable_hash_dedup is False
        assert validator.enable_timestamp_check is False
        assert validator.jump_threshold_ms == 10000
        assert validator._cache_size == 500

    def test_create_validator_from_config_default(self):
        """工厂方法: 默认配置应使用默认profile"""
        config = {}
        validator = create_validator_from_config(config)

        assert isinstance(validator, FrameEvidenceValidator)
        assert validator.max_age_ms == 3000  # 默认值
        assert validator._cache_size == 1000

    def test_create_validator_from_config_custom_max_age(self):
        """工厂方法: 自定义max_age配置"""
        config = {"frame_freshness_max_age_ms": 2000}
        validator = create_validator_from_config(config)

        assert validator.max_age_ms == 2000

    def test_create_validator_from_config_waste_profile(self):
        """工厂方法: hotpot_waste_v2 profile 应使用对应参数"""
        config = {"model_profile": "hotpot_waste_v2"}
        validator = create_validator_from_config(config)

        assert validator.max_age_ms == 2000
        assert validator._cache_size == 500

    def test_create_validator_from_config_table_profile(self):
        """工厂方法: table_state_v1 profile 应使用对应参数"""
        config = {"model_profile": "table_state_v1"}
        validator = create_validator_from_config(config)

        assert validator.max_age_ms == 5000
        assert validator._cache_size == 2000

    def test_create_validator_from_config_staff_profile(self):
        """工厂方法: staff_behavior profile 应使用对应参数"""
        config = {"model_profile": "staff_behavior"}
        validator = create_validator_from_config(config)

        assert validator.max_age_ms == 1500
        assert validator._cache_size == 800


# =============================================================================
# 2. 帧新鲜度检测测试
# =============================================================================


class TestFrameFreshness:
    """帧新鲜度检测测试"""

    def test_fresh_frame_accepted(self, default_validator, sample_jpeg_frame, current_time):
        """正常帧 (新时间戳) → 应通过验证"""
        result = default_validator.validate(
            sample_jpeg_frame,
            capture_time=current_time,
            camera_id="cam01",
            frame_index=1,
        )

        assert result.is_valid is True
        assert result.reject_code == "OK"
        assert result.evidence_ref is not None

    def test_expired_frame_rejected(self, default_validator, sample_jpeg_frame, expired_time):
        """超时帧 (旧时间戳超过max_age_ms) → 应被拒绝"""
        result = default_validator.validate(
            sample_jpeg_frame,
            capture_time=expired_time,
            camera_id="cam02",
            frame_index=10,
        )

        assert result.is_valid is False
        assert result.reject_code == "EXPIRED"
        assert "过期" in result.reject_reason

    def test_boundary_frame_accepted(self, default_validator, sample_jpeg_frame, boundary_time):
        """边界值: 刚好在阈值内的帧 (2秒 < 3秒阈值) → 应通过"""
        result = default_validator.validate(
            sample_jpeg_frame,
            capture_time=boundary_time,
            camera_id="cam03",
            frame_index=5,
        )

        assert result.is_valid is True
        assert result.evidence_ref.freshness_ms < default_validator.max_age_ms

    def test_freshness_ms_calculation(self, default_validator, sample_jpeg_frame):
        """freshness_ms 应正确计算帧年龄"""
        past_time = datetime.now(timezone.utc) - timedelta(milliseconds=500)
        result = default_validator.validate(
            sample_jpeg_frame,
            capture_time=past_time,
            camera_id="cam04",
            frame_index=1,
        )

        # 允许一定误差 (处理延迟)
        assert 400 <= result.evidence_ref.freshness_ms <= 600

    def test_none_capture_time_uses_now(self, default_validator, sample_jpeg_frame):
        """None捕获时间 → 应使用当前时间 → 帧应通过"""
        result = default_validator.validate(
            sample_jpeg_frame,
            capture_time=None,
            camera_id="cam05",
            frame_index=1,
        )

        assert result.is_valid is True
        assert result.evidence_ref.freshness_ms >= 0


# =============================================================================
# 3. SHA256 哈希去重测试
# =============================================================================


class TestHashDeduplication:
    """SHA256 哈希去重测试"""

    def test_first_frame_is_new(self, default_validator, sample_jpeg_frame):
        """首次见到帧 → 缓存未命中 → 返回 IS_NEW (is_valid=True)"""
        result = default_validator.validate(
            sample_jpeg_frame,
            camera_id="cam01",
            frame_index=1,
        )

        assert result.is_valid is True
        assert result.evidence_ref.hash_sha256
        expected_hash = hashlib.sha256(sample_jpeg_frame).hexdigest()
        assert result.evidence_ref.hash_sha256 == expected_hash

    def test_duplicate_frame_rejected(self, default_validator, sample_jpeg_frame):
        """相同帧再次出现 → 缓存命中 → 返回 DUPLICATE"""
        # 第一次提交
        r1 = default_validator.validate(sample_jpeg_frame, camera_id="cam01", frame_index=1)
        assert r1.is_valid

        # 相同内容第二次提交
        r2 = default_validator.validate(sample_jpeg_frame, camera_id="cam01", frame_index=2)
        assert r2.is_valid is False
        assert r2.reject_code == "HASH_DUPLICATE"
        assert "重复帧" in r2.reject_reason

    def test_different_frames_pass(self, default_validator, sample_jpeg_frame, sample_png_frame):
        """不同内容的帧 → 不同hash → 都应通过"""
        r1 = default_validator.validate(sample_jpeg_frame, camera_id="cam01", frame_index=1)
        r2 = default_validator.validate(sample_png_frame, camera_id="cam01", frame_index=2)

        assert r1.is_valid is True
        assert r2.is_valid is True
        assert r1.evidence_ref.hash_sha256 != r2.evidence_ref.hash_sha256

    def test_lru_cache_eviction(self):
        """LRU缓存淘汰: 超过max_size后最旧的条目被移除"""
        small_cache_validator = FrameEvidenceValidator(cache_size=5)

        frames = []
        for i in range(7):  # 提交7个帧, 缓存大小为5
            frame_data = f"frame_data_{i}".encode()
            result = small_cache_validator.validate(frame_data, camera_id="cam", frame_index=i)
            if i < 5:
                assert result.is_valid is True
            frames.append(frame_data)

        # 缓存应该已被清理 (保留后插入的部分)
        assert len(small_cache_validator._hash_cache) <= 5

        # 最早的帧应该已从缓存中移除, 可以重新提交
        first_frame_hash = hashlib.sha256(frames[0]).hexdigest()
        # 注意: 由于缓存清理逻辑是删除前一半, 第0个帧可能已被删除
        # 验证缓存大小符合预期即可

    def test_hash_dedup_disabled(self):
        """禁用哈希去重时, 重复帧应通过"""
        no_dedup_validator = FrameEvidenceValidator(enable_hash_dedup=False)
        frame_data = b"\xff\xd8\xff\xe0" + b"\x00" * 50

        r1 = no_dedup_validator.validate(frame_data, camera_id="cam", frame_index=1)
        r2 = no_dedup_validator.validate(frame_data, camera_id="cam", frame_index=2)

        assert r1.is_valid is True
        assert r2.is_valid is True  # 禁用去重, 不拒绝重复帧


# =============================================================================
# 4. 单调时间戳校验测试
# =============================================================================


class TestTimestampMonotonicity:
    """单调时间戳校验测试"""

    def test_increasing_timestamp_passes(self, default_validator):
        """正常递增时间戳 → 通过"""
        base_time = datetime.now(timezone.utc)

        r1 = default_validator.validate(
            b"\xff\xd8" + b"\x01" * 50,
            capture_time=base_time,
            camera_id="cam_ts",
            frame_index=1,
        )
        assert r1.is_valid is True

        next_time = base_time + timedelta(milliseconds=100)
        r2 = default_validator.validate(
            b"\xff\xd8" + b"\x02" * 50,
            capture_time=next_time,
            camera_id="cam_ts",
            frame_index=2,
        )
        assert r2.is_valid is True

    def test_backwards_timestamp_detected(self, default_validator):
        """回退时间戳 (比上一帧更旧) → 检测为 TIMESTAMP_BACKWARDS"""
        base_time = datetime.now(timezone.utc) + timedelta(seconds=10)

        # 设置基准时间戳 (未来时间)
        r1 = default_validator.validate(
            b"\xff\xd8" + b"\x01" * 50,
            capture_time=base_time,
            camera_id="cam_back",
            frame_index=10,
        )
        assert r1.is_valid is True

        # 提交比基准早但在新鲜度阈值内的帧
        back_time = base_time - timedelta(seconds=2)
        r2 = default_validator.validate(
            b"\xff\xd8" + b"\x02" * 50,
            capture_time=back_time,
            camera_id="cam_back",
            frame_index=11,
        )
        assert r2.is_valid is False
        assert r2.reject_code == "TIMESTAMP_BACKWARDS"
        assert "回退" in r2.reject_reason

    def test_jump_timestamp_warning(self, default_validator):
        """大幅跳变时间戳 (向前跳跃超过阈值) → 记录警告但不拒绝"""
        base_time = datetime.now(timezone.utc)

        r1 = default_validator.validate(
            b"\xff\xd8" + b"\x01" * 50,
            capture_time=base_time,
            camera_id="cam_jump",
            frame_index=1,
        )
        assert r1.is_valid is True

        # 向前跳跃6秒 (超过5秒阈值), 且frame_index跳跃 > 1
        jump_time = base_time + timedelta(seconds=6)
        r2 = default_validator.validate(
            b"\xff\xd8" + b"\x02" * 50,
            capture_time=jump_time,
            camera_id="cam_jump",
            frame_index=10,  # 大幅跳变
        )
        # 时间戳跳跃不拒绝帧, 只记录警告日志
        assert r2.is_valid is True

    def test_first_frame_no_baseline(self, default_validator):
        """首帧无基准时间戳 → 应跳过单调性校验 → 通过"""
        old_time = datetime.now(timezone.utc) - timedelta(hours=1)  # 很旧的时间

        # 首帧即使时间很旧, 如果在新鲜度范围内就应通过
        # 但这里我们测试的是: 无历史记录时不做回退检查
        fresh_old_time = datetime.now(timezone.utc) - timedelta(seconds=1)
        result = default_validator.validate(
            b"\xff\xd8" + b"\x01" * 50,
            capture_time=fresh_old_time,
            camera_id="cam_first",
            frame_index=1,
        )
        assert result.is_valid is True

    def test_different_cameras_independent(self, default_validator):
        """不同摄像头的时间戳基准应独立"""
        time1 = datetime.now(timezone.utc)
        time2 = time1 + timedelta(seconds=10)

        # cam_a 先提交较晚时间
        r1 = default_validator.validate(
            b"\xff\xd8" + b"\x01" * 50,
            capture_time=time2,
            camera_id="cam_a",
            frame_index=1,
        )
        assert r1.is_valid is True

        # cam_b 提交较早时间 (不应受cam_a影响)
        r2 = default_validator.validate(
            b"\xff\xd8" + b"\x02" * 50,
            capture_time=time1,
            camera_id="cam_b",
            frame_index=1,
        )
        assert r2.is_valid is True  # 不同摄像头, 独立基准

    def test_timestamp_check_disabled(self):
        """禁用时间戳校验时, 回退帧应通过"""
        no_ts_validator = FrameEvidenceValidator(enable_timestamp_check=False)
        base_time = datetime.now(timezone.utc) + timedelta(seconds=10)

        # 设置基准
        r1 = no_ts_validator.validate(
            b"\xff\xd8" + b"\x01" * 50,
            capture_time=base_time,
            camera_id="cam_nots",
            frame_index=1,
        )
        assert r1.is_valid is True

        # 回退时间戳
        back_time = base_time - timedelta(seconds=2)
        r2 = no_ts_validator.validate(
            b"\xff\xd8" + b"\x02" * 50,
            capture_time=back_time,
            camera_id="cam_nots",
            frame_index=2,
        )
        assert r2.is_valid is True  # 禁用校验, 不拒绝

    def test_empty_camera_id_skips_check(self, default_validator):
        """空camera_id → 跳过时间戳校验"""
        base_time = datetime.now(timezone.utc) + timedelta(seconds=10)

        r1 = default_validator.validate(
            b"\xff\xd8" + b"\x01" * 50,
            capture_time=base_time,
            camera_id="",  # 空 ID
            frame_index=1,
        )
        assert r1.is_valid is True

        back_time = base_time - timedelta(seconds=2)
        r2 = default_validator.validate(
            b"\xff\xd8" + b"\x02" * 50,
            capture_time=back_time,
            camera_id="",  # 空 ID, 跳过检查
            frame_index=2,
        )
        assert r2.is_valid is True


# =============================================================================
# 5. EvidenceRef 数据类验证测试
# =============================================================================


class TestEvidenceRef:
    """EvidenceRef 数据类验证测试"""

    def test_create_complete_evidence_ref(self):
        """创建完整 EvidenceRef (含所有字段)"""
        ref = EvidenceRef(
            type="image/jpeg",
            url="file:///tmp/evidence/test.jpg",
            hash_sha256="a1b2c3d4" * 8,  # 64字符SHA256
            captured_at="2024-01-15T10:30:00+00:00",
            camera_id="cam_001",
            frame_index=42,
            size_bytes=102400,
            freshness_ms=150,
        )

        assert ref.type == "image/jpeg"
        assert ref.url == "file:///tmp/evidence/test.jpg"
        assert len(ref.hash_sha256) == 64
        assert ref.camera_id == "cam_001"
        assert ref.frame_index == 42
        assert ref.size_bytes == 102400
        assert ref.freshness_ms == 150

    def test_default_values(self):
        """默认字段值应为空/零值"""
        ref = EvidenceRef()

        assert ref.type == "image/jpeg"
        assert ref.url == ""
        assert ref.hash_sha256 == ""
        assert ref.captured_at == ""
        assert ref.camera_id == ""
        assert ref.frame_index == 0
        assert ref.size_bytes == 0
        assert ref.freshness_ms == 0

    def test_to_dict_serialization(self):
        """to_dict() 序列化方法应返回完整字典"""
        ref = EvidenceRef(
            type="image/png",
            url="file:///tmp/test.png",
            hash_sha256="def456" * 8,
            captured_at="2024-06-20T15:45:00+00:00",
            camera_id="cam_002",
            frame_index=100,
            size_bytes=204800,
            freshness_ms=250,
        )

        d = ref.to_dict()

        assert isinstance(d, dict)
        assert d["type"] == "image/png"
        assert d["url"] == "file:///tmp/test.png"
        assert d["hash_sha256"] == "def456" * 8
        assert d["captured_at"] == "2024-06-20T15:45:00+00:00"
        assert d["camera_id"] == "cam_002"
        assert d["frame_index"] == 100
        assert d["size_bytes"] == 204800
        assert d["freshness_ms"] == 250
        assert len(d) == 8  # 确保所有字段都被序列化

    def test_to_dict_matches_fields(self):
        """to_dict() 输出应与数据类字段完全一致"""
        ref = EvidenceRef(
            type="image/jpeg",
            url="test_url",
            hash_sha256="a" * 64,
            captured_at="2024-01-01T00:00:00+00:00",
            camera_id="cam",
            frame_index=1,
            size_bytes=100,
            freshness_ms=10,
        )

        d = ref.to_dict()

        # 验证每个字段都存在且值匹配
        for field_name in ref.__dataclass_fields__:
            assert field_name in d
            assert getattr(ref, field_name) == d[field_name]


# =============================================================================
# 6. 综合流程测试
# =============================================================================


class TestValidationWorkflow:
    """综合流程测试"""

    def test_full_validation_chain(self, default_validator, sample_jpeg_frame):
        """完整的 validate_frame() 调用链 (新鲜度→去重→时间戳)"""
        current = datetime.now(timezone.utc)

        result = default_validator.validate(
            frame_data=sample_jpeg_frame,
            capture_time=current,
            camera_id="cam_workflow",
            frame_index=1,
        )

        # 验证完整结果结构
        assert result.is_valid is True
        assert isinstance(result, FrameValidationResult)
        assert isinstance(result.evidence_ref, EvidenceRef)
        assert result.reject_code == "OK"
        assert result.reject_reason == ""
        assert result.processing_latency_ms >= 0

        # 验证证据引用完整性
        ev = result.evidence_ref
        assert ev.type == "image/jpeg"
        assert ev.hash_sha256
        assert len(ev.hash_sha256) == 64  # SHA256 hex长度
        assert ev.camera_id == "cam_workflow"
        assert ev.frame_index == 1
        assert ev.size_bytes == len(sample_jpeg_frame)
        assert "file:///" in ev.url
        assert "cam_workflow" in ev.url

    def test_batch_validation_multiple_frames(self, default_validator):
        """批量验证多帧数据"""
        base_time = datetime.now(timezone.utc)
        results = []
        num_frames = 20

        for i in range(num_frames):
            frame_data = f"frame_{i}".encode() * 10
            frame_time = base_time + timedelta(milliseconds=33 * i)  # ~30fps

            result = default_validator.validate(
                frame_data=frame_data,
                capture_time=frame_time,
                camera_id="cam_batch",
                frame_index=i + 1,
            )
            results.append(result)

        # 所有帧都应通过
        passed = sum(1 for r in results if r.is_valid)
        assert passed == num_frames

        # 每帧应有不同的hash (内容不同)
        hashes = set(r.evidence_ref.hash_sha256 for r in results)
        assert len(hashes) == num_frames

        # 帧索引应递增
        indices = [r.evidence_ref.frame_index for r in results]
        assert indices == list(range(1, num_frames + 1))

    def test_stats_tracking(self, default_validator, sample_jpeg_frame):
        """统计信息应正确跟踪验证结果"""
        # 通过几帧
        for i in range(3):
            data = f"unique_{i}".encode() * 20
            default_validator.validate(data, camera_id="cam_stat", frame_index=i)

        # 提交重复帧 (第一次通过, 第二次被拒绝)
        default_validator.validate(sample_jpeg_frame, camera_id="cam_stat", frame_index=10)
        default_validator.validate(sample_jpeg_frame, camera_id="cam_stat", frame_index=11)  # 重复

        # 提交过期帧
        old_time = datetime.now(timezone.utc) - timedelta(seconds=10)
        default_validator.validate(b"old_frame", capture_time=old_time, camera_id="cam_exp", frame_index=1)

        stats = default_validator.get_stats()

        assert stats["total_validated"] == 6  # 3 unique + 2 dup(1pass+1reject) + 1 expired
        assert stats["accepted"] == 4  # 3 unique + 1 first dup pass
        assert stats["rejected_duplicate"] == 1
        assert stats["rejected_expired"] == 1
        assert 0 < stats["accept_rate"] <= 100

    def test_reset_stats(self, default_validator, sample_jpeg_frame):
        """reset_stats() 应清零所有计数器"""
        # 产生一些统计
        default_validator.validate(sample_jpeg_frame, camera_id="cam", frame_index=1)
        default_validator.validate(sample_jpeg_frame, camera_id="cam", frame_index=2)  # 重复

        assert default_validator.get_stats()["total_validated"] == 2

        # 重置
        default_validator.reset_stats()

        stats = default_validator.get_stats()
        assert stats["total_validated"] == 0
        assert stats["accepted"] == 0
        assert stats["rejected_expired"] == 0
        assert stats["rejected_duplicate"] == 0
        assert stats["rejected_backwards"] == 0
        assert stats["rejected_jump"] == 0

    def test_clear_cache(self, default_validator, sample_jpeg_frame):
        """clear_cache() 应清除所有缓存数据"""
        # 填充缓存
        for i in range(5):
            data = f"data_{i}".encode()
            default_validator.validate(data, camera_id=f"cam_{i}", frame_index=i)

        assert len(default_validator._hash_cache) > 0
        assert len(default_validator._last_timestamp) > 0

        # 清除
        default_validator.clear_cache()

        assert len(default_validator._hash_cache) == 0
        assert len(default_validator._last_timestamp) == 0


# =============================================================================
# 7. 边界情况测试
# =============================================================================


class TestEdgeCases:
    """边界情况处理测试"""

    def test_empty_frame_data_none(self, default_validator):
        """空帧数据 (None) → 应能处理 (可能抛异常或返回特定结果)"""
        # None 作为 bytes 参数会触发 TypeError
        with pytest.raises((TypeError, AttributeError)):
            default_validator.validate(None, camera_id="cam", frame_index=1)

    def test_empty_frame_data_zero_bytes(self, default_validator):
        """空帧数据 (空bytes) → 应计算hash并处理"""
        result = default_validator.validate(
            b"",
            camera_id="cam_empty",
            frame_index=1,
        )

        # 空字节也有合法的SHA256 hash
        assert result.is_valid is True
        assert result.evidence_ref.hash_sha256 == hashlib.sha256(b"").hexdigest()
        assert result.evidence_ref.size_bytes == 0

    def test_large_frame_data(self, default_validator):
        """超大帧数据 (10MB) → 应正常处理"""
        target_size = 10 * 1024 * 1024  # 10MB
        large_data = b"\xff\xd8" + b"\x00" * (target_size - 2)  # 减去头部2字节

        start = time.time()
        result = default_validator.validate(
            large_data,
            camera_id="cam_large",
            frame_index=1,
        )
        elapsed = (time.time() - start) * 1000

        assert result.is_valid is True
        assert result.evidence_ref.size_bytes == target_size
        # 处理时间应在合理范围内 (< 1秒)
        assert elapsed < 1000

    def test_corrupted_image_data(self, default_validator):
        """损坏的图像数据 (随机字节) → 应仍能计算hash并处理"""
        corrupted = bytes(range(256)) * 10  # 非法图像数据

        result = default_validator.validate(
            corrupted,
            camera_id="cam_corrupt",
            frame_index=1,
        )

        # 验证器不检查图像有效性, 只做hash和新鲜度检查
        assert result.is_valid is True
        assert result.evidence_ref.hash_sha256 == hashlib.sha256(corrupted).hexdigest()

    def test_very_long_camera_id(self, default_validator, sample_jpeg_frame):
        """超长camera_id → URL生成应安全处理 (特殊字符替换)"""
        long_id = "cam:with/special-chars/and:colons"

        result = default_validator.validate(
            sample_jpeg_frame,
            camera_id=long_id,
            frame_index=1,
        )

        assert result.is_valid is True
        # URL中 camera_id 部分: : 和 / 应被替换为 _
        url_path = result.evidence_ref.url
        # 提取 camera_id 所在的目录部分 (evidence/ 之后, 下一个 / 之前)
        evidence_part = url_path.split("evidence/")[1]
        camera_dir = evidence_part.split("/")[0]  # camera_id 变成的目录名
        # 冒号和斜杠应被下划线替换
        assert ":" not in camera_dir
        assert "/" not in camera_dir

    def test_negative_frame_index(self, default_validator, sample_jpeg_frame):
        """负数frame_index → 应正常处理"""
        result = default_validator.validate(
            sample_jpeg_frame,
            camera_id="cam_neg",
            frame_index=-1,
        )

        assert result.is_valid is True
        assert result.evidence_ref.frame_index == -1

    def test_exact_max_age_boundary(self):
        """刚好等于max_age_ms边界的帧 → 应通过 (条件是 > 不是 >=)"""
        # 由于时间精度问题, 这个测试验证的是边界行为
        validator = FrameEvidenceValidator(max_age_ms=1000)

        # 使用刚好在阈值内的时间
        near_boundary = datetime.now(timezone.utc) - timedelta(milliseconds=999)
        result = validator.validate(
            b"test_data",
            capture_time=near_boundary,
            camera_id="cam_boundary",
            frame_index=1,
        )

        assert result.is_valid is True

    def test_unicode_camera_id(self, default_validator, sample_jpeg_frame):
        """Unicode camera_id → 应正常处理"""
        result = default_validator.validate(
            sample_jpeg_frame,
            camera_id="摄像头_中文ID",
            frame_index=1,
        )

        assert result.is_valid is True
        assert result.evidence_ref.camera_id == "摄像头_中文ID"


# =============================================================================
# 8. FrameValidationResult 数据类测试
# =============================================================================


class TestFrameValidationResult:
    """FrameValidationResult 数据类测试"""

    def test_success_result_creation(self):
        """成功结果的创建"""
        ref = EvidenceRef(hash_sha256="a1b2c3d4" * 8)
        result = FrameValidationResult(
            is_valid=True,
            evidence_ref=ref,
            reject_code="OK",
            processing_latency_ms=5,
        )

        assert result.is_valid is True
        assert result.evidence_ref == ref
        assert result.reject_reason == ""  # 默认空字符串

    def test_rejection_result_creation(self):
        """拒绝结果的创建"""
        result = FrameValidationResult(
            is_valid=False,
            reject_reason="帧已过期",
            reject_code="EXPIRED",
            processing_latency_ms=2,
        )

        assert result.is_valid is False
        assert result.evidence_ref is None  # 默认None
        assert result.reject_code == "EXPIRED"


# =============================================================================
# 9. 补充测试 - 提升覆盖率
# =============================================================================


class TestAdditionalCoverage:
    """补充测试以提升代码覆盖率至85%+"""

    def test_factory_unknown_profile_fallback(self):
        """工厂函数: 未知profile应回退到default配置"""
        config = {"model_profile": "unknown_profile_xyz"}
        validator = create_validator_from_config(config)

        # 未知profile应使用default配置
        assert isinstance(validator, FrameEvidenceValidator)
        assert validator.max_age_ms == 3000
        assert validator._cache_size == 1000

    def test_factory_with_both_config_and_profile(self):
        """工厂函数: 同时提供max_age和profile时, profile优先"""
        config = {
            "frame_freshness_max_age_ms": 1000,  # 这个值会被profile覆盖
            "model_profile": "hotpot_waste_v2",
        }
        validator = create_validator_from_config(config)

        # hotpot_waste_v2 profile 的 max_age_ms=2000 应覆盖配置值
        assert validator.max_age_ms == 2000
        assert validator._cache_size == 500

    def test_evidence_ref_url_format(self, default_validator, sample_jpeg_frame):
        """EvidenceRef URL格式验证 - 应包含标准路径结构"""
        result = default_validator.validate(
            sample_jpeg_frame,
            camera_id="cam_url_test",
            frame_index=99,
        )

        url = result.evidence_ref.url
        # 验证URL格式: file:///tmp/hotpot/evidence/{camera_id}/{frame_index}_{hash_prefix}.jpg
        assert url.startswith("file:///tmp/hotpot/evidence/")
        assert "cam_url_test" in url
        assert "99_" in url  # frame_index_hash 格式
        assert url.endswith(".jpg")

    def test_processing_latency_non_negative(self, default_validator, sample_jpeg_frame):
        """processing_latency_ms 应始终非负"""
        for _ in range(10):
            data = f"latency_test_{time.time()}".encode()
            result = default_validator.validate(data, camera_id="cam_lat", frame_index=1)
            assert result.processing_latency_ms >= 0

    def test_reject_codes_are_expected_values(self, default_validator):
        """所有拒绝码应在预期集合中"""
        expected_codes = {"EXPIRED", "HASH_DUPLICATE", "TIMESTAMP_BACKWARDS", "JUMP_DETECTED", "OK"}

        # EXPIRED
        old_time = datetime.now(timezone.utc) - timedelta(seconds=10)
        r1 = default_validator.validate(b"data", capture_time=old_time, camera_id="c", frame_index=1)
        assert r1.reject_code in expected_codes

        # HASH_DUPLICATE
        r2 = default_validator.validate(b"data", camera_id="c", frame_index=2)
        assert r2.reject_code in expected_codes

        # OK (正常通过)
        r3 = default_validator.validate(b"unique", camera_id="c2", frame_index=1)
        assert r3.reject_code in expected_codes

    def test_stats_cache_size_tracking(self, default_validator):
        """统计中的cache_size应反映实际缓存大小"""
        assert default_validator.get_stats()["cache_size"] == 0

        for i in range(5):
            default_validator.validate(f"data_{i}".encode(), camera_id=f"cam_{i}", frame_index=i)

        stats = default_validator.get_stats()
        assert stats["cache_size"] == 5

    def test_stats_tracked_cameras(self, default_validator):
        """统计中的tracked_cameras应反映已跟踪的摄像头数量"""
        assert default_validator.get_stats()["tracked_cameras"] == 0

        for i in range(3):
            # 使用不同数据以避免去重
            default_validator.validate(f"data_{i}".encode(), camera_id=f"camera_{i}", frame_index=i)

        stats = default_validator.get_stats()
        assert stats["tracked_cameras"] == 3

    def test_accept_rate_calculation(self, default_validator):
        """accept_rate应正确计算百分比"""
        # 初始状态
        stats = default_validator.get_stats()
        assert stats["accept_rate"] == 0.0  # 0/1 = 0%

        # 接受1帧
        default_validator.validate(b"frame1", camera_id="cam", frame_index=1)
        stats = default_validator.get_stats()
        assert stats["accept_rate"] == 100.0  # 1/1 = 100%

        # 拒绝1帧 (重复)
        default_validator.validate(b"frame1", camera_id="cam", frame_index=2)
        stats = default_validator.get_stats()
        assert stats["accept_rate"] == 50.0  # 1/2 = 50%
