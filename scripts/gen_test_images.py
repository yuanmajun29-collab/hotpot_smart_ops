#!/usr/bin/env python3
"""生成后厨损耗场景测试图片 — 模拟备餐区摄像头画面"""
import os, random, datetime
from PIL import Image, ImageDraw, ImageFont

OUT = os.path.expanduser("~/company/hotpot_smart_ops/test_images")
os.makedirs(OUT, exist_ok=True)

W, H = 1280, 720
FONT = None
# 尝试加载中文字体
for f in ["/System/Library/Fonts/STHeiti Light.ttc",
          "/System/Library/Fonts/PingFang.ttc",
          "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"]:
    if os.path.exists(f):
        FONT = ImageFont.truetype(f, 22)
        FONT_SM = ImageFont.truetype(f, 15)
        break

def create_kitchen_scene(filename, scenario, items, description):
    img = Image.new("RGB", (W, H), (30, 25, 20))
    draw = ImageDraw.Draw(img)

    # 操作台面
    draw.rectangle([(0, H-200), (W, H)], fill=(60, 50, 40))
    draw.rectangle([(0, H-202), (W, H-200)], fill=(130, 110, 90))
    # 瓷砖背景
    for y in range(0, H-200, 80):
        for x in range(0, W, 160):
            draw.rectangle([(x,y), (x+159,y+79)], outline=(50,42,35), width=1)

    # 不锈钢盆/托盘
    for i, (px, py, pw, ph) in enumerate([(120,380,400,280), (700,350,350,320)]):
        draw.rounded_rectangle([(px,py),(px+pw,py+ph)], radius=12, fill=(90,85,78), outline=(130,125,118), width=2)

    # 食材模拟 — 不同场景不同物品
    items_config = {
        "waste_meat": [
            {"xy": (200,440,320,520), "color": (180,60,50), "label": "毛肚边角料"},
            {"xy": (440,480,560,540), "color": (200,120,80), "label": "鸭肠"},
            {"xy": (300,550,420,600), "color": (160,90,70), "label": "牛百叶"},
        ],
        "waste_veg": [
            {"xy": (180,430,350,510), "color": (60,140,50), "label": "生菜叶"},
            {"xy": (400,460,520,530), "color": (80,160,60), "label": "菠菜"},
            {"xy": (600,500,730,560), "color": (180,170,50), "label": "土豆片"},
        ],
        "waste_mixed": [
            {"xy": (200,440,320,520), "color": (180,60,50), "label": "毛肚边角"},
            {"xy": (440,460,560,530), "color": (70,150,60), "label": "发黄生菜"},
            {"xy": (560,550,680,610), "color": (190,130,60), "label": "鸭肠过期"},
            {"xy": (350,560,470,620), "color": (150,150,50), "label": "氧化土豆"},
        ]
    }

    for item in items_config.get(scenario, items_config["waste_mixed"]):
        draw.rounded_rectangle(item["xy"], radius=8, fill=item["color"], outline=(100,90,80), width=1)
        if FONT_SM:
            lx = item["xy"][0]+4
            ly = item["xy"][1]+4
            draw.text((lx, ly), item["label"], fill=(255,255,255), font=FONT_SM)

    # 右上角摄像头信息
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    draw.rectangle([(W-260, 10), (W-10, 90)], fill=(0,0,0,160))
    if FONT:
        draw.text((W-250, 15), "📷 备餐废弃区", fill=(255,255,255), font=FONT)
        draw.text((W-250, 45), "Camera 01", fill=(86,184,132), font=FONT_SM)
        draw.text((W-250, 68), ts, fill=(180,180,180), font=FONT_SM)

    # 底部信息条
    draw.rectangle([(0, H-36), (W, H)], fill=(0,0,0,200))
    if FONT_SM:
        draw.text((16, H-30), f"门店: 玉环店 | 区域: 备餐废弃区 | {scenario}", fill=(200,200,200), font=FONT_SM)

    img.save(os.path.join(OUT, filename))
    print(f"✓ {filename} ({scenario}): {items}")

# 生成6个场景
scenes = [
    ("scene_01_waste_meat.jpg", "waste_meat", "肉类损耗→毛肚+鸭肠+牛百叶"),
    ("scene_02_waste_veg.jpg", "waste_veg", "蔬菜损耗→生菜+菠菜+土豆"),
    ("scene_03_waste_mixed.jpg", "waste_mixed", "混合损耗→毛肚+生菜+鸭肠+土豆"),
    ("scene_04_over_production.jpg", "waste_mixed", "备餐过量→大盘剩余"),
    ("scene_05_expired.jpg", "waste_meat", "疑似过期→颜色发暗肉类"),
    ("scene_06_clean.jpg", "waste_veg", "清爽备餐→少量蔬菜"),
]

for fn, sc, desc in scenes:
    create_kitchen_scene(fn, sc, desc, desc)

print(f"\n✅ {len(scenes)} 张测试图已生成 → {OUT}")
