#!/usr/bin/env python3
"""Generate synthetic demo images for hotpot PoC."""

from __future__ import annotations

import argparse
from pathlib import Path

import cv2
import numpy as np


def make_front_hall(path: Path, w: int = 1280, h: int = 720) -> None:
    img = np.ones((h, w, 3), dtype=np.uint8) * 40
    cols, rows = 4, 2
    states = ["empty", "dining", "need_clean", "checkout", "dining", "empty", "dining", "need_clean"]
    colors = {
        "empty": (80, 160, 80),
        "dining": (50, 90, 180),
        "need_clean": (30, 140, 200),
        "checkout": (50, 120, 220),
    }
    for r in range(rows):
        for c in range(cols):
            idx = r * cols + c
            x1 = int(c * w / cols + 10)
            y1 = int(r * h / rows + 20)
            x2 = int((c + 1) * w / cols - 10)
            y2 = int((r + 1) * h / rows - 20)
            st = states[idx]
            cv2.rectangle(img, (x1, y1), (x2, y2), colors[st], -1)
            cv2.rectangle(img, (x1, y1), (x2, y2), (200, 200, 200), 2)
            if st == "dining":
                cv2.circle(img, ((x1 + x2) // 2, (y1 + y2) // 2), 30, (30, 30, 30), -1)
            elif st == "need_clean":
                for _ in range(5):
                    px, py = np.random.randint(x1, x2), np.random.randint(y1, y2)
                    cv2.circle(img, (px, py), 8, (20, 20, 20), -1)
            cv2.putText(img, f"T{idx+1:02d}:{st}", (x1 + 10, y1 + 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
    cv2.putText(img, "Hotpot Front Hall Demo", (20, h - 20), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2)
    cv2.imwrite(str(path), img)


def make_kitchen(path: Path, w: int = 1280, h: int = 720) -> None:
    img = np.ones((h, w, 3), dtype=np.uint8) * 60
    # Stainless steel tone
    cv2.rectangle(img, (0, 0), (w, h), (90, 100, 110), -1)
    # Simulated smoke region (bright haze top)
    overlay = img.copy()
    cv2.rectangle(overlay, (200, 50), (900, 280), (220, 220, 230), -1)
    img = cv2.addWeighted(overlay, 0.5, img, 0.5, 0)
    # Person silhouette (skin tone proxy)
    cx, cy = w // 2, h // 2 + 50
    cv2.ellipse(img, (cx, cy - 80), (50, 60), 0, 0, 360, (100, 150, 200), -1)
    cv2.rectangle(img, (cx - 60, cy - 20), (cx + 60, cy + 180), (80, 80, 100), -1)
    cv2.putText(img, "Kitchen Demo (smoke + staff)", (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (255, 255, 255), 2)
    cv2.imwrite(str(path), img)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-dir", default=str(Path(__file__).resolve().parent / "data"))
    args = parser.parse_args()
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    make_front_hall(out / "front_hall.jpg")
    make_kitchen(out / "kitchen.jpg")
    print(f"[OK] Demo images written to {out}")


if __name__ == "__main__":
    main()
