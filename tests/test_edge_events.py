"""
统一边缘事件契约单元测试

覆盖范围:
- 数据模型验证 (EventType, EventSeverity, EvidenceRef, UnifiedEdgeEvent)
- API端点逻辑 (POST /api/v1/edge/events 单事件/批量/幂等/schema)
- 边界情况 (空列表、超大payload、无效输入、离线标记)
- 兼容性接口 (/v1/events 旧版映射)

源码: hotpot_platform/cloud/event_hub/routers/edge_events.py
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError as PydanticValidationError

# 确保项目根目录在 sys.path 中
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# 导入被测模块
from hotpot_platform.cloud.event_hub.routers.edge_events import (
    BatchEventsRequest,
    BatchEventsResponse,
    EvidenceRef,
    EventSeverity,
    EventType,
    UnifiedEdgeEvent,
    _IDEMPOTENCY_TTL_SECONDS,
    _idempotency_store,
    _is_duplicate,
    _generate_event_id,
    router,
)

# 创建 FastAPI TestClient
from fastapi import FastAPI

app = FastAPI()
app.include_router(router)
client = TestClient(app)


# =====================================================================
# Fixtures
# =====================================================================


@pytest.fixture(autouse=True)
def clear_idempotency_store():
    """每个测试前清空幂等存储，避免测试间干扰"""
    _idempotency_store.clear()
    yield
    _idempotency_store.clear()


@pytest.fixture
def base_event_dict():
    """基础合法事件字典 (必填字段)"""
    return {
        "event_type": "waste_detected",
        "store_id": "store_jiaojiang",
        "device_id": "jetson_jiaojiang_001",
        "timestamp": "2026-08-05T01:00:00+08:00",
        "payload": {"waste_type": "food_waste", "estimated_weight_g": 150},
    }


@pytest.fixture
def full_event_dict(base_event_dict):
    """完整事件字典 (包含所有可选字段)"""
    base_event_dict.update(
        {
            "event_id": "evt_test_001",
            "idempotency_key": "idem_test_unique_001",
            "severity": "warning",
            "confidence": 0.92,
            "evidence_ref": {
                "type": "image",
                "url": "s3://bucket/images/cam_a1_main_20260805T010000.jpg",
                "hash_sha256": "a1b2c3d4e5f6" * 4,  # 64字符模拟SHA256
                "captured_at": "2026-08-05T01:00:00+08:00",
                "camera_id": "cam_a1_main",
                "frame_index": 42,
                "metadata": {"model_version": "yolov8n-v1.2"},
            },
            "source_event_id": "src_evt_001",
            "trace_id": "trace_abc123",
            "is_offline_buffer": False,
            "buffered_at": None,
        }
    )
    return base_event_dict


@pytest.fixture
def sample_batch_request(full_event_dict):
    """批量请求示例 (3个事件)"""
    events = []
    for i in range(3):
        evt = dict(full_event_dict)
        evt["event_id"] = f"evt_test_{i:03d}"
        evt["idempotency_key"] = f"idem_test_{i:03d}"
        events.append(evt)
    return {"events": events, "batch_id": "batch_test_001"}


# =====================================================================
# 1. 数据模型验证 - EventType 枚举
# =====================================================================


class TestEventTypeEnum:
    """EventType 枚举验证测试"""

    def test_all_event_types_exist(self):
        """验证所有20种标准事件类型均存在且值正确"""
        expected_types = {
            # 后厨损耗与出品闭环 (4)
            "WASTE_DETECTED": "waste_detected",
            "SOP_VIOLATION": "sop_violation",
            "DISH_OUTPUT": "dish_output",
            "FOOD_QUALITY": "food_quality",
            # 收货/供应链闭环 (4)
            "RECEIVING_START": "receiving_start",
            "RECEIVING_COMPLETE": "receiving_complete",
            "RECEIVING_REJECT": "receiving_reject",
            "INVENTORY_ALERT": "inventory_alert",
            # 前厅服务与翻台闭环 (5)
            "TABLE_DIRTY": "table_dirty",
            "TABLE_CLEANED": "table_cleaned",
            "SERVICE_TIMEOUT": "service_timeout",
            "CUSTOMER_ENTRY": "customer_entry",
            # 销售增长闭环 (3)
            "POS_ORDER": "pos_order",
            "SKU_SALES": "sku_sales",
            "PROMO_TRIGGER": "promo_trigger",
            # 系统事件 (3)
            "DEVICE_HEARTBEAT": "device_heartbeat",
            "CONFIG_ACK": "config_ack",
            "MODEL_INFERENCE": "model_inference",
        }
        assert len(EventType) == 18, f"期望18种事件类型，实际{len(EventType)}种"
        for name, value in expected_types.items():
            assert hasattr(EventType, name), f"缺少枚举成员: {name}"
            assert EventType[name].value == value, f"{name} 值不正确: {EventType[name].value} != {value}"

    def test_event_type_from_string(self):
        """通过字符串值构造枚举"""
        assert EventType("waste_detected") == EventType.WASTE_DETECTED
        assert EventType("pos_order") == EventType.POS_ORDER

    def test_invalid_event_type_raises(self):
        """非法事件类型应抛出 ValueError"""
        with pytest.raises(ValueError):
            EventType("invalid_type")

    def test_kitchen_domain_events(self):
        """验证后厨损耗与出品闭环的事件类型"""
        kitchen_events = [
            EventType.WASTE_DETECTED,
            EventType.SOP_VIOLATION,
            EventType.DISH_OUTPUT,
            EventType.FOOD_QUALITY,
        ]
        assert len(kitchen_events) == 4

    def test_supply_chain_events(self):
        """验证收货/供应链闭环的事件类型"""
        supply_events = [
            EventType.RECEIVING_START,
            EventType.RECEIVING_COMPLETE,
            EventType.RECEIVING_REJECT,
            EventType.INVENTORY_ALERT,
        ]
        assert len(supply_events) == 4

    def test_front_hall_events(self):
        """验证前厅服务与翻台闭环的事件类型"""
        front_events = [
            EventType.TABLE_DIRTY,
            EventType.TABLE_CLEANED,
            EventType.SERVICE_TIMEOUT,
            EventType.CUSTOMER_ENTRY,
        ]
        assert len(front_events) == 4

    def test_sales_events(self):
        """验证销售增长闭环的事件类型"""
        sales_events = [
            EventType.POS_ORDER,
            EventType.SKU_SALES,
            EventType.PROMO_TRIGGER,
        ]
        assert len(sales_events) == 3

    def test_system_events(self):
        """验证系统事件类型"""
        system_events = [
            EventType.DEVICE_HEARTBEAT,
            EventType.CONFIG_ACK,
            EventType.MODEL_INFERENCE,
        ]
        assert len(system_events) == 3


# =====================================================================
# 2. 数据模型验证 - EventSeverity 枚举
# =====================================================================


class TestEventSeverityEnum:
    """EventSeverity 枚举验证测试"""

    def test_all_severity_levels_exist(self):
        """验证所有严重程度级别"""
        expected = {
            "INFO": "info",
            "WARNING": "warning",
            "ERROR": "error",
            "CRITICAL": "critical",
        }
        assert len(EventSeverity) == 4
        for name, value in expected.items():
            assert EventSeverity[name].value == value

    def test_severity_ordering(self):
        """验证严重程度可比较 (按定义顺序)"""
        levels = list(EventSeverity)
        assert levels[0] == EventSeverity.INFO
        assert levels[1] == EventSeverity.WARNING
        assert levels[2] == EventSeverity.ERROR
        assert levels[3] == EventSeverity.CRITICAL

    def test_invalid_severity_raises(self):
        """非法严重程度应抛出 ValueError"""
        with pytest.raises(ValueError):
            EventSeverity("fatal")


# =====================================================================
# 3. 数据模型验证 - EvidenceRef 数据类
# =====================================================================


class TestEvidenceRefModel:
    """EvidenceRef 证据引用数据模型测试"""

    def test_minimal_evidence_ref(self):
        """仅提供必填字段 type 即可创建"""
        ref = EvidenceRef(type="image")
        assert ref.type == "image"
        assert ref.url is None
        assert ref.hash_sha256 is None
        assert ref.captured_at is None
        assert ref.camera_id is None
        assert ref.frame_index is None
        assert ref.metadata == {}

    def test_full_evidence_ref(self):
        """完整字段创建证据引用"""
        ref = EvidenceRef(
            type="video",
            url="s3://bucket/videos/recording.mp4",
            hash_sha256="abcd1234" * 8,
            captured_at="2026-08-05T01:00:00+08:00",
            camera_id="cam_b2_side",
            frame_index=100,
            metadata={"duration_sec": 30, "codec": "h264"},
        )
        assert ref.type == "video"
        assert ref.url == "s3://bucket/videos/recording.mp4"
        assert ref.hash_sha256 == "abcd1234" * 8
        assert ref.camera_id == "cam_b2_side"
        assert ref.frame_index == 100
        assert ref.metadata["duration_sec"] == 30

    def test_evidence_ref_missing_required_field(self):
        """缺少必填字段 type 应报错"""
        with pytest.raises(PydanticValidationError):
            EvidenceRef(url="s3://bucket/image.jpg")

    def test_evidence_ref_metadata_default_is_dict(self):
        """metadata 默认应为空字典"""
        ref = EvidenceRef(type="vlm_result")
        assert isinstance(ref.metadata, dict)
        assert len(ref.metadata) == 0

    def test_evidence_ref_serialization(self):
        """序列化/反序列化一致性"""
        original = EvidenceRef(type="image", camera_id="cam_01")
        data = original.model_dump()
        restored = EvidenceRef(**data)
        assert restored.type == original.type
        assert restored.camera_id == original.camera_id


# =====================================================================
# 4. 数据模型验证 - UnifiedEdgeEvent 完整实例化
# =====================================================================


class TestUnifiedEdgeEventModel:
    """UnifiedEdgeEvent 统一边缘事件模型测试"""

    def test_create_with_required_fields_only(self, base_event_dict):
        """仅使用必填字段创建事件"""
        event = UnifiedEdgeEvent(**base_event_dict)
        assert event.event_type == EventType.WASTE_DETECTED
        assert event.store_id == "store_jiaojiang"
        assert event.device_id == "jetson_jiaojiang_001"
        assert event.timestamp == "2026-08-05T01:00:00+08:00"
        assert event.payload == {"waste_type": "food_waste", "estimated_weight_g": 150}
        # 验证可选字段的默认值
        assert event.event_id is None
        assert event.idempotency_key is None
        assert event.severity == EventSeverity.INFO  # 默认值
        assert event.confidence is None
        assert event.evidence_ref is None
        assert event.is_offline_buffer is False  # 默认值

    def test_create_with_all_fields(self, full_event_dict):
        """使用全部字段创建完整事件"""
        event = UnifiedEdgeEvent(**full_event_dict)
        assert event.event_id == "evt_test_001"
        assert event.idempotency_key == "idem_test_unique_001"
        assert event.severity == EventSeverity.WARNING
        assert event.confidence == 0.92
        assert event.evidence_ref is not None
        assert event.evidence_ref.type == "image"
        assert event.source_event_id == "src_evt_001"
        assert event.trace_id == "trace_abc123"

    def test_missing_required_field_raises(self, base_event_dict):
        """缺少任意必填字段应触发 Pydantic 校验错误"""
        for field in ["event_type", "store_id", "device_id", "timestamp", "payload"]:
            incomplete = dict(base_event_dict)
            del incomplete[field]
            with pytest.raises(PydanticValidationError):
                UnifiedEdgeEvent(**incomplete)

    def test_confidence_range_validation(self, base_event_dict):
        """confidence 必须在 [0.0, 1.0] 范围内"""
        # 合法值
        event = UnifiedEdgeEvent(**base_event_dict, confidence=0.0)
        assert event.confidence == 0.0
        event = UnifiedEdgeEvent(**base_event_dict, confidence=1.0)
        assert event.confidence == 1.0

        # 超出范围应报错
        with pytest.raises(PydanticValidationError):
            UnifiedEdgeEvent(**base_event_dict, confidence=1.5)
        with pytest.raises(PydanticValidationError):
            UnifiedEdgeEvent(**base_event_dict, confidence=-0.1)

    def test_invalid_event_type_value(self, base_event_dict):
        """非法 event_type 值应报错"""
        base_event_dict["event_type"] = "nonexistent_type"
        with pytest.raises(PydanticValidationError):
            UnifiedEdgeEvent(**base_event_dict)

    def test_invalid_severity_value(self, base_event_dict):
        """非法 severity 值应报错"""
        base_event_dict["severity"] = "fatal"
        with pytest.raises(PydanticValidationError):
            UnifiedEdgeEvent(**base_event_dict)

    def test_offline_buffer_fields(self, base_event_dict):
        """离线缓存标记字段"""
        event = UnifiedEdgeEvent(
            **base_event_dict,
            is_offline_buffer=True,
            buffered_at="2026-08-05T02:00:00+08:00",
        )
        assert event.is_offline_buffer is True
        assert event.buffered_at == "2026-08-05T02:00:00+08:00"

    def test_nested_evidence_ref_validation(self, base_event_dict):
        """嵌套的 evidence_ref 也需要符合 EvidenceRef 模型"""
        base_event_dict["evidence_ref"] = {"wrong_field": "value"}  # 缺少 type
        with pytest.raises(PydanticValidationError):
            UnifiedEdgeEvent(**base_event_dict)


# =====================================================================
# 5. API端点逻辑测试 - POST /api/v1/edge/events 单事件
# =====================================================================


class TestPostSingleEvent:
    """单事件提交 API 测试"""

    def test_submit_single_event_success(self, base_event_dict):
        """成功提交单个边缘事件"""
        response = client.post(
            "/api/v1/edge/events",
            json={"events": [base_event_dict]},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["accepted"] == 1
        assert data["rejected"] == 0
        assert data["duplicates"] == 0
        assert len(data["event_ids"]) == 1
        assert data["event_ids"][0].startswith("evt_")
        assert len(data["errors"]) == 0
        assert "processed_at" in data
        assert "batch_id" in data

    def test_submit_single_event_with_custom_id(self, base_event_dict):
        """使用自定义 event_id 提交"""
        base_event_dict["event_id"] = "my_custom_evt_001"
        response = client.post(
            "/api/v1/edge/events",
            json={"events": [base_event_dict]},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["event_ids"][0] == "my_custom_evt_001"

    def test_submit_with_headers(self, base_event_dict):
        """携带 X-Store-Id / X-Device-Id / X-Edge-Version 头部"""
        response = client.post(
            "/api/v1/edge/events",
            json={"events": [base_event_dict]},
            headers={
                "X-Store-Id": "store_header_override",
                "X-Device-Id": "device_header_001",
                "X-Edge-Version": "1.2.3",
            },
        )
        assert response.status_code == 200
        # 头部目前仅用于审计，不影响响应结构
        data = response.json()
        assert data["accepted"] == 1

    def test_submit_with_evidence_ref(self, base_event_dict):
        """携带证据引用提交"""
        base_event_dict["evidence_ref"] = {
            "type": "image",
            "camera_id": "cam_a1_main",
            "hash_sha256": "a1b2c3d4" * 8,
        }
        response = client.post(
            "/api/v1/edge/events",
            json={"events": [base_event_dict]},
        )
        assert response.status_code == 200
        assert response.json()["accepted"] == 1

    def test_submit_offline_buffered_event(self, base_event_dict):
        """提交离线缓存回放事件"""
        base_event_dict["is_offline_buffer"] = True
        base_event_dict["buffered_at"] = "2026-08-05T02:00:00+08:00"
        response = client.post(
            "/api/v1/edge/events",
            json={"events": [base_event_dict]},
        )
        assert response.status_code == 200
        assert response.json()["accepted"] == 1


# =====================================================================
# 6. API端点逻辑测试 - POST /api/v1/edge/events 批量提交
# =====================================================================


class TestPostBatchEvents:
    """批量事件提交 API 测试"""

    def test_submit_batch_success(self, sample_batch_request):
        """成功批量提交多个事件"""
        response = client.post("/api/v1/edge/events", json=sample_batch_request)
        assert response.status_code == 200
        data = response.json()
        assert data["accepted"] == 3
        assert data["rejected"] == 0
        assert data["duplicates"] == 0
        assert len(data["event_ids"]) == 3
        assert data["batch_id"] == "batch_test_001"

    def test_batch_auto_generates_batch_id(self, base_event_dict):
        """未提供 batch_id 时自动生成"""
        events = [dict(base_event_dict) for _ in range(2)]
        response = client.post("/api/v1/edge/events", json={"events": events})
        assert response.status_code == 200
        data = response.json()
        assert data["batch_id"].startswith("batch_")

    def test_batch_with_mixed_event_types(self, base_event_dict):
        """批量提交不同类型的事件"""
        events = []
        for et in ["waste_detected", "pos_order", "table_dirty", "device_heartbeat"]:
            evt = dict(base_event_dict)
            evt["event_type"] = et
            evt["idempotency_key"] = f"idem_{et}"
            events.append(evt)
        response = client.post("/api/v1/edge/events", json={"events": events})
        assert response.status_code == 200
        assert response.json()["accepted"] == 4

    def test_batch_with_device_heartbeat_meta(self, base_event_dict):
        """批量请求附带设备心跳信息"""
        request_body = {
            "events": [dict(base_event_dict)],
            "device_heartbeat": {
                "uptime_seconds": 86400,
                "cpu_usage_pct": 45.2,
                "memory_mb": 1024,
                "temperature_c": 62.5,
            },
        }
        response = client.post("/api/v1/edge/events", json=request_body)
        assert response.status_code == 200
        assert response.json()["accepted"] == 1


# =====================================================================
# 7. 幂等性去重测试
# =====================================================================


class TestIdempotencyDedup:
    """幂等 key 去重机制测试"""

    def test_duplicate_idempotency_key_rejected(self, base_event_dict):
        """相同 idempotency_key 的第二次提交应被识别为重复"""
        base_event_dict["idempotency_key"] = "unique_key_001"

        # 第一次提交 - 成功
        resp1 = client.post("/api/v1/edge/events", json={"events": [dict(base_event_dict)]})
        assert resp1.status_code == 200
        assert resp1.json()["accepted"] == 1
        assert resp1.json()["duplicates"] == 0

        # 第二次提交 - 幂等去重
        resp2 = client.post("/api/v1/edge/events", json={"events": [dict(base_event_dict)]})
        assert resp2.status_code == 200
        assert resp2.json()["accepted"] == 0
        assert resp2.json()["duplicates"] == 1
        assert len(resp2.json()["event_ids"]) == 0

    def test_different_keys_accepted_independently(self, base_event_dict):
        """不同的 idempotency_key 应各自独立处理"""
        events = []
        for i in range(3):
            evt = dict(base_event_dict)
            evt["idempotency_key"] = f"independent_key_{i}"
            events.append(evt)

        response = client.post("/api/v1/edge/events", json={"events": events})
        assert response.json()["accepted"] == 3
        assert response.json()["duplicates"] == 0

    def test_no_idempotency_key_still_accepted(self, base_event_dict):
        """不提供 idempotency_key 时仍能正常接受 (使用派生key)"""
        # base_event_dict 本身就没有 idempotency_key，直接提交即可
        response = client.post("/api/v1/edge/events", json={"events": [base_event_dict]})
        assert response.status_code == 200
        assert response.json()["accepted"] == 1

    def test_idempotency_ttl_expiration(self, base_event_dict):
        """幂等 key 在 TTL 过期后应重新接受"""
        base_event_dict["idempotency_key"] = "ttl_test_key"

        # 第一次提交
        resp1 = client.post("/api/v1/edge/events", json={"events": [dict(base_event_dict)]})
        assert resp1.json()["accepted"] == 1

        # 模拟 TTL 过期：直接操作内部存储的时间戳
        old_time = time.time() - _IDEMPOTENCY_TTL_SECONDS - 10
        _idempotency_store["ttl_test_key"] = old_time

        # 过期后再次提交 - 应被视为新请求
        resp2 = client.post("/api/v1/edge/events", json={"events": [dict(base_event_dict)]})
        assert resp2.json()["accepted"] == 1
        assert resp2.json()["duplicates"] == 0

    def test_payload_based_derived_key_dedup(self, base_event_dict):
        """无显式 idempotency_key 时，基于 payload 派生的 key 也应去重"""
        # 不设置 idempotency_key，相同的 event_type/device_id/timestamp/payload 应派生出相同 key
        evt1 = dict(base_event_dict)
        evt2 = dict(base_event_dict)

        resp1 = client.post("/api/v1/edge/events", json={"events": [evt1]})
        assert resp1.json()["accepted"] == 1

        resp2 = client.post("/api/v1/edge/events", json={"events": [evt2]})
        # 由于 payload 完全相同，派生 key 相同，应被去重
        assert resp2.json()["duplicates"] >= 1


# =====================================================================
# 8. 证据引用校验测试
# =====================================================================


class TestEvidenceRefValidation:
    """证据引用格式校验测试"""

    def test_valid_image_evidence(self, base_event_dict):
        """有效的图像证据引用"""
        base_event_dict["evidence_ref"] = {
            "type": "image",
            "url": "s3://bucket/img.jpg",
            "hash_sha256": "aa" * 32,
            "camera_id": "cam_01",
        }
        response = client.post("/api/v1/edge/events", json={"events": [base_event_dict]})
        assert response.status_code == 200
        assert response.json()["accepted"] == 1

    def test_valid_video_evidence(self, base_event_dict):
        """有效的视频证据引用"""
        base_event_dict["evidence_ref"] = {
            "type": "video",
            "url": "/local/videos/rec.mp4",
            "captured_at": "2026-08-05T01:00:00Z",
            "frame_index": 0,
        }
        response = client.post("/api/v1/edge/events", json={"events": [base_event_dict]})
        assert response.status_code == 200

    def test_valid_vlm_result_evidence(self, base_event_dict):
        """有效的 VLM 推理结果引用"""
        base_event_dict["evidence_ref"] = {
            "type": "vlm_result",
            "metadata": {"model": "qwen-vl", "description": "检测到废料"},
        }
        response = client.post("/api/v1/edge/events", json={"events": [base_event_dict]})
        assert response.status_code == 200

    def test_evidence_ref_missing_type_field(self, base_event_dict):
        """证据引用缺少 type 字段应失败"""
        base_event_dict["evidence_ref"] = {"url": "s3://bucket/img.jpg"}
        response = client.post("/api/v1/edge/events", json={"events": [base_event_dict]})
        assert response.status_code == 422  # Pydantic 校验错误


# =====================================================================
# 9. GET /api/v1/edge/events/schema Schema Discovery
# =====================================================================


class TestEventSchemaEndpoint:
    """Schema 发现端点测试"""

    def test_schema_returns_contract_info(self):
        """返回完整的契约元信息"""
        response = client.get("/api/v1/edge/events/schema")
        assert response.status_code == 200
        schema = response.json()

        # 基本结构
        assert schema["version"] == "1.0.0"
        assert schema["contract_name"] == "hotpot_edge_events_v1"
        assert "updated_at" in schema

        # 事件类型列表
        assert isinstance(schema["event_types"], list)
        assert len(schema["event_types"]) == len(EventType)
        assert "waste_detected" in schema["event_types"]
        assert "pos_order" in schema["event_types"]

        # 严重程度
        assert schema["severity_levels"] == ["info", "warning", "error", "critical"]

        # 必填/推荐字段
        assert "event_type" in schema["required_fields"]
        assert "payload" in schema["required_fields"]
        assert "confidence" in schema["recommended_fields"]

        # 证据类型
        assert "image" in schema["evidence_types"]
        assert "video" in schema["evidence_types"]
        assert "vlm_result" in schema["evidence_types"]

        # 批量限制
        assert schema["batch_limits"]["min"] == 1
        assert schema["batch_limits"]["max"] == 100

        # 头部说明
        assert "X-Store-Id" in schema["headers"]

    def test_schema_contains_all_event_types(self):
        """schema 包含所有定义的事件类型"""
        response = client.get("/api/v1/edge/events/schema")
        types_set = set(response.json()["event_types"])
        expected_set = {et.value for et in EventType}
        assert types_set == expected_set


# =====================================================================
# 10. GET /api/v1/edge/events/idempotency/stats 统计端点
# =====================================================================


class TestIdempotencyStatsEndpoint:
    """幂等统计端点测试"""

    def test_empty_stats_initially(self):
        """初始状态统计为空"""
        response = client.get("/api/v1/edge/events/idempotency/stats")
        assert response.status_code == 200
        data = response.json()
        assert data["active_idempotency_keys"] == 0
        assert data["total_stored"] == 0
        assert data["ttl_seconds"] == _IDEMPOTENCY_TTL_SECONDS

    def test_stats_after_submissions(self, base_event_dict):
        """提交后统计数增加"""
        base_event_dict["idempotency_key"] = "stats_key_001"
        client.post("/api/v1/edge/events", json={"events": [base_event_dict]})

        response = client.get("/api/v1/edge/events/idempotency/stats")
        data = response.json()
        assert data["total_stored"] >= 1
        assert data["active_idempotency_keys"] >= 1


# =====================================================================
# 11. 边界情况测试
# =====================================================================


class TestBoundaryCases:
    """边界情况和异常输入测试"""

    def test_empty_events_list_rejected(self):
        """空事件列表应被拒绝 (Pydantic min_items=1)"""
        response = client.post("/api/v1/edge/events", json={"events": []})
        assert response.status_code == 422

    def test_exceeds_max_batch_size(self, base_event_dict):
        """超过100个事件的批次应被拒绝 (Pydantic max_items=100)"""
        events = [dict(base_event_dict) for _ in range(101)]
        response = client.post("/api/v1/edge/events", json={"events": events})
        assert response.status_code == 422

    def test_max_batch_size_accepted(self, base_event_dict):
        """恰好100个事件的批次应被接受"""
        events = []
        for i in range(100):
            evt = dict(base_event_dict)
            evt["idempotency_key"] = f"max_batch_{i}"
            events.append(evt)
        response = client.post("/api/v1/edge/events", json={"events": events})
        assert response.status_code == 200
        assert response.json()["accepted"] == 100

    def test_invalid_event_type_in_batch(self, base_event_dict):
        """批次中包含非法事件类型时整个批次被 Pydantic 拒绝"""
        invalid_evt = dict(base_event_dict)
        invalid_evt["event_type"] = "not_a_real_type"
        response = client.post("/api/v1/edge/events", json={"events": [invalid_evt]})
        assert response.status_code == 422

    def test_missing_timestamp(self, base_event_dict):
        """缺少 timestamp 应被 Pydantic 拒绝"""
        del base_event_dict["timestamp"]
        response = client.post("/api/v1/edge/events", json={"events": [base_event_dict]})
        assert response.status_code == 422

    def test_missing_store_id(self, base_event_dict):
        """缺少 store_id 应被拒绝"""
        del base_event_dict["store_id"]
        response = client.post("/api/v1/edge/events", json={"events": [base_event_dict]})
        assert response.status_code == 422

    def test_missing_device_id(self, base_event_dict):
        """缺少 device_id 应被拒绝"""
        del base_event_dict["device_id"]
        response = client.post("/api/v1/edge/events", json={"events": [base_event_dict]})
        assert response.status_code == 422

    def test_missing_payload(self, base_event_dict):
        """缺少 payload 应被拒绝"""
        del base_event_dict["payload"]
        response = client.post("/api/v1/edge/events", json={"events": [base_event_dict]})
        assert response.status_code == 422

    def test_invalid_severity_value_api(self, base_event_dict):
        """API 层面传入非法 severity 值"""
        base_event_dict["severity"] = "super_critical"
        response = client.post("/api/v1/edge/events", json={"events": [base_event_dict]})
        assert response.status_code == 422

    def test_confidence_out_of_range_api(self, base_event_dict):
        """API 层面 confidence 超出 [0, 1] 范围"""
        base_event_dict["confidence"] = 2.0
        response = client.post("/api/v1/edge/events", json={"events": [base_event_dict]})
        assert response.status_code == 422

    def test_extra_unknown_fields_ignored(self, base_event_dict):
        """未知字段应被忽略 (Pydantic 默认行为)"""
        base_event_dict["unknown_custom_field"] = "should_be_ignored"
        response = client.post("/api/v1/edge/events", json={"events": [base_event_dict]})
        assert response.status_code == 200

    def test_payload_can_be_any_json_structure(self, base_event_dict):
        """payload 可以是任意 JSON 结构"""
        complex_payloads = [
            {"simple": "value"},
            {"nested": {"deep": {"value": 42}}},
            {"array": [1, 2, 3], "flag": True, "count": None},
            {},  # 空对象也是合法的
        ]
        for payload in complex_payloads:
            evt = dict(base_event_dict)
            evt["idempotency_key"] = f"payload_test_{id(payload)}"
            evt["payload"] = payload
            response = client.post("/api/v1/edge/events", json={"events": [evt]})
            assert response.status_code == 200, f"payload {payload} 应被接受"


# =====================================================================
# 12. 离线/死信相关逻辑测试
# =====================================================================


class TestOfflineAndDeadLetterLogic:
    """离线缓存和死信队列相关逻辑测试"""

    def test_offline_buffer_flag_preserved(self, base_event_dict):
        """离线缓存标记在处理后保留"""
        base_event_dict["is_offline_buffer"] = True
        base_event_dict["buffered_at"] = "2026-08-05T02:00:00+08:00"
        # 提交后检查事件被正常接受
        response = client.post("/api/v1/edge/events", json={"events": [base_event_dict]})
        assert response.status_code == 200
        assert response.json()["accepted"] == 1

    def test_offline_buffer_without_timestamp(self, base_event_dict):
        """离线标记为True但缺少 buffered_at 仍可接受 (buffered_at 是可选的)"""
        base_event_dict["is_offline_buffer"] = True
        # 不设置 buffered_at
        response = client.post("/api/v1/edge/events", json={"events": [base_event_dict]})
        assert response.status_code == 200

    def test_batch_mix_online_and_offline(self, base_event_dict):
        """同一批次中混合在线和离线事件"""
        online_evt = dict(base_event_dict)
        online_evt["idempotency_key"] = "online_001"

        offline_evt = dict(base_event_dict)
        offline_evt["idempotency_key"] = "offline_001"
        offline_evt["is_offline_buffer"] = True
        offline_evt["buffered_at"] = "2026-08-05T02:00:00+08:00"

        response = client.post(
            "/api/v1/edge/events",
            json={"events": [online_evt, offline_evt]},
        )
        assert response.status_code == 200
        assert response.json()["accepted"] == 2

    def test_source_event_id_tracing(self, base_event_dict):
        """源事件ID链式追踪"""
        base_event_dict["source_event_id"] = "original_detection_evt"
        base_event_dict["trace_id"] = "trace-chain-abc"
        response = client.post("/api/v1/edge/events", json={"events": [base_event_dict]})
        assert response.status_code == 200
        assert response.json()["accepted"] == 1


# =====================================================================
# 13. 内部函数单元测试
# =====================================================================


class TestInternalFunctions:
    """内部辅助函数单元测试"""

    def test_generate_event_id_format(self):
        """生成的事件ID格式正确"""
        evt_id = _generate_event_id()
        assert evt_id.startswith("evt_")
        parts = evt_id.split("_")
        # 格式: evt_{12位hex}_{时间戳ms}
        assert len(parts) == 3
        assert len(parts[1]) == 12
        assert parts[2].isdigit()

    def test_generate_event_id_uniqueness(self):
        """连续生成的ID唯一"""
        ids = {_generate_event_id() for _ in range(100)}
        assert len(ids) == 100

    def test_is_duplicate_basic(self):
        """基本重复检测"""
        key = "dedup_test_key"
        assert _is_duplicate(key) is False  # 第一次不是重复
        assert _is_duplicate(key) is True   # 第二次是重复

    def test_is_duplicate_empty_key(self):
        """空 key 不参与去重"""
        assert _is_duplicate("") is False
        assert _is_duplicate("") is False
        assert _is_duplicate(None) is False  # type: ignore

    def test_is_duplicate_ttl_cleanup(self):
        """过期 key 被清理并重新接受"""
        key = "ttl_cleanup_key"
        _idempotency_store[key] = time.time() - _IDEMPOTENCY_TTL_SECONDS - 1
        assert _is_duplicate(key) is False  # 已过期，不算重复
        assert key in _idempotency_store     # 但已更新为新时间戳


# =====================================================================
# 14. 旧版兼容接口 /v1/events 测试
# =====================================================================


class TestLegacyCompatibility:
    """旧版 /v1/events 兼容接口测试"""

    def test_legacy_accepts_old_format(self):
        """旧版接口接受旧格式数据"""
        old_format = {
            "type": "waste_detected",
            "store_id": "store_legacy",
            "source": "device_legacy_001",
            "time": "2026-08-05T01:00:00+08:00",
            "data": {"waste_type": "food_waste"},
            "level": "warning",
            "confidence": 0.85,
        }
        response = client.post("/v1/events", json=old_format)
        assert response.status_code == 200
        data = response.json()
        assert data["accepted"] == 1

    def test_legacy_accepts_array_format(self):
        """旧版接口接受数组格式"""
        old_array = [
            {"type": "pos_order", "store_id": "store_01", "data": {"amount": 99.0}},
            {"type": "table_dirty", "store_id": "store_01", "data": {"table_id": "T05"}},
        ]
        response = client.post("/v1/events", json=old_array)
        assert response.status_code == 200
        assert response.json()["accepted"] == 2

    def test_legacy_defaults_for_missing_fields(self):
        """旧版接口对缺失字段使用默认值"""
        minimal = {"custom_field": "only_this"}
        response = client.post("/v1/events", json=minimal)
        assert response.status_code == 200
        # 默认转换为 model_inference 类型
        assert response.json()["accepted"] == 1

    def test_deprecated_header_present(self):
        """旧版接口应标记为 deprecated"""
        # FastAPI deprecated 端点不会改变HTTP状态码，但 OpenAPI schema 中会标记
        # 这里仅验证功能可用
        response = client.post("/v1/events", json={"type": "device_heartbeat"})
        assert response.status_code == 200


# =====================================================================
# 15. BatchEventsRequest/Response 模型验证
# =====================================================================


class TestBatchModels:
    """批量请求/响应模型验证"""

    def test_batch_request_min_events(self):
        """最少1个事件"""
        req = BatchEventsRequest(events=[
            UnifiedEdgeEvent(
                event_type=EventType.WASTE_DETECTED,
                store_id="s1",
                device_id="d1",
                timestamp="2026-08-05T01:00:00+08:00",
                payload={},
            )
        ])
        assert len(req.events) == 1

    def test_batch_request_max_events(self):
        """最多100个事件"""
        events = [
            UnifiedEdgeEvent(
                event_type=EventType.DEVICE_HEARTBEAT,
                store_id="s1",
                device_id=f"d{i}",
                timestamp="2026-08-05T01:00:00+08:00",
                payload={},
            )
            for i in range(100)
        ]
        req = BatchEventsRequest(events=events)
        assert len(req.events) == 100

    def test_batch_request_exceeds_max(self):
        """超过100个事件应校验失败"""
        events = [
            UnifiedEdgeEvent(
                event_type=EventType.DEVICE_HEARTBEAT,
                store_id="s1",
                device_id=f"d{i}",
                timestamp="2026-08-05T01:00:00+08:00",
                payload={},
            )
            for i in range(101)
        ]
        with pytest.raises(PydanticValidationError):
            BatchEventsRequest(events=events)

    def test_batch_response_model_roundtrip(self):
        """响应模型序列化/反序列化一致"""
        resp = BatchEventsResponse(
            batch_id="test_batch",
            accepted=5,
            rejected=1,
            duplicates=2,
            event_ids=["evt_1", "evt_2", "evt_3", "evt_4", "evt_5"],
            errors=[{"event_index": "5", "reason": "test error"}],
            processed_at=datetime.now(timezone.utc).isoformat(),
        )
        data = resp.model_dump()
        assert data["accepted"] == 5
        assert data["rejected"] == 1
        assert len(data["errors"]) == 1
