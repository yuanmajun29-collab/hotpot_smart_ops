#!/usr/bin/env python3
"""HSGDet 轻量落地 — 未知检测语义化 + 自适应扩类

思路对齐 CR2T: 视觉特征 + 场景上下文 + 父节点语义 → 生成未知标签

轻量适配 (Jetson可跑):
  1. YOLO低置信度检测 → 路由到"未知"
  2. CLIP特征匹配已有类别（类似DHGA Top-K路由）
  3. 匹配不上 → VLM生成描述 + 注册为新类别
  4. 新类别写回本地词表，下次检测复用

用法:
  from open_world_adapter import OpenWorldAdapter
  adapter = OpenWorldAdapter(vocab_path="kitchen_vocab.json")
  results = adapter.process(yolo_detections, frame, scene_context)
"""

import json
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np

# ─── 配置 ───
VOCAB_PATH = Path("/opt/hotpot-infer/models/kitchen_vocab.json")
UNKNOWN_THRESH = 0.35       # 低于此置信度 → 视为"不确定"
SIMILARITY_THRESH = 0.6     # CLIP相似度阈值
MAX_VOCAB_SIZE = 100         # 词表上限


class OpenWorldAdapter:
    """开放世界检测适配器: 未知→语义化→扩类."""

    def __init__(self, vocab_path: Path = VOCAB_PATH):
        self.vocab_path = vocab_path
        self.vocab: Dict[str, dict] = self._load_vocab()
        self._clip_features: Dict[str, np.ndarray] = {}

    # ─── 词表管理 ───

    def _load_vocab(self) -> Dict[str, dict]:
        """加载本地词表."""
        if self.vocab_path.exists():
            return json.loads(self.vocab_path.read_text())
        return {
            "_meta": {"version": 1, "created": time.strftime("%Y-%m-%d")},
            "categories": {
                "bowl": {"parent": "tableware", "description": "碗", "count": 0},
                "plate": {"parent": "tableware", "description": "盘子", "count": 0},
                "pot": {"parent": "cookware", "description": "锅", "count": 0},
                "food_waste": {"parent": "waste", "description": "食物残渣", "count": 0},
                "cluttered": {"parent": "disorder", "description": "杂乱堆放", "count": 0},
                "clean": {"parent": "state", "description": "干净整洁", "count": 0},
            },
            "parents": {
                "tableware": "餐具",
                "cookware": "厨具",
                "waste": "废弃物",
                "disorder": "异常状态",
                "state": "状态",
            },
        }

    def _save_vocab(self):
        """持久化词表."""
        self.vocab_path.write_text(json.dumps(self.vocab, ensure_ascii=False, indent=2))

    def register_category(self, name: str, parent: str, description: str):
        """注册新类别到词表."""
        if len(self.vocab["categories"]) >= MAX_VOCAB_SIZE:
            # 淘汰最不常用的
            least_used = min(
                self.vocab["categories"].items(),
                key=lambda x: x[1]["count"],
            )
            del self.vocab["categories"][least_used[0]]

        parent_key = parent.lower().replace(" ", "_")
        if parent_key not in self.vocab["parents"]:
            self.vocab["parents"][parent_key] = parent

        key = name.lower().replace(" ", "_")
        if key in self.vocab["categories"]:
            self.vocab["categories"][key]["count"] += 1
        else:
            self.vocab["categories"][key] = {
                "parent": parent_key,
                "description": description,
                "count": 1,
            }
        self._save_vocab()

    def get_category_texts(self) -> List[str]:
        """返回所有类别描述文本 (用于 CLIP 匹配)."""
        return [
            info["description"]
            for info in self.vocab["categories"].values()
        ]

    # ─── CLIP 匹配 ───

    def _clip_match(self, image_crop: np.ndarray, candidates: List[str]) -> List[Tuple[str, float]]:
        """用 CLIP 匹配图像crop与候选文本.

        Returns: [(text, similarity), ...] 按相似度降序.
        """
        try:
            from edge.kitchen.inference.clip_infer import clip_match
            scores = clip_match(image_crop, candidates)
            ranked = sorted(
                zip(candidates, scores),
                key=lambda x: x[1],
                reverse=True,
            )
            return ranked
        except Exception:
            return [(c, 0.0) for c in candidates]

    # ─── 场景上下文 ───

    def _scene_context(self, zone: str) -> str:
        """根据区域推断父节点."""
        zone_map = {
            "备餐废弃区": "waste",
            "清洗区": "disorder",
            "烹饪区": "cookware",
            "传菜口": "tableware",
        }
        return zone_map.get(zone, "state")

    # ─── 核心: CR2T 轻量适配 ───

    def process(
        self,
        detections: List[dict],
        frame: np.ndarray,
        zone: str = "备餐废弃区",
        enable_vlm: bool = True,
    ) -> List[dict]:
        """处理 YOLO 检测结果，对低置信度目标做语义化.

        Args:
            detections: YOLO输出 [{"bbox":..., "confidence":..., "class":...}]
            frame: 原始帧 (用于 crop + CLIP)
            zone: 场景区域
            enable_vlm: 是否启用VLM生成未知标签

        Returns: 增强后的检测列表，含 "semantic_label" 和 "is_novel"
        """
        import cv2

        parent = self._scene_context(zone)
        parent_text = self.vocab["parents"].get(parent, parent)
        candidates = self.get_category_texts()

        results = []
        for det in detections:
            conf = det.get("confidence", 0)
            cls = det.get("class", -1)

            # 高置信度 → 直接通过
            if conf >= UNKNOWN_THRESH and cls >= 0:
                results.append({**det, "semantic_label": None, "is_novel": False})
                continue

            # 低置信度 → CR2T 轻量处理
            bbox = det["bbox"]
            x1, y1, x2, y2 = [int(v) for v in bbox[:4]]
            h, w = frame.shape[:2]
            crop = frame[max(0, y1):min(h, y2), max(0, x1):min(w, x2)]

            if crop.size == 0:
                results.append({**det, "semantic_label": "unknown", "is_novel": True})
                continue

            # Step 1: CLIP匹配已有类别
            matched = self._clip_match(crop, candidates)

            top_match, top_score = matched[0] if matched else ("unknown", 0)

            if top_score >= SIMILARITY_THRESH:
                # 匹配到已有类别 → 路由到该类别
                results.append({
                    **det,
                    "semantic_label": top_match,
                    "similarity": round(top_score, 3),
                    "is_novel": False,
                    "matched_category": top_match,
                })
            else:
                # 匹配不上 → 新类别
                label = "unknown"
                if enable_vlm:
                    label = self._vlm_describe(crop, parent_text)

                self.register_category(
                    name=label,
                    parent=parent,
                    description=label,
                )
                results.append({
                    **det,
                    "semantic_label": label,
                    "similarity": round(top_score, 3),
                    "is_novel": True,
                    "parent": parent,
                })

        return results

    def _vlm_describe(self, crop: np.ndarray, parent_text: str) -> str:
        """调用 VLM 描述未知目标."""
        try:
            from edge.kitchen.inference.vlm_infer import vlm_infer
            prompt = f"这是一个火锅后厨的{parent_text}场景。简短描述这个区域的内容（1-5个字）："
            result = vlm_infer(crop, prompt)
            return result.strip() if result else "unknown_item"
        except Exception:
            return "unknown_item"


