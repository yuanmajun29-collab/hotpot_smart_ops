#!/usr/bin/env python3
"""生成逼真后厨场景测试图，直接喂给 Jetson VLM 全链路。

每张图模拟真实监控摄像头画面：噪点、模糊、时间戳水印、低光照偏色。
"""

import io
import os
import random
import uuid
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

OUT_DIR = Path(__file__).resolve().parent.parent / "test_images"
OUT_DIR.mkdir(parents=True, exist_ok=True)

W, H = 1280, 720  # 720p 监控分辨率

# ── 配色方案 ──
KITCHEN_FLOOR = (180, 175, 165)      # 暖灰瓷砖
STAINLESS_STEEL = (200, 200, 205)     # 不锈钢台面
CUTTING_BOARD = (210, 180, 140)       # 木砧板
MEAT_RED = (180, 60, 40)             # 红肉
MEAT_PALE = (200, 140, 120)          # 变质肉
VEG_GREEN = (80, 160, 60)            # 蔬菜绿
VEG_YELLOW = (180, 170, 60)          # 菜叶黄
OIL_STAIN = (140, 120, 80)           # 油渍
PLASTIC_BLUE = (100, 150, 200)       # 蓝色塑料筐
TRASH_BLACK = (50, 50, 50)           # 垃圾桶
BROTH_BROWN = (160, 90, 40)          # 火锅汤底
STEAM_WHITE = (240, 240, 245, 60)    # 蒸汽
CAMERA_TIMESTAMP_BG = (0, 0, 0, 160)


def noise_layer(img: Image.Image, intensity: float = 0.03) -> Image.Image:
    """模拟监控摄像头噪点。"""
    import numpy as np
    arr = np.array(img, dtype=np.float32)
    noise = np.random.normal(0, 255 * intensity, arr.shape).astype(np.float32)
    arr = np.clip(arr + noise, 0, 255).astype(np.uint8)
    return Image.fromarray(arr)


def camera_effect(img: Image.Image) -> Image.Image:
    """添加监控摄像头效果：轻微模糊、噪点、边角暗角。"""
    img = img.filter(ImageFilter.GaussianBlur(radius=0.6))
    img = noise_layer(img, intensity=0.02)

    # 暗角 vignette
    draw = ImageDraw.Draw(img, "RGBA")
    for i in range(6):
        alpha = 8
        draw.rectangle([i, i, W - i - 1, H - i - 1], outline=(0, 0, 0, alpha))
    # 四个角的径向暗角（简化）
    corners = [
        (0, 0, 180, 140),
        (W - 180, 0, W, 140),
        (0, H - 140, 180, H),
        (W - 180, H - 140, W, H),
    ]
    for cx, cy, cx2, cy2 in corners:
        for j in range(20):
            a = 6 - j // 4
            if a <= 0:
                break
            draw.rectangle(
                [cx + j, cy + j, cx2 - j, cy2 - j],
                fill=None,
                outline=(0, 0, 0, a),
            )

    return img


