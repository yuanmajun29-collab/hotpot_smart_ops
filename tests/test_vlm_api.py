"""Tests for VLM review API (DEV-301)."""

from fastapi.testclient import TestClient

from hotpot_platform.cloud.vlm_review.app import app

client = TestClient(app)


def test_vlm_health():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_quality_grade_rule():
    r = client.post("/quality-grade", json={"sku": "毛肚", "batch_id": "B001"})
    assert r.status_code == 200
    data = r.json()
    assert data["quality_grade"] in ("A", "B", "C")
    assert data["backend"] == "rule"


def test_table_clean_rule():
    r = client.post("/table-clean-ready", json={"table_id": "T03"})
    assert r.status_code == 200
    data = r.json()
    assert "clean_ready_score" in data
    assert "ready" in data


def test_review_rule():
    r = client.post("/review", json={"event_type": "kitchen_smoke"})
    assert r.status_code == 200
    assert r.json()["confirmed"] is True