# ─── Pipeline Stage ───

STAGE_NAME = "open_world"
STAGE_ORDER = 2  # 在 YOLO 之后, CLIP/VLM 之前

_adapter: Optional[OpenWorldAdapter] = None


def _get_adapter() -> OpenWorldAdapter:
    global _adapter
    if _adapter is None:
        _adapter = OpenWorldAdapter()
    return _adapter


def run(frame_path: str, ctx: dict) -> dict:
    """Stage: 开放世界语义化.

    读取 ctx["yolo_result"]["detections"]，为低置信度目标生成语义标签。
    """
    import cv2

    yolo = ctx.get("yolo_result", {})
    detections = yolo.get("detections", [])
    if not detections:
        return {"status": "skipped", "reason": "no_detections"}

    frame = cv2.imread(frame_path)
    if frame is None:
        return {"status": "error", "error": f"cannot read {frame_path}"}

    zone = ctx.get("zone", "备餐废弃区")

    t0 = time.time()
    adapter = _get_adapter()
    enriched = adapter.process(detections, frame, zone=zone, enable_vlm=True)
    dt = (time.time() - t0) * 1000

    novel_count = sum(1 for d in enriched if d.get("is_novel"))
    vocab_size = len(adapter.vocab["categories"])

    ctx["yolo_result"]["detections"] = enriched
    ctx["open_world"] = {
        "status": "ok",
        "novel_detections": novel_count,
        "vocab_size": vocab_size,
        "latency_ms": round(dt, 1),
    }

    return ctx["open_world"]
