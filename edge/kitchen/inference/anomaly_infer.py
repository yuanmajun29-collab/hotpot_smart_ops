#!/usr/bin/env python3
"""
SuperADD 适配版 — 零训练厨房异常检测
Backbone: MobileNetV3-Small (5MB, <100ms on Jetson)
原理: 正常样本 → Memory Bank → KNN距离 → 异常热力图
"""

import json
import sys
import time
import warnings
from pathlib import Path

import numpy as np
from PIL import Image
from typing import List, Optional

warnings.filterwarnings("ignore")

# ─── 配置 ─────────────────────────────────────────────
PATCH_SIZE = 128
OVERLAP = 32  # 25% overlap
IMAGE_SIZE = 512  # resize to this before patching
BANK_PATH = Path("/opt/hotpot-infer/models/kitchen_normality_bank.npz")
LAYER_NAME = "features.12"  # MobileNetV3 last conv block
FEATURE_DIM = 576  # MobileNetV3-Small feature dim at layer 12
K = 5  # KNN neighbors
GAIN = 1.2  # threshold gain factor

# ─── 延迟加载 Backbone ──────────────────────────────────
_backbone = None


def _get_backbone():
    global _backbone
    if _backbone is not None:
        return _backbone
    import torch
    import torchvision.models as models

    model = models.mobilenet_v3_small(weights="DEFAULT")
    model.eval()

    # Hook to extract intermediate features
    features = {}

    def hook_fn(name):
        def fn(_, inp, out):
            features[name] = out

        return fn

    # Register hook at layer features.12
    for name, module in model.named_modules():
        if name == LAYER_NAME:
            module.register_forward_hook(hook_fn(name))
            break

    model(torch.randn(1, 3, IMAGE_SIZE, IMAGE_SIZE))  # warmup
    _backbone = (model, features)
    return _backbone


# ─── 图像预处理 ──────────────────────────────────────────
def _preprocess(img: Image.Image):
    import torchvision.transforms as T

    transform = T.Compose(
        [
            T.Resize((IMAGE_SIZE, IMAGE_SIZE)),
            T.ToTensor(),
            T.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225]),
        ]
    )
    return transform(img).unsqueeze(0)


# ─── 特征提取 ───────────────────────────────────────────
def extract_features(img: Image.Image):
    """提取 MobileNetV3 中间层特征 (C×H×W → N×D)"""
    import torch

    model, hooks = _get_backbone()
    tensor = _preprocess(img)

    with torch.no_grad():
        _ = model(tensor)

    feat = hooks[LAYER_NAME]  # [1, 576, 16, 16]
    feat = feat.squeeze(0).permute(1, 2, 0).cpu().numpy()  # [16, 16, 576]
    return feat  # spatial feature map


