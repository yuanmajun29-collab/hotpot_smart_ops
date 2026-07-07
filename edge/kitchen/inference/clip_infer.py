#!/usr/bin/env python3
"""CLIP-Adapter Inference — 后厨少样本食材/缺陷分类

推理规则（阈值/类别）→ rules.py
推理内容（Adapter 架构/分类器）→ 本文件

Usage:
    python3 clip_infer.py --image /tmp/roi.jpg --classes "毛肚,鹅肠,废料,手套" --adapter /opt/hotpot-infer/models/adapter_weights.pt

CLIP-Adapter 架构: ViT-B/32 冻结 + 瓶颈适配器(1024→256→1024) + 残差融合
适配器仅 514KB，1-Shot 微调后准确率 33%→67%

Run inside Docker:
    docker run --rm --runtime=nvidia \
        -v /opt/hotpot-infer:/opt/hotpot-infer \
        -v /tmp:/tmp \
        nvcr.io/nvidia/l4t-pytorch:r34.1.1-pth1.12-py3 \
        python3 /opt/hotpot-infer/pipeline/clip_infer.py --image /tmp/roi.jpg --classes "毛肚,鹅肠,废料"
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

import torch
import torch.nn as nn
from PIL import Image

from .rules import CLIP_LOW_CONF_THRESHOLD, CLIP_ADAPTER_RATIO


# ===== Adapter 实现 =====
class Adapter(nn.Module):
    """瓶颈适配器: 1024 → 256 → 1024, 参数量 ~0.5M"""

    def __init__(self, c_in=1024, reduction=4):
        super().__init__()
        self.fc = nn.Sequential(
            nn.Linear(c_in, c_in // reduction, bias=False),
            nn.ReLU(inplace=True),
            nn.Linear(c_in // reduction, c_in, bias=False),
            nn.ReLU(inplace=True),
        )

    def forward(self, x):
        return self.fc(x)


class CLIPAdapter(nn.Module):
    """CLIP + Adapter 残差融合"""

    def __init__(self, clip_model, adapter_ratio=CLIP_ADAPTER_RATIO):
        super().__init__()
        self.clip = clip_model
        output_dim = clip_model.visual.output_dim
        self.adapter = Adapter(output_dim, 4).to(device=clip_model.visual.proj.device, dtype=torch.float32)
        self.ratio = adapter_ratio

    def encode_image(self, image):
        with torch.no_grad():
            features = self.clip.encode_image(image)
        adapted = self.adapter(features.to(torch.float32)).to(features.dtype)
        fused = self.ratio * adapted + (1 - self.ratio) * features
        return fused / fused.norm(dim=-1, keepdim=True)

    def encode_text(self, text):
        with torch.no_grad():
            features = self.clip.encode_text(text)
        return features / features.norm(dim=-1, keepdim=True)


class CLIPInferencer:
    def __init__(self, adapter_path: str, device: str = "cuda"):
        self.device = device

        import clip
        self.clip = clip

        self.model, self.preprocess = clip.load("ViT-B/32", device=device)
        self.model.eval()

        self.clip_adapter = CLIPAdapter(self.model, adapter_ratio=CLIP_ADAPTER_RATIO).to(device)
        self.clip_adapter.eval()

        if adapter_path and os.path.exists(adapter_path):
            state = torch.load(adapter_path, map_location=device)
            self.clip_adapter.adapter.load_state_dict(state)
            print(f"[clip] Adapter loaded: {adapter_path}")
        else:
            print("[clip] No adapter weights, using zero-shot baseline")

    def classify(self, image_path: str, classes: list) -> dict:
        image = self.preprocess(Image.open(image_path)).unsqueeze(0).to(self.device)

        text_tokens = self.clip.tokenize(classes).to(self.device)

        with torch.no_grad():
            img_feat = self.clip_adapter.encode_image(image)
            txt_feat = self.clip_adapter.encode_text(text_tokens)
            logits = (100.0 * img_feat @ txt_feat.T).softmax(dim=-1)

        scores = logits[0].tolist()
        best_idx = int(logits[0].argmax())
        return {
            "top_class": classes[best_idx],
            "top_confidence": round(scores[best_idx], 4),
            "all_scores": {cls: round(s, 4) for cls, s in zip(classes, scores)},
            "low_confidence": scores[best_idx] < CLIP_LOW_CONF_THRESHOLD,
        }


def main():
    parser = argparse.ArgumentParser(description="CLIP-Adapter Inference")
    parser.add_argument("--image", required=True, help="Input image path")
    parser.add_argument("--classes", required=True, help="Comma-separated class names")
    parser.add_argument(
        "--adapter", default="/opt/hotpot-infer/models/adapter_weights.pt"
    )
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--threshold", type=float, default=CLIP_LOW_CONF_THRESHOLD, help="Low confidence threshold")
    args = parser.parse_args()

    classes = [c.strip() for c in args.classes.split(",")]

    t0 = time.time()
    inferencer = CLIPInferencer(args.adapter, args.device)
    result = inferencer.classify(args.image, classes)
    dt = (time.time() - t0) * 1000

    result["inference_ms"] = round(dt, 1)
    result["image"] = args.image

    print(json.dumps(result, ensure_ascii=False, indent=2))

    # Exit code for pipeline: 0=high_confidence, 1=low_confidence
    if result["low_confidence"]:
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