def timestamp_overlay(draw: ImageDraw.ImageDraw, zone: str) -> None:
    """监控时间戳水印。"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    text = f"玉环店 · {zone} · Cam01  {now}"

    # 背景条
    draw.rectangle([0, H - 36, W, H], fill=(0, 0, 0, 150))
    # 时间戳文字（白色）
    draw.text((12, H - 30), text, fill=(255, 255, 255))
    # 右上角 "REC" 红点
    draw.ellipse([W - 46, H - 28, W - 30, H - 12], fill=(220, 30, 30))
    draw.text((W - 26, H - 30), "REC", fill=(255, 255, 255))


def draw_stainless_table(draw: ImageDraw.ImageDraw, x: int, y: int, w: int, h: int) -> None:
    """不锈钢台面。"""
    draw.rectangle([x, y, x + w, y + h], fill=STAINLESS_STEEL)
    # 不锈钢拉丝效果
    for i in range(y + 4, y + h, 8):
        draw.line([x + 2, i, x + w - 2, i], fill=(190, 190, 195), width=1)


def draw_meat_piece(draw: ImageDraw.ImageDraw, cx: int, cy: int, r: int) -> None:
    """一片不规则肉片。"""
    pts = []
    for angle in range(0, 360, 20):
        rad = angle * 3.14159 / 180
        rr = r * (0.7 + 0.3 * random.random())
        pts.append((cx + int(rr * __import__("math").cos(rad)), cy + int(rr * __import__("math").sin(rad))))
    draw.polygon(pts, fill=MEAT_RED, outline=(140, 40, 30))


def draw_veg_leaf(draw: ImageDraw.ImageDraw, cx: int, cy: int, w: int, h: int, color=None) -> None:
    """一片菜叶。"""
    c = color or VEG_GREEN
    draw.ellipse([cx - w // 2, cy - h // 2, cx + w // 2, cy + h // 2], fill=c, outline=(c[0] - 30, c[1] - 30, c[2] - 30))
    # 叶脉
    draw.line([cx, cy - h // 2, cx, cy + h // 2], fill=(c[0] - 50, c[1] - 50, c[2] - 50), width=1)


def draw_oil_puddle(draw: ImageDraw.ImageDraw, cx: int, cy: int, r: int) -> None:
    """油渍/水渍。"""
    for i in range(r, 0, -2):
        alpha = 30 - i
        color = (OIL_STAIN[0], OIL_STAIN[1], OIL_STAIN[2], max(0, alpha))
        draw.ellipse([cx - i, cy - i // 2, cx + i, cy + i // 2], fill=color)


# ═══════════════════════════════════════════
# 场景生成
# ═══════════════════════════════════════════


def scene_01_waste_meat() -> Image.Image:
    """毛肚边角料 — 案板上散落已切好未加盖的毛肚片，周围有血迹。"""
    img = Image.new("RGB", (W, H), KITCHEN_FLOOR)
    draw = ImageDraw.Draw(img, "RGBA")

    # 背景墙
    draw.rectangle([0, 0, W, H // 2], fill=(230, 225, 215))
    # 不锈钢台面
    draw_stainless_table(draw, 150, 300, 980, 280)
    # 木砧板
    draw.rectangle([250, 360, 850, 520], fill=CUTTING_BOARD, outline=(160, 130, 90), width=3)

    # 大量边角料肉片散落
    import math, random as rnd
    rnd.seed(42)
    for _ in range(25):
        cx = rnd.randint(290, 810)
        cy = rnd.randint(380, 500)
        rr = rnd.randint(15, 40)
        pts = []
        for a in range(0, 360, 25):
            rad = a * math.pi / 180
            rv = rr * (0.6 + 0.4 * rnd.random())
            pts.append((cx + int(rv * math.cos(rad)), cy + int(rv * math.sin(rad))))
        color = (
            rnd.randint(140, 190),
            rnd.randint(35, 70),
            rnd.randint(25, 55),
        )
        draw.polygon(pts, fill=color, outline=(120, 30, 20))

    # 血迹
    for _ in range(8):
        cx = rnd.randint(280, 820)
        cy = rnd.randint(390, 510)
        for r in range(rnd.randint(5, 18), 0, -2):
            draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(160, 20, 20, 30))

    # 蓝色塑料筐（装"应该收掉"的肉）
    draw.rectangle([580, 440, 680, 510], fill=PLASTIC_BLUE, outline=(70, 120, 170), width=2)
    draw.text((590, 455), "毛肚", fill=(255, 255, 255))

    # 右下方垃圾桶
    draw.rectangle([930, 480, 1010, 560], fill=TRASH_BLACK, outline=(80, 80, 80))
    draw.text((945, 505), "废弃", fill=(200, 200, 200))

    # 油渍
    draw_oil_puddle(draw, 500, 440, 30)
    draw_oil_puddle(draw, 720, 400, 20)

    timestamp_overlay(draw, "备餐区")
    return camera_effect(img)


def scene_02_waste_veg() -> Image.Image:
    """蔬菜大量浪费 — 整框未用的蔬菜堆积，部分发黄变质。"""
    img = Image.new("RGB", (W, H), KITCHEN_FLOOR)
    draw = ImageDraw.Draw(img, "RGBA")

    draw.rectangle([0, 0, W, H // 3], fill=(240, 235, 225))
    draw.rectangle([0, H // 3, W, H], fill=(195, 190, 180))

    # 多个蓝色塑料筐堆叠
    box_positions = [
        (120, 350, 320, 480),
        (350, 340, 550, 470),
        (580, 360, 780, 490),
        (810, 370, 1010, 500),
    ]
    import random as rnd
    rnd.seed(7)
    labels = ["生菜", "菠菜", "油麦菜", "茼蒿"]
    for i, (x1, y1, x2, y2) in enumerate(box_positions):
        draw.rectangle([x1, y1, x2, y2], fill=PLASTIC_BLUE, outline=(80, 130, 180), width=2)
        # 筐内蔬菜 —— 部分绿色部分发黄
        for _ in range(20):
            lx = rnd.randint(x1 + 15, x2 - 15)
            ly = rnd.randint(y1 + 15, y2 - 15)
            if rnd.random() < 0.4:
                color = VEG_YELLOW  # 变质发黄
            else:
                color = VEG_GREEN
            w = rnd.randint(15, 35)
            h = rnd.randint(8, 20)
            draw_veg_leaf(draw, lx, ly, w, h, color)
        draw.text((x1 + 10, y1 + 5), labels[i], fill=(255, 255, 255))

    # 地面散落菜叶
    for _ in range(15):
        lx = rnd.randint(50, 1150)
        ly = rnd.randint(510, 680)
        draw_veg_leaf(draw, lx, ly, rnd.randint(20, 45), rnd.randint(10, 25),
                       VEG_YELLOW if rnd.random() < 0.5 else VEG_GREEN)

    # 油渍地面
    for _ in range(4):
        draw_oil_puddle(draw, rnd.randint(100, 1100), rnd.randint(520, 670), rnd.randint(15, 35))

    timestamp_overlay(draw, "洗菜区")
    return camera_effect(img)


def scene_03_over_production() -> Image.Image:
    """过量备菜 — 已装盘的菜品堆积，超过需求，即将打烊仍未消耗。"""
    img = Image.new("RGB", (W, H), KITCHEN_FLOOR)
    draw = ImageDraw.Draw(img, "RGBA")

    draw.rectangle([0, 0, W, H // 2], fill=(235, 230, 220))
    draw.rectangle([0, H // 2, W, H], fill=(200, 195, 185))

    # 传送带式长台面
    draw_stainless_table(draw, 40, 340, 1200, 200)

    import random as rnd
    rnd.seed(2024)
    # 一排装好盘的菜
    plate_colors = [(250, 250, 245), (240, 235, 225), (245, 240, 230)]
    for i in range(12):
        px = 70 + i * 90
        py = 400
        # 盘子
        draw.ellipse([px - 30, py - 15, px + 30, py + 15], fill=rnd.choice(plate_colors), outline=(180, 175, 165))
        # 盘上食物
        food_color = rnd.choice([MEAT_RED, (200, 160, 90), VEG_GREEN])
        for _ in range(5):
            fx = rnd.randint(px - 20, px + 20)
            fy = rnd.randint(py - 10, py + 10)
            draw.ellipse([fx - 5, fy - 3, fx + 5, fy + 3], fill=food_color)

    # "待上菜" 标签
    draw.rectangle([460, 310, 620, 335], fill=(220, 40, 40))
    draw.text((478, 313), "⚠ 过量备菜 · 打烊未消耗", fill=(255, 255, 255))

    # 下方堆叠的备菜筐
    for i in range(4):
        bx = 100 + i * 240
        draw.rectangle([bx, 520, bx + 180, 620], fill=PLASTIC_BLUE, outline=(80, 130, 180), width=2)
        draw.text((bx + 60, 560), f"备菜×{rnd.randint(8,15)}", fill=(255, 255, 255))

    timestamp_overlay(draw, "出菜口")
    return camera_effect(img)


def scene_04_expired() -> Image.Image:
    """鸭肠过期 — 真空包装鸭肠颜色暗沉发粘，与新鲜品对比明显。"""
    img = Image.new("RGB", (W, H), KITCHEN_FLOOR)
    draw = ImageDraw.Draw(img, "RGBA")

    draw.rectangle([0, 0, W, H // 2], fill=(225, 220, 210))
    draw_stainless_table(draw, 80, 300, 1120, 350)

    import random as rnd
    rnd.seed(99)

    # 左边：新鲜鸭肠
    draw.text((140, 270), "✓ 新鲜 (当日)", fill=(40, 160, 40))
    draw.rectangle([120, 340, 400, 500], fill=(255, 255, 250), outline=(80, 180, 80), width=3)
    # 新鲜鸭肠 — 粉色偏白
    for _ in range(30):
        cx = rnd.randint(140, 380)
        cy = rnd.randint(360, 480)
        rnd_len = rnd.randint(20, 50)
        angle = rnd.random() * 6.28
        pts = []
        for t in range(6):
            tt = t / 5
            px = cx + int(rnd_len * (tt - 0.5) * 2 * __import__("math").cos(angle))
            py = cy + int(rnd_len * (tt - 0.5) * 2 * __import__("math").sin(angle)) + rnd.randint(-5, 5)
            pts.append((px, py))
        color = (rnd.randint(225, 245), rnd.randint(170, 195), rnd.randint(155, 180))
        draw.line(pts, fill=color, width=rnd.randint(3, 6))

    # 右边：过期鸭肠
    draw.text((700, 270), "✗ 过期 (3天前)", fill=(200, 40, 40))
    draw.rectangle([680, 340, 980, 500], fill=(250, 245, 240), outline=(200, 40, 40), width=3)
    for _ in range(30):
        cx = rnd.randint(700, 960)
        cy = rnd.randint(360, 480)
        rnd_len = rnd.randint(20, 50)
        angle = rnd.random() * 6.28
        pts = []
        for t in range(6):
            tt = t / 5
            px = cx + int(rnd_len * (tt - 0.5) * 2 * __import__("math").cos(angle))
            py = cy + int(rnd_len * (tt - 0.5) * 2 * __import__("math").sin(angle)) + rnd.randint(-5, 5)
            pts.append((px, py))
        color = (rnd.randint(130, 170), rnd.randint(90, 120), rnd.randint(70, 95))  # 暗沉
        draw.line(pts, fill=color, width=rnd.randint(3, 6))

    # 粘液光泽效果
    for _ in range(10):
        cx = rnd.randint(700, 960)
        cy = rnd.randint(370, 470)
        draw.ellipse([cx - 6, cy - 2, cx + 6, cy + 2], fill=(180, 180, 190, 50))

    # 警示标签
    draw.rectangle([670, 310, 990, 335], fill=(220, 30, 30))
    draw.text((720, 313), "⛔ 过期食材 · 已变色发粘", fill=(255, 255, 255))

    # "废弃" 红叉
    draw.line([960, 340, 990, 510], fill=(255, 0, 0), width=4)
    draw.line([990, 340, 960, 510], fill=(255, 0, 0), width=4)

    timestamp_overlay(draw, "冷库出库")
    return camera_effect(img)


def scene_05_overflow() -> Image.Image:
    """溢锅场景 — 火锅沸腾溢出，汤汁流到台面，周围蒸汽弥漫。"""
    img = Image.new("RGB", (W, H), KITCHEN_FLOOR)
    draw = ImageDraw.Draw(img, "RGBA")

    draw.rectangle([0, 0, W, H // 2], fill=(220, 215, 205))
    draw_stainless_table(draw, 200, 350, 880, 300)

    import random as rnd
    rnd.seed(33)
    # 炉灶
    draw.rectangle([460, 390, 620, 400], fill=(80, 80, 85))  # 灶台
    draw.ellipse([440, 360, 640, 420], fill=(60, 60, 65))     # 炉圈

    # 火锅锅具
    draw.ellipse([420, 340, 660, 430], fill=(120, 170, 180), outline=(80, 130, 140), width=4)
    # 锅内汤底
    draw.ellipse([440, 365, 640, 415], fill=BROTH_BROWN)
    # 沸腾气泡
    for _ in range(12):
        bx = rnd.randint(460, 620)
        by = rnd.randint(375, 405)
        br = rnd.randint(3, 10)
        draw.ellipse([bx - br, by - br, bx + br, by + br], fill=(200, 150, 100), outline=(140, 90, 50))

    # 溢出的汤汁 — 从锅边流向台面
    spill_paths = [
        [(640, 390), (680, 400), (720, 410), (760, 430)],
        [(420, 380), (380, 395), (340, 415), (300, 440)],
        [(540, 430), (530, 460), (520, 490), (510, 520)],
    ]
    for path in spill_paths:
        for i in range(len(path) - 1):
            x1, y1 = path[i]
            x2, y2 = path[i + 1]
            draw.line([x1, y1, x2, y2], fill=BROTH_BROWN, width=rnd.randint(8, 18))
        # 末端水洼
        ex, ey = path[-1]
        for r in range(35, 0, -3):
            alpha = max(0, 25 - r // 3)
            draw.ellipse([ex - r, ey - r // 2, ex + r, ey + r // 2], fill=(BROTH_BROWN[0], BROTH_BROWN[1], BROTH_BROWN[2], alpha))

    # 蒸汽（半透明白色椭圆）
    for _ in range(20):
        sx = rnd.randint(440, 640)
        sy = rnd.randint(310, 360)
        sw = rnd.randint(20, 60)
        sh = rnd.randint(15, 40)
        draw.ellipse([sx - sw // 2, sy - sh, sx + sw // 2, sy], fill=STEAM_WHITE)

    # 红色警报标签
    draw.rectangle([420, 280, 660, 310], fill=(220, 30, 30))
    draw.text((450, 283), "⚠ 溢锅告警 · 汤液外流", fill=(255, 255, 255))

    timestamp_overlay(draw, "后厨灶台")
    return camera_effect(img)


def scene_06_unserved_return() -> Image.Image:
    """空盘回收区 — 大量未吃就回收的菜品，整盘浪费。"""
    img = Image.new("RGB", (W, H), KITCHEN_FLOOR)
    draw = ImageDraw.Draw(img, "RGBA")

    draw.rectangle([0, 0, W, H // 2], fill=(210, 205, 195))
    draw.rectangle([0, H // 2, W, H], fill=(185, 180, 170))

    # 回收台
    draw_stainless_table(draw, 40, 380, 1200, 300)

    import random as rnd
    rnd.seed(55)
    # 大量回收盘，盘中食物几乎没动
    for i in range(18):
        px = 80 + (i % 6) * 180
        py = 420 + (i // 6) * 100
        # 盘子
        draw.ellipse([px - 35, py - 18, px + 35, py + 18], fill=(245, 240, 230), outline=(170, 165, 155))
        # 盘上食物（大量）
        food_type = rnd.choice(["meat", "veg", "mixed"])
        for _ in range(rnd.randint(6, 14)):
            fx = rnd.randint(px - 28, px + 28)
            fy = rnd.randint(py - 12, py + 12)
            if food_type == "meat":
                draw.ellipse([fx - 6, fy - 4, fx + 6, fy + 4], fill=MEAT_RED)
            elif food_type == "veg":
                draw.ellipse([fx - 5, fy - 3, fx + 5, fy + 3], fill=VEG_GREEN)
            else:
                draw.ellipse([fx - 5, fy - 4, fx + 5, fy + 4], fill=rnd.choice([MEAT_RED, VEG_GREEN, (200, 160, 100)]))

    # "未食用回收" 标签
    draw.rectangle([30, 330, 300, 360], fill=(220, 140, 40))
    draw.text((50, 333), "🍽 回收区 · 超 60% 未食用", fill=(255, 255, 255))

    # 垃圾桶
    draw.rectangle([1080, 480, 1180, 600], fill=TRASH_BLACK, outline=(90, 90, 90))
    for _ in range(8):
        tx = rnd.randint(1085, 1175)
        ty = rnd.randint(490, 580)
        draw.ellipse([tx - 8, ty - 4, tx + 8, ty + 4], fill=MEAT_RED)

    # 计数器
    draw.rectangle([900, 310, 1180, 355], fill=(40, 40, 40))
    draw.text((920, 318), f"本班次回收: {rnd.randint(23, 45)} 盘", fill=(255, 200, 80))
    draw.text((920, 338), f"估算损耗: ¥{rnd.randint(380, 920)}", fill=(255, 100, 80))

    timestamp_overlay(draw, "回收区")
    return camera_effect(img)


# ═══════════════════════════════════════════
# 主流程
# ═══════════════════════════════════════════

SCENES = {
    "01_waste_meat": ("毛肚边角料 · 备餐区", scene_01_waste_meat),
    "02_waste_veg": ("蔬菜大量浪费 · 洗菜区", scene_02_waste_veg),
    "03_over_production": ("过量备菜未消耗 · 出菜口", scene_03_over_production),
    "04_expired": ("鸭肠过期变质 · 冷库出库", scene_04_expired),
    "05_overflow": ("火锅溢锅 · 后厨灶台", scene_05_overflow),
    "06_unserved_return": ("未食用回收 · 回收区", scene_06_unserved_return),
}


def main():
    print(f"🎬 生成 {len(SCENES)} 张后厨场景图 → {OUT_DIR}\n")
    for key, (desc, gen_fn) in SCENES.items():
        img = gen_fn()
        fname = f"scene_{key}.jpg"
        fpath = OUT_DIR / fname
        img.save(fpath, "JPEG", quality=92)
        size_kb = fpath.stat().st_size / 1024
        print(f"  ✅ {fname}  ({size_kb:.0f} KB)  — {desc}")

    print(f"\n📦 共 {len(SCENES)} 张，保存于 {OUT_DIR}")

    # 生成上传脚本
    upload_py = OUT_DIR.parent / "scripts" / "upload_test_images.py"
    upload_content = f'''#!/usr/bin/env python3
"""将 test_images/ 图片 base64 上传到 Hub 图床，并推送到 VLM 链路。"""

import base64, json, os, sys
from pathlib import Path
from urllib import request, error

HUB = os.environ.get("HUB_URL", "http://127.0.0.1:8098")
API_KEY = os.environ.get("HOTPOT_API_KEY", "edge_yuhuan_dev_key")
IMAGES_DIR = Path(__file__).resolve().parent.parent / "test_images"

SCENES = {json.dumps({k: d for k, (d, _) in SCENES.items()}, ensure_ascii=False, indent=2)}


def upload_image(fpath: Path) -> dict:
    with open(fpath, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()

    body = json.dumps({{
        "store_id": "yuhuan",
        "zone": "kitchen",
        "camera_id": "cam01",
        "image_base64": b64,
    }}).encode()
    req = request.Request(
        f"{{HUB}}/v1/images",
        data=body,
        headers={{"Content-Type": "application/json", "X-Api-Key": API_KEY}},
    )
    with request.urlopen(req) as resp:
        return json.loads(resp.read())


def push_waste_estimate(image_ref: str, items: list[dict] | None = None) -> dict:
    body = {{
        "store_id": "yuhuan",
        "zone": "kitchen",
        "image_ref": image_ref,
        "stream_id": "cam01",
        "source": "vlm-edge" if items else "mock",
        "model": "ostrakon-vl-8b" if items else "mock-rule",
    }}
    if items:
        body["items"] = items

    data = json.dumps(body).encode()
    req = request.Request(
        f"{{HUB}}/v1/vlm/waste-estimate",
        data=data,
        headers={{"Content-Type": "application/json", "X-Api-Key": API_KEY}},
    )
    with request.urlopen(req) as resp:
        return json.loads(resp.read())


def main():
    print(f"🔗 Hub: {{HUB}}\\n")

    for fname in sorted(IMAGES_DIR.glob("scene_*.jpg")):
        key = fname.stem.replace("scene_", "")
        desc = SCENES.get(key, "未知")

        print(f"📤 上传: {{fname.name}} — {{desc}}")
        try:
            result = upload_image(fname)
            url = result.get("url", "")
            print(f"   ✅ {{url}}")

            # 推送 VLM（先走 mock 验证链路通）
            vlm = push_waste_estimate(url)
            print(f"   🧠 VLM: event_id={{vlm.get('event_id','?')}} items={{len(vlm.get('items',[]))}}")
        except error.HTTPError as e:
            print(f"   ❌ HTTP {{e.code}}: {{e.reason}}")
        except error.URLError as e:
            print(f"   ❌ 连接失败: {{e.reason}}")
            print("   💡 请先启动 Hub: bash scripts/start_all.sh")
            sys.exit(1)

    print(f"\\n✅ 完成。Dashboard: http://127.0.0.1:3099/vlm-demo.html")


if __name__ == "__main__":
    main()
'''
    upload_py.parent.mkdir(parents=True, exist_ok=True)
    upload_py.write_text(upload_content)
    print(f"\n📝 上传脚本已生成: {upload_py}")


if __name__ == "__main__":
    main()
