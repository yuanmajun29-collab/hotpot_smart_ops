"""POST /v1/vlm/waste-estimate — VLM 废料识别 (VLM-603 / TC-COST-09)."""
from __future__ import annotations

import base64
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(monkeypatch):
    tmp = tempfile.mkdtemp()
    db_path = Path(tmp) / "test_hub.db"
    monkeypatch.setenv("HOTPOT_DB", str(db_path))
    monkeypatch.setenv("HOTPOT_AUTH_MODE", "strict")
    monkeypatch.delenv("HOTPOT_SEED_DIR", raising=False)
    monkeypatch.delenv("HOTPOT_DATABASE_URL", raising=False)
    monkeypatch.delenv("HOTPOT_VLM_WASTE", raising=False)
    from cloud.event_hub import app as m
    from cloud.event_hub.db import create_hub_database
    from cloud.event_hub import runtime

    dbo = create_hub_database(db_path)
    runtime.init(m.MultiTenantHub(on_persist=dbo.on_persist), dbo, m.AlertGateway(db_path))
    with TestClient(m.app) as c:
        yield c


def _tok(c, user="zhangdian", role="店长", store="store_yuhuan"):
    r = c.post("/auth/token", json={"username": user, "password": "demo", "role": role, "store_id": store})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


# ── mock (hub) path tests ──

def test_waste_estimate_mock_with_image_ref(client):
    h = _tok(client)
    r = client.post(
        "/v1/vlm/waste-estimate",
        json={"image_ref": "rtsp://cam/waste-zone-a/frame-001.jpg", "zone": "备餐废弃区"},
        headers=h,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["source"] == "mock"
    assert body["store_id"] == "store_yuhuan"
    assert body["event_id"]
    assert len(body["items"]) >= 1
    assert body["items"][0]["confidence"] > 0
    assert body["items"][0]["unit"] == "份"


def test_waste_estimate_requires_input(client):
    """Must have items, image_ref, or stream_id."""
    h = _tok(client)
    r = client.post("/v1/vlm/waste-estimate", json={"zone": "废弃区"}, headers=h)
    assert r.status_code == 422


def test_waste_estimate_cross_store_forbidden(client):
    h = _tok(client, store="store_yuhuan")
    r = client.post(
        "/v1/vlm/waste-estimate",
        json={"store_id": "store_jiaojiang", "stream_id": "cam-jj-waste-1"},
        headers=h,
    )
    assert r.status_code == 403


def test_waste_estimate_writes_loss_features(client):
    h = _tok(client)
    client.post(
        "/v1/vlm/waste-estimate",
        json={"image_ref": "file://sample/waste.jpg"},
        headers=h,
    )
    feats = client.get("/v1/cost/loss-features", headers=h)
    assert feats.status_code == 200, feats.text
    data = feats.json()
    assert data["waste_evidence"]
    assert data["source"] in ("mock", "vlm-shadow")


# ── edge inference (Jetson bridge) path tests ──

def test_waste_estimate_edge_items_direct(client):
    """Jetson sends items directly — Hub uses them without mock."""
    h = _tok(client)
    items = [
        {
            "sku": "毛肚",
            "waste_type": "边角料",
            "estimated_portion": 0.8,
            "unit": "份",
            "confidence": 0.82,
            "reason": "切口不齐，大小不均",
            "suggested_action": "调整切配标准",
        }
    ]
    r = client.post(
        "/v1/vlm/waste-estimate",
        json={
            "store_id": "store_yuhuan",
            "items": items,
            "source": "vlm-shadow",
            "model": "ostrakon-vl-8b-iq4xs",
            "zone": "备餐废弃区",
        },
        headers=h,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["source"] == "vlm-shadow"
    assert body["model"] == "ostrakon-vl-8b-iq4xs"
    assert body["items"] == items
    assert body["store_id"] == "store_yuhuan"


def test_waste_estimate_edge_no_image_ref_ok(client):
    """Edge path: image_ref not required when items present."""
    h = _tok(client)
    r = client.post(
        "/v1/vlm/waste-estimate",
        json={
            "items": [{"sku": "黄喉", "waste_type": "过期临界", "estimated_portion": 0.3, "unit": "kg", "confidence": 0.91, "reason": "颜色发暗"}],
            "source": "vlm-shadow",
            "model": "ostrakon-vl-8b-iq4xs",
        },
        headers=h,
    )
    assert r.status_code == 200
    assert r.json()["source"] == "vlm-shadow"


def test_waste_estimate_edge_empty_items_rejected(client):
    """Empty items list without image_ref/stream_id → 422 (no valid input)."""
    h = _tok(client)
    r = client.post(
        "/v1/vlm/waste-estimate",
        json={
            "items": [],
            "source": "vlm-shadow",
            "model": "ostrakon-vl-8b-iq4xs",
        },
        headers=h,
    )
    assert r.status_code == 422


def test_waste_estimate_edge_empty_items_with_image_ref(client):
    """Empty items + image_ref → mock fallback (hub path)."""
    h = _tok(client)
    r = client.post(
        "/v1/vlm/waste-estimate",
        json={
            "items": [],
            "source": "vlm-shadow",
            "model": "ostrakon-vl-8b-iq4xs",
            "image_ref": "file://test.jpg",
        },
        headers=h,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["source"] == "mock"


# ── 图片流转测试 ──

# 最小有效 1x1 JPEG (base64)
_TINY_JPEG_B64 = "/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAAgGBgcGBQgHBwcJCQgKDBQNDAsLDBkSEw8UHRofHh0aHBwgJC4nICIsIxwcKDcpLDAxNDQ0Hyc5PTgyPC4zNDL/wAALCAABAAEBAREA/8QAFAABAAAAAAAAAAAAAAAAAAAACf/EABQQAQAAAAAAAAAAAAAAAAAAAAD/2gAIAQEAAD8AKp//2Q=="


def test_waste_estimate_edge_with_image(client):
    """Jetson sends items + base64 image → Hub saves image + returns image_url."""
    h = _tok(client)
    items = [{"sku": "毛肚", "waste_type": "边角料", "estimated_portion": 0.8, "unit": "份", "confidence": 0.82}]
    r = client.post("/v1/vlm/waste-estimate", json={
        "store_id": "store_yuhuan",
        "items": items,
        "source": "vlm-shadow",
        "model": "ostrakon-vl-8b-iq4xs",
        "image_data": _TINY_JPEG_B64,
        "image_mime": "image/jpeg",
    }, headers=h)
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert "image_url" in body
    # 验证图片端点可访问
    img_r = client.get(body["image_url"])
    assert img_r.status_code == 200
    assert img_r.headers["content-type"].startswith("image/")


def test_waste_image_404(client):
    """Non-existent image returns 404."""
    r = client.get("/v1/vlm/images/nonexistent-id")
    assert r.status_code == 404


def test_waste_estimate_edge_no_image(client):
    """Edge path without image_data still works (backward compat)."""
    h = _tok(client)
    items = [{"sku": "黄喉", "waste_type": "过期临界", "estimated_portion": 0.3, "unit": "kg", "confidence": 0.91}]
    r = client.post("/v1/vlm/waste-estimate", json={
        "items": items, "source": "vlm-shadow", "model": "ostrakon-vl-8b-iq4xs",
    }, headers=h)
    assert r.status_code == 200
    assert "image_url" not in r.json() or r.json().get("image_url") is None
