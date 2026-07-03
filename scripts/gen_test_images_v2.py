#!/usr/bin/env python3
"""
生成逼真后厨场景测试图 — 模拟备餐区监控摄像头画面 v2
比 v1 提升：不锈钢渐变台面、食材有机形状、阴影光照、JPEG噪点、摄像头OSD叠加
"""
import os, random, math, datetime
from PIL import Image, ImageDraw, ImageFilter, ImageEnhance, ImageFont

OUT = os.path.expanduser("~/company/hotpot_smart_ops/test_images")
os.makedirs(OUT, exist_ok=True)

W, H = 1280, 720
SEED = 42
random.seed(SEED)

# ── 字体 ──
FONT = FONT_SM = FONT_XS = None
for f in ["/System/Library/Fonts/STHeiti Light.ttc",
          "/System/Library/Fonts/PingFang.ttc",
          "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"]:
    if os.path.exists(f):
        FONT = ImageFont.truetype(f, 24)
        FONT_SM = ImageFont.truetype(f, 16)
        FONT_XS = ImageFont.truetype(f, 13)
        break


def _lerp(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def _brighten(c, amt):
    return tuple(min(255, c[i] + amt) for i in range(3))


def _darken(c, amt):
    return tuple(max(0, c[i] - amt) for i in range(3))


def _random_point_in_ellipse(cx, cy, rx, ry):
    """均匀分布在椭圆内的随机点"""
    angle = random.uniform(0, 2 * math.pi)
    r = math.sqrt(random.random())  # sqrt 保证均匀
    return (int(cx + r * rx * math.cos(angle)),
            int(cy + r * ry * math.sin(angle)))


def draw_stainless_table(draw, img):
    """绘制不锈钢操作台面 — 水平渐变 + 反光带"""
    table_top = H - 260
    # 主台面：深灰→中灰渐变
    for y in range(table_top, H):
        t = (y - table_top) / (H - table_top)
        c = _lerp((70, 65, 58), (110, 105, 95), t)
        draw.line([(0, y), (W, y)], fill=c)

    # 台面边缘高光线
    draw.line([(0, table_top), (W, table_top)], fill=(160, 155, 145), width=3)
    draw.line([(0, table_top + 2), (W, table_top + 2)], fill=(180, 175, 165), width=1)

    # 不锈钢反光带（横向条纹）
    for i in range(3):
        sy = table_top + 40 + i * 60
        for y in range(sy, sy + 8):
            alpha = 40 - abs(y - sy - 4) * 10
            if alpha > 0:
                c = _brighten((100, 95, 85), alpha)
                draw.line([(0, y), (W, y)], fill=c)

    # 台面下阴影
    for y in range(table_top - 20, table_top):
        alpha = int((y - table_top + 20) * 6)
        draw.line([(0, y), (W, y)], fill=(25, 20, 15, alpha))


def draw_tile_wall(draw, img):
    """绘制瓷砖墙壁 — 浅灰瓷砖 + 填缝线"""
    tile_h, tile_w = 90, 140
    grout = (55, 48, 42)
    for row in range(0, H - 260, tile_h):
        offset = (row // tile_h % 2) * (tile_w // 2)
        for col in range(-1, W // tile_w + 2):
            x = col * tile_w + offset
            y = row
            # 瓷砖主体 — 带微小随机色差
            r_var = random.randint(-5, 5)
            tile_color = (175 + r_var, 168 + r_var, 158 + r_var)
            draw.rectangle([(x + 1, y + 1), (x + tile_w - 2, y + tile_h - 2)],
                           fill=tile_color)
            # 填缝线
            draw.rectangle([(x, y), (x + tile_w, y + tile_h)],
                           outline=grout, width=1)

    # 墙壁底部踢脚线
    wall_bottom = H - 260
    draw.rectangle([(0, wall_bottom - 15), (W, wall_bottom)], fill=(45, 40, 35))
    draw.line([(0, wall_bottom - 15), (W, wall_bottom - 15)], fill=(80, 75, 65), width=2)


def draw_metal_tray(draw, x, y, w, h):
    """绘制不锈钢托盘 — 圆角 + 渐变 + 内阴影"""
    # 阴影
    shadow_rect = [(x + 6, y + 6), (x + w + 6, y + h + 6)]
    draw.rounded_rectangle(shadow_rect, radius=14, fill=(20, 18, 15, 120))

    # 托盘主体
    for dy in range(h):
        t = dy / h
        c = _lerp((95, 90, 80), (130, 125, 115), t)
        draw.rounded_rectangle([(x, y + dy), (x + w, y + dy + 1)],
                               radius=14, fill=c)

    # 边框
    draw.rounded_rectangle([(x, y), (x + w, y + h)], radius=14,
                           outline=(150, 145, 135), width=2)
    # 内高光
    draw.rounded_rectangle([(x + 4, y + 4), (x + w - 4, y + h - 4)],
                           radius=10, outline=(170, 165, 155), width=1)


def draw_food_item(draw, cx, cy, rx, ry, base_color, label=None):
    """绘制单个食材 — 椭圆主体 + 纹理斑点 + 高光"""
    # 主体 — 多层叠加模拟体积感
    for layer in range(3):
        lr = rx - layer * 3
        lry = ry - layer * 3
        if lr < 5 or lry < 5:
            break
        c = _brighten(base_color, (2 - layer) * 15)
        draw.ellipse([(cx - lr, cy - lry), (cx + lr, cy + lry)], fill=c)

    # 纹理斑点（模拟肉纹理/菜叶脉络）
    for _ in range(random.randint(8, 20)):
        px, py = _random_point_in_ellipse(cx, cy, rx * 0.9, ry * 0.9)
        spot_r = random.randint(3, 8)
        spot_c = _darken(base_color, random.randint(20, 50))
        draw.ellipse([(px - spot_r, py - spot_r), (px + spot_r, py + spot_r)],
                     fill=spot_c)

    # 高光点
    hl_x = int(cx - rx * 0.3 + random.randint(-5, 5))
    hl_y = int(cy - ry * 0.3 + random.randint(-3, 3))
    for hl_r in [4, 3, 2]:
        draw.ellipse([(hl_x - hl_r, hl_y - hl_r), (hl_x + hl_r, hl_y + hl_r)],
                     fill=(255, 255, 255, 100))

    # 阴影在底部
    shadow_ellipse = [(cx - rx - 3, cy + ry - 5), (cx + rx + 3, cy + ry + 8)]
    draw.ellipse(shadow_ellipse, fill=(15, 12, 10, 80))


def draw_leafy_item(draw, cx, cy, rx, ry, base_color):
    """绘制叶片状食材 — 不规则形状"""
    points = []
    n_points = 12
    for i in range(n_points):
        angle = 2 * math.pi * i / n_points
        r_var = random.uniform(0.7, 1.3)
        px = int(cx + rx * r_var * math.cos(angle))
        py = int(cy + ry * r_var * math.sin(angle))
        points.append((px, py))
    draw.polygon(points, fill=base_color)

    # 叶脉
    mid_vein = [(cx, cy - ry // 2), (cx, cy + ry // 2)]
    draw.line(mid_vein, fill=_darken(base_color, 30), width=2)

    # 侧脉
    for i in range(3):
        t = 0.3 + i * 0.2
        vy = int(cy - ry // 2 + ry * t)
        vx_start = cx
        for side in [-1, 1]:
            vx_end = int(cx + side * rx * 0.7)
            draw.line([(vx_start, vy), (vx_end, vy)],
                      fill=_darken(base_color, 20), width=1)


def draw_meat_slice(draw, cx, cy, rx, ry, meat_type="beef"):
    """绘制肉片 — 不规则椭圆 + 脂肪纹理"""
    colors = {
        "beef": (170, 50, 45),
        "pork": (195, 130, 110),
        "lamb": (165, 60, 50),
        "tripe": (190, 175, 155),
        "intestine": (195, 140, 110),
    }
    base = colors.get(meat_type, (180, 80, 60))

    # 主体
    draw.ellipse([(cx - rx, cy - ry), (cx + rx, cy + ry)], fill=base)

    # 脂肪纹路（白/浅色线条）
    for _ in range(random.randint(4, 8)):
        sx = cx + random.randint(-rx // 2, rx // 2)
        sy = cy + random.randint(-ry // 2, ry // 2)
        ex = sx + random.randint(-rx // 3, rx // 3)
        ey = sy + random.randint(-ry // 3, ry // 3)
        fat_color = (240, 230, 210) if meat_type != "tripe" else (210, 200, 185)
        draw.line([(sx, sy), (ex, ey)], fill=fat_color, width=random.randint(1, 3))

    # 边缘焦色
    draw.ellipse([(cx - rx + 2, cy - ry + 2), (cx + rx + 2, cy + ry + 2)],
                 fill=None, outline=(60, 20, 15), width=1)

    # 高光
    hl_x, hl_y = cx - rx // 3, cy - ry // 3
    draw.ellipse([(hl_x - 5, hl_y - 3), (hl_x + 5, hl_y + 3)],
                 fill=(255, 220, 200, 60))


def draw_camera_overlay(draw, scene_name, scene_desc):
    """绘制监控相机OSD叠加层"""
    # 左上角 — 通道名称
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    draw.rectangle([(10, 10), (200, 55)], fill=(0, 0, 0, 180))
    if FONT_SM:
        draw.text((16, 14), f"📷 CH01 备餐废弃区", fill=(255, 255, 255), font=FONT_SM)

    # 右上角 — 时间戳
    draw.rectangle([(W - 270, 10), (W - 10, 55)], fill=(0, 0, 0, 180))
    if FONT_SM:
        draw.text((W - 260, 14), ts, fill=(200, 200, 200), font=FONT_SM)
        draw.text((W - 260, 34), "玉环店 · 后厨 · 备餐区", fill=(150, 150, 150), font=FONT_XS)

    # 底部信息条
    draw.rectangle([(0, H - 32), (W, H)], fill=(0, 0, 0, 200))
    if FONT_XS:
        draw.text((12, H - 26), f"CH01 | 1920×1080 | 25fps | {scene_desc}",
                  fill=(180, 180, 180), font=FONT_XS)

    # 录像指示红点
    draw.ellipse([(W - 25, 48), (W - 15, 58)], fill=(255, 40, 40))
    draw.ellipse([(W - 23, 50), (W - 17, 56)], fill=(255, 80, 80))


def add_camera_noise(img):
    """添加监控相机噪声 — 轻微高斯模糊 + 噪点"""
    img = img.filter(ImageFilter.GaussianBlur(radius=0.5))

    # 轻微随机噪点
    pixels = img.load()
    for _ in range(W * H // 50):
        x = random.randint(0, W - 1)
        y = random.randint(0, H - 1)
        r, g, b = pixels[x, y]
        noise = random.randint(-12, 12)
        pixels[x, y] = (max(0, min(255, r + noise)),
                        max(0, min(255, g + noise)),
                        max(0, min(255, b + noise)))

    # 轻微降低饱和度（监控相机特征）
    enhancer = ImageEnhance.Color(img)
    img = enhancer.enhance(0.85)
    # 略微提亮暗部
    enhancer = ImageEnhance.Brightness(img)
    img = enhancer.enhance(1.05)

    return img


def create_scene(filename, scene_name, scene_desc, food_items):
    """创建完整场景"""
    img = Image.new("RGBA", (W, H), (15, 12, 10, 255))
    draw = ImageDraw.Draw(img)

    # 1. 瓷砖墙壁
    draw_tile_wall(draw, img)
    # 2. 不锈钢台面
    draw_stainless_table(draw, img)
    # 3. 不锈钢托盘
    tray_y = H - 250
    draw_metal_tray(draw, 80, tray_y, 520, 230)
    draw_metal_tray(draw, 650, tray_y, 500, 230)

    # 4. 食材
    for item in food_items:
        kind = item.get("kind", "food")
        cx, cy = item["cx"], item["cy"]
        rx, ry = item["rx"], item["ry"]
        color = item["color"]
        label = item.get("label")

        if kind == "meat":
            meat_type = item.get("meat_type", "beef")
            draw_meat_slice(draw, cx, cy, rx, ry, meat_type)
        elif kind == "leafy":
            draw_leafy_item(draw, cx, cy, rx, ry, color)
        else:
            draw_food_item(draw, cx, cy, rx, ry, color)

        # 标签
        if label and FONT_XS:
            lx = cx - len(label) * 4
            ly = cy + ry + 4
            # 标签背景
            tw = len(label) * 10 + 8
            draw.rectangle([(lx - 2, ly - 1), (lx + tw, ly + 16)],
                           fill=(0, 0, 0, 180))
            draw.text((lx + 2, ly), label, fill=(255, 255, 200), font=FONT_XS)

    # 5. 摄像头OSD
    draw_camera_overlay(draw, scene_name, scene_desc)

    # 6. 转为RGB + 加噪声
    img = img.convert("RGB")
    img = add_camera_noise(img)

    path = os.path.join(OUT, filename)
    img.save(path, quality=92)
    print(f"✓ {filename} ({scene_name}): {scene_desc}")
    return path


# ═══════════════════════════════════════════
# 6 个场景定义
# ═══════════════════════════════════════════

scenes = [
    # 场景1：肉类边角料损耗
    ("scene_01_waste_meat.jpg", "waste_meat", "肉类边角料·毛肚+鸭肠+牛百叶", [
        {"kind": "meat", "meat_type": "tripe", "cx": 200, "cy": 520, "rx": 65, "ry": 30,
         "color": (190, 175, 155), "label": "毛肚边角"},
        {"kind": "meat", "meat_type": "intestine", "cx": 350, "cy": 550, "rx": 70, "ry": 25,
         "color": (195, 140, 110), "label": "鸭肠"},
        {"kind": "meat", "meat_type": "beef", "cx": 250, "cy": 590, "rx": 55, "ry": 35,
         "color": (170, 50, 45), "label": "牛百叶"},
        {"kind": "meat", "meat_type": "tripe", "cx": 400, "cy": 510, "rx": 50, "ry": 28,
         "color": (190, 175, 155), "label": "毛肚碎"},
    ]),

    # 场景2：蔬菜腐烂损耗
    ("scene_02_waste_veg.jpg", "waste_veg", "蔬菜损耗·发黄生菜+菠菜+氧化土豆", [
        {"kind": "leafy", "cx": 250, "cy": 530, "rx": 70, "ry": 40,
         "color": (160, 180, 60), "label": "发黄生菜"},
        {"kind": "leafy", "cx": 480, "cy": 550, "rx": 60, "ry": 35,
         "color": (80, 150, 55), "label": "菠菜"},
        {"kind": "food", "cx": 350, "cy": 600, "rx": 45, "ry": 35,
         "color": (140, 130, 60), "label": "氧化土豆"},
        {"kind": "leafy", "cx": 150, "cy": 580, "rx": 50, "ry": 30,
         "color": (170, 160, 70), "label": "发蔫生菜"},
    ]),

    # 场景3：混合损耗（肉+菜混放）
    ("scene_03_waste_mixed.jpg", "waste_mixed", "混合损耗·边角肉+发黄菜混放", [
        {"kind": "meat", "meat_type": "tripe", "cx": 230, "cy": 510, "rx": 55, "ry": 28,
         "color": (190, 175, 155), "label": "毛肚边角"},
        {"kind": "leafy", "cx": 400, "cy": 520, "rx": 55, "ry": 35,
         "color": (160, 170, 55), "label": "发黄生菜"},
        {"kind": "meat", "meat_type": "intestine", "cx": 300, "cy": 570, "rx": 60, "ry": 22,
         "color": (195, 140, 110), "label": "过期鸭肠"},
        {"kind": "food", "cx": 450, "cy": 590, "rx": 40, "ry": 32,
         "color": (130, 120, 55), "label": "氧化土豆"},
        {"kind": "meat", "meat_type": "beef", "cx": 180, "cy": 590, "rx": 50, "ry": 30,
         "color": (120, 35, 30), "label": "变色牛肉"},
    ]),

    # 场景4：备餐过量（大量剩余）
    ("scene_04_over_production.jpg", "over_production", "备餐过量·双盘大量剩余食材", [
        # 左盘 — 大量肉
        {"kind": "meat", "meat_type": "beef", "cx": 180, "cy": 500, "rx": 55, "ry": 32,
         "color": (170, 50, 45), "label": "肥牛1"},
        {"kind": "meat", "meat_type": "beef", "cx": 280, "cy": 510, "rx": 60, "ry": 30,
         "color": (170, 50, 45), "label": "肥牛2"},
        {"kind": "meat", "meat_type": "pork", "cx": 380, "cy": 500, "rx": 50, "ry": 28,
         "color": (195, 130, 110), "label": "午餐肉"},
        {"kind": "meat", "meat_type": "beef", "cx": 230, "cy": 560, "rx": 55, "ry": 30,
         "color": (160, 45, 40), "label": "肥牛3"},
        {"kind": "meat", "meat_type": "pork", "cx": 340, "cy": 570, "rx": 50, "ry": 25,
         "color": (195, 130, 110), "label": "午餐肉2"},
        # 右盘 — 大量蔬菜
        {"kind": "leafy", "cx": 750, "cy": 500, "rx": 55, "ry": 35,
         "color": (100, 170, 70), "label": "生菜"},
        {"kind": "leafy", "cx": 880, "cy": 510, "rx": 50, "ry": 30,
         "color": (90, 160, 60), "label": "菠菜"},
        {"kind": "food", "cx": 810, "cy": 560, "rx": 45, "ry": 35,
         "color": (180, 170, 70), "label": "土豆片"},
        {"kind": "leafy", "cx": 910, "cy": 570, "rx": 40, "ry": 28,
         "color": (130, 160, 55), "label": "娃娃菜"},
    ]),

    # 场景5：疑似过期（颜色发暗）
    ("scene_05_expired.jpg", "expired", "疑似过期·颜色异常发暗肉类", [
        {"kind": "meat", "meat_type": "beef", "cx": 220, "cy": 520, "rx": 60, "ry": 32,
         "color": (80, 25, 20), "label": "发黑牛肉"},
        {"kind": "meat", "meat_type": "intestine", "cx": 380, "cy": 530, "rx": 65, "ry": 24,
         "color": (130, 90, 75), "label": "变色鸭肠"},
        {"kind": "meat", "meat_type": "pork", "cx": 280, "cy": 580, "rx": 55, "ry": 28,
         "color": (140, 90, 75), "label": "发暗午餐肉"},
        {"kind": "meat", "meat_type": "tripe", "cx": 430, "cy": 590, "rx": 50, "ry": 26,
         "color": (140, 130, 110), "label": "变色毛肚"},
    ]),

    # 场景6：清洁备餐（少量正常食材）
    ("scene_06_clean.jpg", "clean", "标准备餐·少量正常食材整齐摆放", [
        {"kind": "meat", "meat_type": "beef", "cx": 280, "cy": 540, "rx": 50, "ry": 28,
         "color": (180, 60, 50), "label": "肥牛卷"},
        {"kind": "leafy", "cx": 440, "cy": 540, "rx": 45, "ry": 30,
         "color": (70, 155, 55), "label": "生菜"},
        {"kind": "food", "cx": 600, "cy": 540, "rx": 40, "ry": 32,
         "color": (190, 180, 60), "label": "土豆片"},
    ]),
]

# ── 生成 ──
print("🎬 生成逼真后厨场景测试图...\n")
for fn, sn, sd, items in scenes:
    create_scene(fn, sn, sd, items)

print(f"\n✅ {len(scenes)} 张测试图已生成 → {OUT}")
print(f"   场景覆盖：肉类损耗 / 蔬菜腐烂 / 混合损耗 / 备餐过量 / 疑似过期 / 标准备餐")