def extract_patch_features(img: Image.Image):
    """
    重叠切块 → 逐块提取特征
    返回: (n_patches, feature_dim) 数组 + patch 坐标列表
    """
    w, h = img.size
    scale = IMAGE_SIZE / max(w, h)
    new_w, new_h = int(w * scale), int(h * scale)
    img_resized = img.resize((new_w, new_h))

    # 计算 grid
    stride = PATCH_SIZE - OVERLAP
    nx = max(1, (new_w - PATCH_SIZE) // stride + 1)
    ny = max(1, (new_h - PATCH_SIZE) // stride + 1)

    features = []
    coords = []

    for iy in range(ny):
        for ix in range(nx):
            x1 = ix * stride
            y1 = iy * stride
            x2 = min(x1 + PATCH_SIZE, new_w)
            y2 = min(y1 + PATCH_SIZE, new_h)

            # 调整 patch 使其对齐到边缘
            if x2 == new_w:
                x1 = max(0, new_w - PATCH_SIZE)
            if y2 == new_h:
                y1 = max(0, new_h - PATCH_SIZE)

            patch = img_resized.crop((x1, y1, x1 + PATCH_SIZE, y1 + PATCH_SIZE))
            feat_map = extract_features(patch)  # [Hp, Wp, D]

            # 全局平均池化 → 1D 特征
            feat_vec = feat_map.mean(axis=(0, 1))  # [D]
            features.append(feat_vec)
            coords.append((x1, y1, min(x1 + PATCH_SIZE, new_w), min(y1 + PATCH_SIZE, new_h)))

    return np.array(features), coords, (new_w, new_h)


# ─── Memory Bank ─────────────────────────────────────────
def build_memory_bank(normal_image_paths: List[str]):
    """
    从正常样本构建 Memory Bank
    参数: normal_image_paths — 整洁后厨图片路径列表
    保存到 BANK_PATH
    """
    all_features = []
    for path in normal_image_paths:
        img = Image.open(path).convert("RGB")
        feats, _, _ = extract_patch_features(img)
        all_features.append(feats)

    bank = np.concatenate(all_features, axis=0)
    BANK_PATH.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(BANK_PATH, features=bank)
    return bank


def load_memory_bank():
    """加载 Memory Bank"""
    if not BANK_PATH.exists():
        return None
    data = np.load(BANK_PATH)
    return data["features"]


# ─── 异常检测 ───────────────────────────────────────────
def detect_anomaly(image_path: str, bank: np.ndarray = None):
    """
    对单张图像做异常检测
    返回: anomaly_score (float), anomaly_map (np.array), details (dict)
    """
    if bank is None:
        bank = load_memory_bank()
    if bank is None:
        return {"status": "error", "error": "Memory Bank not built. Run build_memory_bank first."}

    img = Image.open(image_path).convert("RGB")
    t0 = time.time()
    feats, coords, (img_w, img_h) = extract_patch_features(img)
    t1 = time.time()

    # KNN 距离 (简化: 用 numpy 暴力搜索)
    from sklearn.neighbors import NearestNeighbors

    nn = NearestNeighbors(n_neighbors=K, metric="cosine", n_jobs=1)
    nn.fit(bank)
    distances, _ = nn.kneighbors(feats)
    anomaly_scores = distances.mean(axis=1)  # [n_patches]

    t2 = time.time()

    # 构建 anomaly map（与原始图片尺寸对齐）
    anomaly_map = np.zeros((img_h, img_w), dtype=np.float32)
    count_map = np.zeros((img_h, img_w), dtype=np.float32)

    for (x1, y1, x2, y2), score in zip(coords, anomaly_scores):
        anomaly_map[y1:y2, x1:x2] += score
        count_map[y1:y2, x1:x2] += 1

    count_map[count_map == 0] = 1
    anomaly_map /= count_map

    # 异常分数（取 top-K patch 平均作为整图分数）
    top_k = max(3, len(anomaly_scores) // 4)
    image_score = float(np.sort(anomaly_scores)[-top_k:].mean())

    # 二分判定：score > 正常样本95分位数 * gain
    is_anomaly = image_score > 0.5  # 初始阈值，后续从 Bank 校准

    return {
        "status": "ok",
        "image_score": round(image_score, 4),
        "is_anomaly": is_anomaly,
        "anomaly_map": anomaly_map.tolist(),
        "patch_count": len(feats),
        "feature_time_ms": int((t1 - t0) * 1000),
        "knn_time_ms": int((t2 - t1) * 1000),
        "total_time_ms": int((t2 - t0) * 1000),
        "image_size": (img_w, img_h),
    }


# ─── 热力图生成 ──────────────────────────────────────────
def generate_heatmap(image_path: str, anomaly_map: np.ndarray, output_path: str):
    """生成异常热力图叠加在原图上"""
    from PIL import ImageDraw

    img = Image.open(image_path).convert("RGBA")
    w, h = img.size

    # 上采样 anomaly_map 到原始尺寸
    from PIL import Image as PILImage

    amap_img = PILImage.fromarray((anomaly_map * 255).astype(np.uint8))
    amap_img = amap_img.resize((w, h), PILImage.Resampling.BILINEAR)
    amap = np.array(amap_img) / 255.0

    # 红色热力 overlay
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(w / 100, h / 100), dpi=100)
    ax.imshow(img.convert("RGB"))
    ax.imshow(amap, cmap="hot", alpha=0.5, vmin=0, vmax=max(amap.max(), 0.01))
    ax.axis("off")
    plt.tight_layout(pad=0)
    plt.savefig(output_path, bbox_inches="tight", pad_inches=0, dpi=100)
    plt.close()


# ─── CLI ─────────────────────────────────────────────────
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd")

    build_parser = sub.add_parser("build")
    build_parser.add_argument("images", nargs="+", help="正常样本图片路径")

    detect_parser = sub.add_parser("detect")
    detect_parser.add_argument("image", help="待检测图片路径")
    detect_parser.add_argument("--output", help="热力图输出路径")
    detect_parser.add_argument("--bank", default=str(BANK_PATH))

    args = parser.parse_args()

    if args.cmd == "build":
        bank = build_memory_bank(args.images)
        print(json.dumps({"status": "ok", "bank_size": len(bank), "path": str(BANK_PATH)}))

    elif args.cmd == "detect":
        bank = load_memory_bank() if Path(args.bank).exists() else None
        result = detect_anomaly(args.image, bank)
        print(json.dumps(result, ensure_ascii=False, indent=2))

        if args.output and "anomaly_map" in result:
            amap = np.array(result["anomaly_map"])
            generate_heatmap(args.image, amap, args.output)
            print(f"heatmap → {args.output}")
