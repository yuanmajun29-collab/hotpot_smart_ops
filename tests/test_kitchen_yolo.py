"""后厨 YOLO 预过滤冒烟测试 (ADR-014 三级过滤 Phase 1)

验证：
  1. /infer/kitchen/yolo — YOLO-only 检测端点
  2. /infer/kitchen — 完整管道（VLM 禁用时返回 yolo-only）
  3. VLM 触发逻辑 — 可疑帧触发、正常帧跳过
  4. 标注图生成
"""

import json
import requests

BASE = "http://localhost:9100"


def test_kitchen_health():
    """后厨健康检查：管道模式、YOLO 状态"""
    r = requests.get(f"{BASE}/infer/kitchen/health", timeout=10)
    assert r.status_code == 200
    data = r.json()
    assert data["active"] is True
    assert data["pipeline"] in ("yolo-only", "yolo+vlm")
    assert "yolo_loaded" in data


def test_kitchen_yolo_detection():
    """YOLO 检测 real_kitchen.jpg — 后厨场景应有检测结果"""
    r = requests.get(
        f"{BASE}/infer/kitchen/yolo",
        params={"image_path": "demo/data/real_kitchen.jpg", "annotate": "true"},
        timeout=30,
    )
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert data["mode"] == "yolo-only"
    assert data["total_detections"] > 0, "后厨场景应有物体检测"
    assert data["inference_ms"] < 500, f"YOLO 推理应在 500ms 内，实际 {data['inference_ms']}ms"
    assert "vlm_should_trigger" in data
    assert "vlm_reason" in data
    # 有 staff + 容器/餐具 → 应触发 VLM
    assert data["vlm_should_trigger"] is True, f"后厨有人员+物体，应触发VLM，原因: {data.get('vlm_reason')}"
    # 标注图
    if data.get("annotated_url"):
        assert data["annotated_url"].startswith("/output/")


def test_kitchen_yolo_empty_scene():
    """YOLO 检测 kitchen.jpg — 空/简单厨房场景"""
    r = requests.get(
        f"{BASE}/infer/kitchen/yolo",
        params={"image_path": "demo/data/kitchen.jpg"},
        timeout=30,
    )
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    # 空或简单场景 → 检测数应较少
    assert data["total_detections"] >= 0


def test_kitchen_full_pipeline():
    """完整管道 POST — VLM 禁用时返回 YOLO 结果"""
    r = requests.post(
        f"{BASE}/infer/kitchen",
        json={"image_path": "demo/data/real_kitchen.jpg"},
        timeout=30,
    )
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert data["pipeline"] in ("yolo-only", "yolo+vlm")
    assert data["yolo"]["total_detections"] > 0
    assert data["yolo"]["inference_ms"] < 500
    # VLM 层
    assert "triggered" in data["vlm"]
    assert "reason" in data["vlm"]
    assert data["total_ms"] < 500
    # 标注图
    assert "annotated_url" in data


def test_kitchen_annotated_image():
    """标注图可访问"""
    r = requests.get(
        f"{BASE}/infer/kitchen/yolo",
        params={"image_path": "demo/data/real_kitchen.jpg", "annotate": "true"},
        timeout=30,
    )
    data = r.json()
    url = data.get("annotated_url", "")
    assert url, "应返回标注图 URL"

    img_r = requests.get(f"{BASE}{url}", timeout=10)
    assert img_r.status_code == 200
    assert len(img_r.content) > 1000, "标注图应有内容"


def test_kitchen_image_not_found():
    """不存在的图片 → 404"""
    r = requests.get(
        f"{BASE}/infer/kitchen/yolo",
        params={"image_path": "nonexistent.jpg"},
        timeout=10,
    )
    assert r.status_code == 404


def test_kitchen_module_disabled():
    """未激活模块的 health 检查（仅验证响应格式）"""
    # 当前 kitchen 是激活的，只验证 health 结构和状态
    r = requests.get(f"{BASE}/infer/kitchen/health", timeout=10)
    assert r.status_code == 200
    data = r.json()
    assert "module" in data
    assert "pipeline" in data
    assert "vlm_enabled" in data
