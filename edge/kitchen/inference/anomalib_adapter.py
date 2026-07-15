#!/usr/bin/env python3
"""anomalib 适配器 — 与自写 Memory Bank 的 A/B 对比

当前方案: MobileNetV3-Small + Patch KNN (anomaly_infer.py)
anomalib: PatchCore (WideResNet50 + Coreset) — Intel 开源

用法:
  python3 anomalib_adapter.py --compare     # 对比两种方案
  python3 anomalib_adapter.py --image x.jpg  # 单张推理
"""

import json
import time
import warnings
from pathlib import Path
from typing import Dict, Optional

import numpy as np

warnings.filterwarnings("ignore")

# ─── 配置 ───
BANK_PATH = Path("/opt/hotpot-infer/models/kitchen_normality_bank.npz")
ANOMALIB_MODEL_PATH = Path("/opt/hotpot-infer/models/anomalib_patchcore.pt")
IMAGE_SIZE = 512


def benchmark_self_made(image_path: str) -> Dict:
    """自写 Memory Bank 方案 (现有方案)."""
    t0 = time.time()

    # 复用 anomaly_infer 的推理
    from edge.kitchen.inference.anomaly_infer import (
        AnomalyDetector, BANK_PATH, K, GAIN
    )
    detector = AnomalyDetector(bank_path=BANK_PATH, k=K, gain=GAIN)
    result = detector.detect(image_path)
    result["latency_ms"] = round((time.time() - t0) * 1000, 1)
    result["backend"] = "self-made-knn"
    result["model_size_mb"] = 5.0  # MobileNetV3-Small
    return result


def benchmark_anomalib(image_path: str) -> Dict:
    """anomalib PatchCore 方案."""
    try:
        from anomalib.models import Patchcore
        from anomalib.data.utils import read_image, transform_image
    except ImportError:
        return {"error": "anomalib not installed", "backend": "anomalib-patchcore"}

    t0 = time.time()

    # 加载模型
    if ANOMALIB_MODEL_PATH.exists():
        model = Patchcore.load_from_checkpoint(str(ANOMALIB_MODEL_PATH))
    else:
        # 使用默认预训练
        model = Patchcore(backbone="wide_resnet50_2")
        model.eval()

    # 预处理
    image = read_image(image_path)
    image = transform_image(image, IMAGE_SIZE)

    with np.no_grad():
        result = model.predict(image)

    return {
        "anomaly_score": float(result.pred_score),
        "has_anomaly": bool(result.pred_label == 1),
        "heatmap_available": result.anomaly_map is not None,
        "latency_ms": round((time.time() - t0) * 1000, 1),
        "backend": "anomalib-patchcore",
        "model_size_mb": 280.0,  # WideResNet50
    }


def compare(image_path: str):
    """A/B 对比两种方案."""
    if not Path(image_path).exists():
        print(f"❌ 图片不存在: {image_path}")
        return

    print(f"=== 异常检测方案对比 ===")
    print(f"图片: {image_path}\n")

    # 方案1
    print("1️⃣ 自写 Memory Bank (MobileNetV3-Small + KNN)")
    try:
        r1 = benchmark_self_made(image_path)
        print(f"   得分: {r1.get('anomaly_score', '?'):.3f}")
        print(f"   异常: {r1.get('has_anomaly', 'unknown')}")
        print(f"   延迟: {r1['latency_ms']}ms")
        print(f"   模型: {r1['model_size_mb']}MB")
    except Exception as e:
        r1 = None
        print(f"   ❌ {e}")

    print()

    # 方案2
    print("2️⃣ anomalib PatchCore (WideResNet50 + Coreset)")
    try:
        r2 = benchmark_anomalib(image_path)
        if "error" in r2:
            print(f"   ⚠️ {r2['error']}")
        else:
            print(f"   得分: {r2['anomaly_score']:.3f}")
            print(f"   异常: {r2['has_anomaly']}")
            print(f"   延迟: {r2['latency_ms']}ms")
            print(f"   模型: {r2['model_size_mb']}MB")
    except Exception as e:
        r2 = None
        print(f"   ❌ {e}")

    # 评估
    print("\n📊 评估:")
    print("   自写方案: 轻量(5MB)、快速、已部署 ✅")
    print("   anomalib: 更重(280MB)、更准(工业验证)、热力图更好")
    print("   → Phase 1 保持自写。Phase 2 标注数据充足后可迁移 anomalib。")


# ─── CLI ───
if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        # 默认运行对比表
        print("用法: python3 anomalib_adapter.py --compare  [A/B对比]")
        print("      python3 anomalib_adapter.py image.jpg  [单张推理]")
        print()
        print("=== 方案特性对比 ===")
        print(f"{'特性':<20} {'自写 KNN':<20} {'anomalib PatchCore':<20}")
        print("-" * 60)
        rows = [
            ("骨干网络", "MobileNetV3-Small", "WideResNet50"),
            ("模型大小", "5 MB", "280 MB"),
            ("异常检测方法", "KNN距离", "Coreset采样"),
            ("特征维度", "576", "1792"),
            ("预期延迟", "<100ms", "200-400ms"),
            ("内存占用", "~50MB", "~1GB"),
            ("工业验证", "自测", "Intel/MVTec"),
            ("热力图", "手工叠加", "内置Grad-CAM"),
            ("Jetson可行", "✅ 是", "⚠️ 内存紧张"),
            ("Phase 1", "✅ 当前方案", "⏸ 不做"),
            ("Phase 2", "🔄 持续优化", "🔜 标注后迁移"),
        ]
        for r in rows:
            print(f"{r[0]:<20} {r[1]:<20} {r[2]:<20}")
    elif sys.argv[1] == "--compare" and len(sys.argv) > 2:
        compare(sys.argv[2])
    else:
        # 单张推理（用自写方案）
        result = benchmark_self_made(sys.argv[1])
        print(json.dumps(result, ensure_ascii=False, indent=2))
