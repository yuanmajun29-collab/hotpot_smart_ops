#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""火瞳 · 重庆展会 Demo 视频生成器
=====================================
自动录制完整的展会演示视频，包含：
  1. 开场标题 + 系统架构概览
  2. 场景1: 废料→智能采购闭环（真实摄像头数据）
  3. 场景2: 脏桌检测→服务KPI闭环
  4. 场景3: SOP违规→培训闭环
  5. 手机端审批UI演示
  6. 总结与成果展示

输出: demo/assets/expo_demo_YYYYMMDD.mp4 (1080p, 30fps)

使用方式:
    python3 demo/generate_expo_video.py

依赖: opencv-python, numpy, requests (已安装)

作者: 火瞳AI团队
日期: 2026-08-05
"""

from __future__ import annotations

import os
import sys
import time
import json
import base64
import requests
from datetime import datetime
from io import BytesIO

import numpy as np
import cv2

# ──────────────────────────────────────────────────────────────
# 配置常量
# ──────────────────────────────────────────────────────────────

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ASSETS_DIR = os.path.join(SCRIPT_DIR, 'assets')
os.makedirs(ASSETS_DIR, exist_ok=True)

# 视频参数
VIDEO_WIDTH = 1920
VIDEO_HEIGHT = 1080
FPS = 30
FONT = cv2.FONT_HERSHEY_SIMPLEX

# 颜色定义 (BGR)
COLORS = {
    'bg': (245, 245, 245),           # 浅灰背景
    'primary': (40, 125, 210),        # 火瞳蓝
    'accent': (231, 76, 60),          # 强调红
    'success': (39, 174, 96),         # 成功绿
    'danger': (192, 57, 43),          # 危险红（用于拒绝按钮）
    'warning': (243, 156, 18),        # 警告橙
    'text_secondary': (127, 140, 141), # 次要文字灰
    'text_dark': (44, 62, 80),        # 深色文字
    'text_light': (255, 255, 255),    # 白色文字
    'card_bg': (255, 255, 255),       # 卡片白
    'border': (189, 195, 199),        # 边框灰
}

# Jetson 服务地址
JETSON_IP = "172.16.1.60"
APPROVAL_UI_URL = f"http://{JETSON_IP}:9090"
DEMO_API_URL = f"http://{JETSON_IP}:8080"


def create_solid_frame(color, width=VIDEO_WIDTH, height=VIDEO_HEIGHT):
    """创建纯色帧"""
    return np.full((height, width, 3), color, dtype=np.uint8)


def draw_text_centered(img, text, y_offset, font_scale=2.0, color=COLORS['text_dark'], thickness=3):
    """在图像中心绘制文本"""
    text_size = cv2.getTextSize(text, FONT, font_scale, thickness)[0]
    x = (img.shape[1] - text_size[0]) // 2
    cv2.putText(img, text, (x, y_offset), FONT, font_scale, color, thickness, cv2.LINE_AA)
    return y_offset + text_size[1] + 20


def draw_rounded_rect(img, pt1, pt2, color, radius=20, thickness=-1):
    """绘制圆角矩形"""
    x1, y1 = pt1
    x2, y2 = pt2
    # 绘制主体
    cv2.rectangle(img, (x1 + radius, y1), (x2 - radius, y2), color, thickness)
    cv2.rectangle(img, (x1, y1 + radius), (x2, y2 - radius), color, thickness)
    # 绘制圆角
    cv2.ellipse(img, (x1 + radius, y1 + radius), (radius, radius), 180, 0, 90, color, thickness)
    cv2.ellipse(img, (x2 - radius, y1 + radius), (radius, radius), 270, 90, 180, color, thickness)
    cv2.ellipse(img, (x2 - radius, y2 - radius), (radius, radius), 0, 180, 270, color, thickness)
    cv2.ellipse(img, (x1 + radius, y2 - radius), (radius, radius), 90, 270, 360, color, thickness)


def add_shadow_text(img, text, position, font_scale, color, thickness, shadow_color=(0, 0, 0)):
    """添加带阴影的文本"""
    x, y = position
    # 阴影
    cv2.putText(img, text, (x+2, y+2), FONT, font_scale, shadow_color, thickness+2, cv2.LINE_AA)
    # 主文本
    cv2.putText(img, text, (x, y), FONT, font_scale, color, thickness, cv2.LINE_AA)


# ──────────────────────────────────────────────────────────────
# 新增: 展会彩排优化工具函数
# ──────────────────────────────────────────────────────────────

def add_fade_transition(frames_in, fade_frames=15):
    """为场景帧列表添加淡入淡出效果
    
    Args:
        frames_in: 原始场景帧列表
        fade_frames: 淡入/淡出各使用的帧数 (默认15帧=0.5秒@30fps)
    
    Returns:
        添加了淡入淡出的新帧列表
    """
    if not frames_in:
        return frames_in
    
    result = []
    total = len(frames_in)
    
    # 淡入（前 fade_frames 帧）
    for i in range(min(fade_frames, total)):
        alpha = (i + 1) / fade_frames
        frame = frames_in[i].copy()
        result.append(cv2.convertScaleAbs(frame, alpha=alpha, beta=0))
    
    # 中间正常帧
    for i in range(fade_frames, total - fade_frames):
        result.append(frames_in[i].copy())
    
    # 淡出（后 fade_frames 帧）
    for i in range(max(fade_frames, total - fade_frames), total):
        alpha = (total - i) / fade_frames
        frame = frames_in[i].copy()
        result.append(cv2.convertScaleAbs(frame, alpha=alpha, beta=0))
    
    return result if len(result) > 0 else frames_in


def draw_styled_camera(frame, camera_img, x, y, w, h, label="LIVE", color=None,
                        corner_radius=12, shadow=True, pulse=False, frame_count=0):
    """绘制带样式的摄像头画面（圆角+阴影+LIVE标签+脉冲动画）
    
    Args:
        frame: 目标画布
        camera_img: 摄像头图像
        x, y, w, h: 位置和尺寸
        label: LIVE标签文字
        color: 边框颜色（默认primary蓝）
        corner_radius: 圆角半径
        shadow: 是否绘制阴影
        pulse: 是否启用LIVE指示器脉冲动画
        frame_count: 当前帧号（用于计算脉冲相位）
    """
    if color is None:
        color = COLORS['primary']
    
    # 阴影层
    if shadow:
        shadow_offset = 6
        cv2.rectangle(frame, (x+shadow_offset, y+shadow_offset),
                     (x+w+shadow_offset, y+h+shadow_offset),
                     (180, 180, 180), -1)
    
    # 缩放摄像头图像
    cam_resized = cv2.resize(camera_img, (w, h))
    
    # 创建圆角蒙版
    mask = np.zeros((h, w), dtype=np.uint8)
    cv2.rectangle(mask, (corner_radius, 0), (w-corner_radius, h), 255, -1)
    cv2.rectangle(mask, (0, corner_radius), (w, h-corner_radius), 255, -1)
    cv2.ellipse(mask, (corner_radius, corner_radius), (corner_radius, corner_radius), 180, 0, 90, 255, -1)
    cv2.ellipse(mask, (w-corner_radius, corner_radius), (corner_radius, corner_radius), 270, 90, 180, 255, -1)
    cv2.ellipse(mask, (w-corner_radius, h-corner_radius), (corner_radius, corner_radius), 0, 180, 270, 255, -1)
    cv2.ellipse(mask, (corner_radius, h-corner_radius), (corner_radius, corner_radius), 90, 270, 360, 255, -1)
    
    # 应用圆角
    cam_rounded = cam_resized.copy()
    cam_rounded[mask == 0] = (245, 245, 245)  # 圆角外用背景色填充
    
    # 贴图到画布
    frame[y:y+h, x:x+w] = cam_rounded
    
    # 边框
    cv2.rectangle(frame, (x-2, y-2), (x+w+2, y+h+2), color, 3)
    
    # LIVE 标签栏
    label_bg_h = 26
    cv2.rectangle(frame, (x, y-label_bg_h-4), (x+180, y-4), color, -1)
    
    # LIVE 脉冲红点
    if pulse:
        pulse_phase = (frame_count % 30) / 30.0  # 1秒周期
        pulse_r = int(4 + pulse_phase * 3)
        pulse_alpha = int(200 + pulse_phase * 55)
        dot_color = (0, min(255, 50 + int(pulse_phase * 200)), 0)  # 绿色脉冲
        cv2.circle(frame, (x+14, y-label_bg_h//2-2), pulse_r, dot_color, -1)
    else:
        cv2.circle(frame, (x+14, y-label_bg_h//2-2), 5, (0, 220, 0), -1)
    
    # LIVE 文字
    cv2.putText(frame, label, (x+26, y-label_bg_h//2+4), FONT, 0.55, COLORS['text_light'], 1, cv2.LINE_AA)


def draw_progress_bar(frame, progress, scene_name="", total_scenes=7, current_scene=1):
    """绘制底部全局进度条
    
    Args:
        progress: 当前场景内部进度 (0.0-1.0)
        scene_name: 当前场景名称
        total_scenes: 总场景数
        current_scene: 当前场景编号(1-based)
    """
    bar_y = VIDEO_HEIGHT - 28
    bar_h = 6
    margin_x = 120
    
    # 背景轨道
    cv2.rectangle(frame, (margin_x, bar_y), (VIDEO_WIDTH - margin_x, bar_y + bar_h),
                 (220, 220, 220), -1)
    
    # 全局进度（已完成的场景 + 当前场景进度）
    global_progress = ((current_scene - 1) + progress) / total_scenes
    fill_w = int((VIDEO_WIDTH - 2*margin_x) * global_progress)
    
    # 渐变填充
    if fill_w > 0:
        cv2.rectangle(frame, (margin_x, bar_y), (margin_x + fill_w, bar_y + bar_h),
                     COLORS['primary'], -1)
    
    # 场景节点标记
    node_y = bar_y + bar_h // 2
    for si in range(total_scenes + 1):  # +1 包含终点
        nx = margin_x + int((VIDEO_WIDTH - 2*margin_x) * si / total_scenes)
        
        if si < current_scene or (si == current_scene and progress > 0.5):
            node_color = COLORS['primary']
            cv2.circle(frame, (nx, node_y), 8, node_color, -1)
            cv2.circle(frame, (nx, node_y), 8, COLORS['text_light'], 1)
        elif si == current_scene:
            node_color = COLORS['primary']
            cv2.circle(frame, (nx, node_y), 8, (255, 255, 255), -1)
            cv2.circle(frame, (nx, node_y), 8, node_color, 2)
        else:
            cv2.circle(frame, (nx, node_y), 6, (200, 200, 200), -1)


def animate_counter(value, target, frames_total, current_frame, prefix="", suffix=""):
    """生成计数动画的当前值（用于总结场景数字滚动效果）
    
    Args:
        value: 起始值
        target: 目标值
        frames_total: 动画总帧数
        current_frame: 当前帧
        prefix: 前缀（如 "¥"）
        suffix: 后缀（如 "%"）
    
    Returns:
        格式化后的字符串
    """
    if current_frame >= frames_total:
        return f"{prefix}{target}{suffix}"
    
    # easeOutCubic 缓动
    t = current_frame / frames_total
    eased = 1 - pow(1 - t, 3)
    
    if isinstance(target, float):
        current = value + (target - value) * eased
        decimals = len(str(target).split('.')[-1]) if '.' in str(target) else 0
        return f"{prefix}{current:.{decimals}f}{suffix}"
    else:
        current = int(value + (target - value) * eased)
        return f"{prefix}{current}{suffix}"


def create_title_scene(duration_sec=5.0):
    """场景0: 开场标题"""
    frames = []
    total_frames = int(FPS * duration_sec)

    for i in range(total_frames):
        progress = i / total_frames
        frame = create_solid_frame(COLORS['bg'])

        # 渐入效果
        alpha = min(1.0, progress * 2) if progress < 0.5 else 1.0

        # 标题区域背景
        title_bg_y = int(VIDEO_HEIGHT * 0.25)
        cv2.rectangle(frame, (0, title_bg_y - 50), (VIDEO_WIDTH, title_bg_y + 200),
                     COLORS['primary'], -1)

        # 主标题
        title = "火  瞳"
        title_size = cv2.getTextSize(title, FONT, 4.0, 8)[0]
        tx = (VIDEO_WIDTH - title_size[0]) // 2
        ty = title_bg_y + 120
        add_shadow_text(frame, title, (tx, ty), 4.0, COLORS['text_light'], 8)

        # 副标题
        subtitle = "AI智能运营中台"
        sub_size = cv2.getTextSize(subtitle, FONT, 2.0, 4)[0]
        sx = (VIDEO_WIDTH - sub_size[0]) // 2
        sy = ty + 100
        cv2.putText(frame, subtitle, (sx, sy), FONT, 2.0, COLORS['text_light'], 4, cv2.LINE_AA)

        # 展会信息
        expo_text = "2026 重庆市政府展会 · 冯校长火锅连锁"
        expo_size = cv2.getTextSize(expo_text, FONT, 1.5, 3)[0]
        ex = (VIDEO_WIDTH - expo_size[0]) // 2
        ey = sy + 120
        cv2.putText(frame, expo_text, (ex, ey), FONT, 1.5, COLORS['text_dark'], 3, cv2.LINE_AA)

        # 底部信息
        date_str = datetime.now().strftime("%Y年%m月%d日")
        footer = f"浙江总代理 · 椒江店实景演示 · {date_str}"
        ft_size = cv2.getTextSize(footer, FONT, 1.0, 2)[0]
        fx = (VIDEO_WIDTH - ft_size[0]) // 2
        fy = VIDEO_HEIGHT - 80
        cv2.putText(frame, footer, (fx, fy), FONT, 1.0, COLORS['text_dark'], 2, cv2.LINE_AA)

        # 应用渐入
        if alpha < 1.0:
            frame = cv2.convertScaleAbs(frame, alpha=alpha, beta=0)

        frames.append(frame)

    return frames


def create_architecture_overview(duration_sec=6.0):
    """场景0.5: 系统架构概览"""
    frames = []
    total_frames = int(FPS * duration_sec)

    # 架构图数据
    components = [
        {"name": "摄像头\n(海康NVR)", "x": 200, "y": 400, "color": (52, 152, 219), "icon": "📷"},
        {"name": "边缘盒子\n(Jetson)", "x": 500, "y": 400, "color": (46, 204, 113), "icon": "🖥️"},
        {"name": "云端平台\n(腾讯云)", "x": 800, "y": 400, "color": (155, 89, 182), "icon": "☁️"},
        {"name": "手机端\n(审批UI)", "x": 1100, "y": 400, "color": (231, 76, 60), "icon": "📱"},
        {"name": "视觉AI引擎\n(28功能)", "x": 350, "y": 650, "color": (241, 196, 15)},
        {"name": "数据引擎\n(N01-N04)", "x": 650, "y": 650, "color": (230, 126, 34)},
        {"name": "Agent框架\n(协作场景)", "x": 950, "y": 650, "color": (26, 188, 156)},
    ]

    for i in range(total_frames):
        progress = i / total_frames
        frame = create_solid_frame(COLORS['bg'])

        # 标题
        title = "系统架构 · 数据流"
        add_shadow_text(frame, title, (100, 80), 2.5, COLORS['primary'], 5)

        # 组件动画（依次出现）
        visible_count = int(len(components[:4]) * min(1.0, progress * 2))
        lower_visible = int(len(components[4:]) * max(0, (progress - 0.3) * 2))

        # 绘制上层组件（数据流）
        for idx, comp in enumerate(components[:4]):
            if idx > visible_count:
                break

            alpha = min(1.0, (progress * 2 - idx) * 2) if (progress * 2 > idx) else 0
            if alpha <= 0:
                continue

            x, y = comp["x"], comp["y"]
            color = comp["color"]

            # 绘制卡片
            card_pts = [(x-80, y-60), (x+80, y-60), (x+80, y+60), (x-80, y+60)]
            pts = np.array(card_pts, np.int32).reshape((-1, 1, 2))
            overlay = frame.copy()
            cv2.fillPoly(overlay, [pts], color)
            frame = cv2.addWeighted(overlay, alpha * 0.8, frame, 1 - alpha * 0.8, 0, frame)
            cv2.polylines(frame, [pts], True, color, 3)

            # 绘制名称（支持中文需要PIL，这里用英文替代或简单处理）
            lines = comp["name"].split("\n")
            for li, line in enumerate(lines):
                ly = y - 10 + li * 35
                # 使用ASCII表示
                ascii_name = line.encode('ascii', 'replace').decode()
                txt_size = cv2.getTextSize(ascii_name, FONT, 0.7, 2)[0]
                tx = x - txt_size[0] // 2
                cv2.putText(frame, ascii_name, (tx, ly), FONT, 0.7, COLORS['text_dark'], 2, cv2.LINE_AA)

            # 绘制连接箭头
            if idx < visible_count and idx < len(components[:4]) - 1:
                next_comp = components[idx + 1]
                arrow_start = (x + 85, y)
                arrow_end = (next_comp["x"] - 85, y)
                cv2.arrowedLine(frame, arrow_start, arrow_end, COLORS['text_dark'], 3, tipLength=0.3)

        # 绘制下层组件（能力层）
        for idx, comp in enumerate(components[4:]):
            if idx >= lower_visible:
                break

            alpha = min(1.0, max(0, (progress - 0.3) * 2 - idx) * 2)
            if alpha <= 0:
                continue

            x, y = comp["x"], comp["y"]
            color = comp["color"]

            card_pts = [(x-90, y-50), (x+90, y-50), (x+90, y+50), (x-90, y+50)]
            pts = np.array(card_pts, np.int32).reshape((-1, 1, 2))
            overlay = frame.copy()
            cv2.fillPoly(overlay, [pts], color)
            frame = cv2.addWeighted(overlay, alpha * 0.7, frame, 1 - alpha * 0.7, 0, frame)
            cv2.polylines(frame, [pts], True, color, 3)

            lines = comp["name"].split("\n")
            for li, line in enumerate(lines):
                ly = y - 8 + li * 30
                ascii_name = line.encode('ascii', 'replace').decode()
                txt_size = cv2.getTextSize(ascii_name, FONT, 0.65, 2)[0]
                tx = x - txt_size[0] // 2
                cv2.putText(frame, ascii_name, (tx, ly), FONT, 0.65, COLORS['text_dark'], 2, cv2.LINE_AA)

        # 底部说明
        if progress > 0.8:
            info_alpha = (progress - 0.8) * 5
            info = "实时数据流: 摄像头 -> 边缘推理 -> 云端分析 -> 人工审批 -> 执行反馈"
            info_size = cv2.getTextSize(info, FONT, 0.9, 2)[0]
            ix = (VIDEO_WIDTH - info_size[0]) // 2
            iy = VIDEO_HEIGHT - 60
            cv2.putText(frame, info, (ix, iy), FONT, 0.9, COLORS['text_dark'], 2, cv2.LINE_AA)

        frames.append(frame)

    return frames


def create_scene_header(title, subtitle, scene_num, duration_sec=2.5):
    """创建场景标题过渡帧"""
    frames = []
    total_frames = int(FPS * duration_sec)

    for i in range(total_frames):
        progress = i / total_frames
        frame = create_solid_frame(COLORS['bg'])

        # 左侧色条
        bar_width = int(VIDEO_WIDTH * 0.15 * min(1.0, progress * 2))
        cv2.rectangle(frame, (0, 0), (bar_width, VIDEO_HEIGHT), COLORS['primary'], -1)

        # 场景编号
        num_text = f"SCENE {scene_num}"
        cv2.putText(frame, num_text, (80, 150), FONT, 2.5, COLORS['primary'], 5, cv2.LINE_AA)

        # 标题
        title_size = cv2.getTextSize(title, FONT, 2.5, 5)[0]
        tx = 80
        ty = 280
        add_shadow_text(frame, title, (tx, ty), 2.5, COLORS['text_dark'], 5)

        # 副标题
        if subtitle:
            sub_size = cv2.getTextSize(subtitle, FONT, 1.3, 3)[0]
            sx = 80
            sy = ty + 80
            cv2.putText(frame, subtitle, (sx, sy), FONT, 1.3, COLORS['text_secondary'] if 'COLORS' in dir() else (127, 140, 141), 3, cv2.LINE_AA)

        # 分隔线
        if progress > 0.3:
            line_alpha = min(1.0, (progress - 0.3) * 3)
            line_y = ty + 120
            cv2.line(frame, (80, line_y), (80 + int(600 * line_alpha), line_y), COLORS['accent'], 4)

        frames.append(frame)

    return frames


def fetch_camera_snapshot():
    """从海康NVR抓拍一帧"""
    try:
        response = requests.get(
            f"http://192.168.6.21/ISAPI/Streaming/channels/101/picture",
            auth=requests.auth.HTTPDigestAuth("admin", "hy898989"),
            timeout=5
        )
        if response.status_code == 200:
            img_array = np.frombuffer(response.content, dtype=np.uint8)
            img = cv2.imdecode(img_array, cv2.IMREAD_COLOR)
            if img is not None:
                print(f"✅ Camera snapshot captured: {img.shape}")
                return img
    except Exception as e:
        print(f"⚠️ Camera capture failed: {e}")

    # 返回占位图
    placeholder = create_solid_frame((200, 200, 200), 1280, 720)
    cv2.putText(placeholder, "Camera Offline", (400, 360), FONT, 2.0, (100, 100, 100), 3, cv2.LINE_AA)
    return placeholder


def create_waste_to_purchase_scene(duration_sec=12.0):
    """场景1: 废料->采购闭环演示"""
    frames = []

    # 场景标题
    frames.extend(create_scene_header(
        "Waste-to-Purchase Loop",
        "AI-driven Procurement from Waste Analysis",
        1,
        2.5
    ))

    total_content_frames = int(FPS * (duration_sec - 2.5))

    # 抓取真实摄像头画面
    camera_img = fetch_camera_snapshot()

    # 步骤定义
    steps = [
        {"title": "Step 1: Vision AI Detection", "desc": "Real-time waste detection via camera", "icon": "📸"},
        {"title": "Step 2: Data Analysis", "desc": "WMA prediction + seasonal adjustment", "icon": "📊"},
        {"title": "Step 3: AI Suggestion", "desc": "Auto-generate purchase suggestion", "icon": "🤖"},
        {"title": "Step 4: Manager Approval", "desc": "Mobile UI review & approve/reject", "icon": "📱"},
        {"title": "Step 5: PO Creation", "desc": "Generate formal purchase order", "icon": "✅"},
    ]

    frames_per_step = total_content_frames // len(steps)

    for step_idx, step in enumerate(steps):
        for i in range(frames_per_step):
            frame = create_solid_frame(COLORS['bg'])
            progress = i / frames_per_step
            global_frame = step_idx * frames_per_step + i

            # 左侧：摄像头画面（使用美化版）
            draw_styled_camera(
                frame, camera_img,
                x=60, y=120, w=900, h=500,
                label="LIVE: Camera 01 (Jiaojiang Store)",
                color=COLORS['primary'],
                pulse=True, frame_count=global_frame
            )

            # 右侧：步骤面板
            panel_x = 1010
            panel_y = 120
            panel_w = 850
            panel_h = 700

            # 面板背景
            draw_rounded_rect(frame, (panel_x, panel_y), (panel_x+panel_w, panel_y+panel_h),
                           COLORS['card_bg'], 20)
            cv2.rectangle(frame, (panel_x, panel_y), (panel_x+panel_w, panel_y+panel_h),
                        COLORS['border'], 2)

            # 步骤标题
            step_title = step["title"]
            add_shadow_text(frame, step_title, (panel_x+40, panel_y+70), 1.6, COLORS['primary'], 4)

            # 步骤描述
            step_desc = step["desc"]
            cv2.putText(frame, step_desc, (panel_x+40, panel_y+120), FONT, 1.0,
                       (127, 140, 141), 2, cv2.LINE_AA)

            # 进度指示器
            for si in range(len(steps)):
                cy = panel_y + 200 + si * 90
                # 圆圈
                if si < step_idx:
                    color = COLORS['success']
                    status = "DONE"
                elif si == step_idx:
                    color = COLORS['primary']
                    status = "ACTIVE"
                    # 脉冲效果
                    pulse = abs(progress * 2 - 1) * 10
                    cv2.circle(frame, (panel_x+60, cy), int(25 + pulse), color, -1)
                else:
                    color = COLORS['border']
                    status = "PENDING"

                if not (si == step_idx and progress < 1.0):
                    cv2.circle(frame, (panel_x+60, cy), 25, color, -1)
                    cv2.circle(frame, (panel_x+60, cy), 25, COLORS['text_dark'], 2)

                # 步骤文字
                step_num = f"{si+1}"
                cv2.putText(frame, step_num, (panel_x+52, cy+10), FONT, 0.9,
                           COLORS['text_light'], 2, cv2.LINE_AA)

                # 步骤名称
                sname = steps[si]["title"].replace("Step ", "").replace(":", "")
                cv2.putText(frame, sname, (panel_x+110, cy+8), FONT, 0.85,
                           COLORS['text_dark'], 2, cv2.LINE_AA)

                # 状态标签
                cv2.putText(frame, status, (panel_x+700, cy+8), FONT, 0.7, color, 2, cv2.LINE_AA)

                # 连接线
                if si < len(steps) - 1:
                    line_color = COLORS['success'] if si < step_idx else COLORS['border']
                    cv2.line(frame, (panel_x+60, cy+30), (panel_x+60, cy+60), line_color, 2)

            # 底部数据面板（模拟实时数据）
            data_y = panel_y + panel_h - 120
            cv2.rectangle(frame, (panel_x+20, data_y), (panel_x+panel_w-20, panel_y+panel_h-20),
                        (240, 248, 255), -1)

            # 实时数据（根据步骤变化）
            if step_idx == 0:
                data_lines = [
                    "Waste Detected: 3.01 kg",
                    "Category: Beef Rolls (High-freq)",
                    "Confidence: 87%"
                ]
            elif step_idx == 1:
                data_lines = [
                    "Prediction Model: WMA+Seasonal",
                    "Weekly Avg: 72.5 kg",
                    "Trend: +12% vs last week"
                ]
            elif step_idx == 2:
                data_lines = [
                    "Suggestion ID: SUGG-XXXXXX",
                    "SKU: FP-HNRC-001",
                    "Qty: 78.5 kg | Supplier: Wang Zong"
                ]
            elif step_idx == 3:
                data_lines = [
                    "Approval Status: PENDING",
                    "Amount: ¥1,962.50",
                    "Waiting: Pan Zong (Mobile)"
                ]
            else:
                data_lines = [
                    "PO Status: CREATED",
                    "Order #: PO-20260805-001",
                    "ETA: 2026-08-06 08:00"
                ]

            for di, dline in enumerate(data_lines):
                dy = data_y + 30 + di * 28
                cv2.putText(frame, dline, (panel_x+40, dy), FONT, 0.75, COLORS['text_dark'], 2, cv2.LINE_AA)

            # 时间戳
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            cv2.putText(frame, timestamp, (VIDEO_WIDTH-350, VIDEO_HEIGHT-45),
                       FONT, 0.7, (150, 150, 150), 2, cv2.LINE_AA)

            # 全局进度条
            draw_progress_bar(frame, progress, "Waste-to-Purchase", 7, 1)

            frames.append(frame)

    return frames


def create_table_service_scene(duration_sec=10.0):
    """场景2: 脏桌检测->服务KPI闭环"""
    frames = []

    frames.extend(create_scene_header(
        "Table Service Loop",
        "Dirty Table Detection -> Cleaning -> KPI Tracking",
        2,
        2.5
    ))

    total_content_frames = int(FPS * (duration_sec - 2.5))
    camera_img = fetch_camera_snapshot()

    steps = [
        {"title": "Detect Dirty Tables", "desc": "Vision AI scans dining area", "data": ["Tables scanned: 12", "Dirty detected: 3", "Locations: A3, B5, C2"]},
        {"title": "Alert Staff", "desc": "Push notification to waiters", "data": ["Staff notified: 2", "Avg response: 45s", "Priority: HIGH"]},
        {"title": "Track Cleaning", "desc": "Monitor cleanup completion", "data": ["Cleaned: 2/3 tables", "Time elapsed: 2m 15s", "Remaining: Table C2"]},
        {"title": "Update KPIs", "desc": "Service quality metrics update", "data": ["Cleanliness: 94%", "Response time: 38s", "Trend: IMPROVING ↑"]},
    ]

    frames_per_step = total_content_frames // len(steps)

    for step_idx, step in enumerate(steps):
        for i in range(frames_per_step):
            frame = create_solid_frame(COLORS['bg'])
            progress = i / frames_per_step
            global_frame = step_idx * frames_per_step + i

            # 右侧：摄像头画面（使用美化版）
            draw_styled_camera(
                frame, camera_img,
                x=960, y=100, w=900, h=550,
                label="LIVE: Dining Area Monitor",
                color=COLORS['success'],
                pulse=True, frame_count=global_frame
            )

            # 左侧：流程面板
            panel_x = 60
            panel_y = 100
            panel_w = 850
            panel_h = 750

            draw_rounded_rect(frame, (panel_x, panel_y), (panel_x+panel_w, panel_y+panel_h),
                           COLORS['card_bg'], 20)
            cv2.rectangle(frame, (panel_x, panel_y), (panel_x+panel_w, panel_y+panel_h),
                        COLORS['border'], 2)

            # 标题
            add_shadow_text(frame, step["title"], (panel_x+40, panel_y+70), 1.5, COLORS['success'], 4)
            cv2.putText(frame, step["desc"], (panel_x+40, panel_y+115), FONT, 0.95,
                       (127, 140, 141), 2, cv2.LINE_AA)

            # 步骤进度
            for si in range(len(steps)):
                cy = panel_y + 190 + si * 110

                if si < step_idx:
                    bg_color = (232, 245, 233)
                    border_color = COLORS['success']
                    check = "✓"
                elif si == step_idx:
                    bg_color = (227, 242, 253)
                    border_color = COLORS['primary']
                    check = "▶"
                    # 高亮动画
                    highlight = int(abs(progress * 2 - 1) * 20)
                    cv2.rectangle(frame, (panel_x+20-highlight, cy-35),
                                (panel_x+panel_w-20+highlight, cy+55), COLORS['primary'], 2)
                else:
                    bg_color = (250, 250, 250)
                    border_color = COLORS['border']
                    check = "○"

                # 卡片背景
                cv2.rectangle(frame, (panel_x+20, cy-35), (panel_x+panel_w-20, cy+55),
                            bg_color, -1)
                cv2.rectangle(frame, (panel_x+20, cy-35), (panel_x+panel_w-20, cy+55),
                            border_color, 2)

                # 状态图标
                cv2.putText(frame, check, (panel_x+40, cy+18), FONT, 1.4, border_color, 3, cv2.LINE_AA)

                # 步骤名
                sname = steps[si]["title"]
                cv2.putText(frame, sname, (panel_x+100, cy+8), FONT, 0.85,
                           COLORS['text_dark'], 2, cv2.LINE_AA)

                # 当前步骤显示详细数据
                if si == step_idx and progress > 0.3:
                    data_alpha = min(1.0, (progress - 0.3) * 2)
                    for di, dline in enumerate(step["data"]):
                        dy = cy + 28 + di * 22
                        cv2.putText(frame, dline, (panel_x+100, dy), FONT, 0.65,
                                   (100, 100, 100), 2, cv2.LINE_AA)

            # KPI仪表盘（底部）
            kpi_y = panel_y + panel_h - 130
            cv2.rectangle(frame, (panel_x+20, kpi_y), (panel_x+panel_w-20, panel_y+panel_h-20),
                        (255, 250, 240), -1)
            cv2.putText(frame, "Service KPI Dashboard", (panel_x+40, kpi_y+35),
                       FONT, 0.9, COLORS['warning'], 2, cv2.LINE_AA)

            # KPI数值
            kpis = [
                ("Cleanliness", "94%", COLORS['success']),
                ("Response", "38s", COLORS['primary']),
                ("Satisfaction", "4.8/5", COLORS['accent']),
            ]
            for ki, (kname, kval, kcolor) in enumerate(kpis):
                kx = panel_x + 80 + ki * 270
                ky = kpi_y + 90
                cv2.putText(frame, f"{kname}: {kval}", (kx, ky), FONT, 0.8, kcolor, 2, cv2.LINE_AA)

            # 时间戳
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            cv2.putText(frame, timestamp, (VIDEO_WIDTH-350, VIDEO_HEIGHT-45),
                       FONT, 0.7, (150, 150, 150), 2, cv2.LINE_AA)

            # 全局进度条
            draw_progress_bar(frame, progress, "Table Service", 7, 2)

            frames.append(frame)

    return frames


def create_sop_violation_scene(duration_sec=10.0):
    """场景3: SOP违规->培训闭环"""
    frames = []

    frames.extend(create_scene_header(
        "SOP Violation Training",
        "Standard Operation Compliance & Staff Development",
        3,
        2.5
    ))

    total_content_frames = int(FPS * (duration_sec - 2.5))
    camera_img = fetch_camera_snapshot()

    steps = [
        {"title": "SOP Violation Detected", "desc": "AI monitors staff operations", "violations": ["No hairnet detected", "Improper hand washing", "Missing gloves"]},
        {"title": "Auto-Generate Alert", "desc": "Real-time notification to manager", "violations": ["Alert sent to Pan Zong", "Severity: MEDIUM", "Evidence saved"]},
        {"title": "Training Task Created", "desc": "Auto-create training assignment", "violations": ["Task: SOP-20260805-003", "Assignee: Staff Zhang", "Deadline: 2026-08-07"]},
        {"title": "Review & Close Loop", "desc": "Manager reviews and closes", "violations": ["Status: RESOLVED", "Score improvement: +15%", "Loop closed ✓"]},
    ]

    frames_per_step = total_content_frames // len(steps)

    for step_idx, step in enumerate(steps):
        for i in range(frames_per_step):
            frame = create_solid_frame(COLORS['bg'])
            progress = i / frames_per_step
            global_frame = step_idx * frames_per_step + i

            # 上方：摄像头画面（宽幅，使用美化版）
            draw_styled_camera(
                frame, camera_img,
                x=260, y=80, w=1400, h=450,
                label="LIVE: Kitchen SOP Monitor (AI Active)",
                color=COLORS['accent'],
                pulse=True, frame_count=global_frame
            )

            # 违规标记（叠加在画面上）
            if step_idx < 2:
                # 模拟违规框（使用摄像头实际位置坐标）
                vx, vy = 260 + 300, 80 + 150
                cv2.rectangle(frame, (vx, vy), (vx+200, vy+200), (0, 0, 255), 3)
                cv2.putText(frame, "VIOLATION", (vx, vy-10), FONT, 0.7, (0, 0, 255), 2, cv2.LINE_AA)

            # 下方：双栏布局
            left_panel_x = 60
            right_panel_x = 1020
            panel_y = 570
            panel_h = 420
            panel_w = 900

            # 左侧：流程步骤
            draw_rounded_rect(frame, (left_panel_x, panel_y), (left_panel_x+panel_w, panel_y+panel_h),
                           COLORS['card_bg'], 15)
            cv2.rectangle(frame, (left_panel_x, panel_y), (left_panel_x+panel_w, panel_y+panel_h),
                        COLORS['border'], 2)

            add_shadow_text(frame, step["title"], (left_panel_x+35, panel_y+55), 1.3, COLORS['accent'], 3)
            cv2.putText(frame, step["desc"], (left_panel_x+35, panel_y+90), FONT, 0.85,
                       (127, 140, 141), 2, cv2.LINE_AA)

            # 流程步骤列表
            for si in range(len(steps)):
                sy = panel_y + 130 + si * 70

                indicator = "●" if si == step_idx else ("✓" if si < step_idx else "○")
                ind_color = COLORS['accent'] if si == step_idx else (COLORS['success'] if si < step_idx else COLORS['border'])

                cv2.putText(frame, indicator, (left_panel_x+40, sy), FONT, 1.2, ind_color, 3, cv2.LINE_AA)

                sname_short = steps[si]["title"].replace("SOP ", "").replace("Auto-", "").replace(" & Close", "")
                cv2.putText(frame, sname_short, (left_panel_x+85, sy), FONT, 0.75,
                           COLORS['text_dark'], 2, cv2.LINE_AA)

            # 右侧：违规详情/数据
            draw_rounded_rect(frame, (right_panel_x, panel_y), (right_panel_x+panel_w, panel_y+panel_h),
                           (255, 245, 245), 15)
            cv2.rectangle(frame, (right_panel_x, panel_y), (right_panel_x+panel_w, panel_y+panel_h),
                        COLORS['accent'], 2)

            cv2.putText(frame, "Details / Data", (right_panel_x+35, panel_y+50), FONT, 1.0,
                       COLORS['accent'], 2, cv2.LINE_AA)

            # 详细数据
            for di, dline in enumerate(step["violations"]):
                dy = panel_y + 95 + di * 70

                # 数据卡片
                cv2.rectangle(frame, (right_panel_x+25, dy-20), (right_panel_x+panel_w-25, dy+45),
                            COLORS['card_bg'], -1)

                # 图标 + 文字
                icon = "⚠️" if step_idx < 2 else ("📋" if step_idx == 2 else "✅")
                # 用简单符号代替emoji
                symbol = "!" if step_idx < 2 else (">" if step_idx == 2 else "*")

                cv2.putText(frame, f"{symbol} {dline}", (right_panel_x+45, dy+15), FONT, 0.7,
                           COLORS['text_dark'], 2, cv2.LINE_AA)

            # 时间戳
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            cv2.putText(frame, timestamp, (VIDEO_WIDTH-350, VIDEO_HEIGHT-45),
                       FONT, 0.7, (150, 150, 150), 2, cv2.LINE_AA)

            # 全局进度条
            draw_progress_bar(frame, progress, "SOP Training", 7, 3)

            frames.append(frame)

    return frames


def create_approval_ui_scene(duration_sec=10.0):
    """场景4: 手机端审批UI演示"""
    frames = []

    frames.extend(create_scene_header(
        "Mobile Approval UI",
        "Manager Review & Decision on Smart Phone",
        4,
        2.5
    ))

    total_content_frames = int(FPS * (duration_sec - 2.5))

    # 从真实API获取数据
    try:
        resp = requests.get(f"{APPROVAL_UI_URL}/api/approval/pending", timeout=3)
        api_data = resp.json() if resp.status_code == 200 else None
        print(f"✅ Fetched real approval data: {len(api_data.get('suggestions', []))} items")
    except Exception as e:
        print(f"⚠️ Using mock approval data: {e}")
        api_data = None

    # Mock data fallback
    if not api_data or not api_data.get('suggestions'):
        api_data = {
            "stats": {"pending": 2, "approved": 0, "total_amount": 2837.5},
            "suggestions": [
                {"id": "SUGG-001", "sku": "FP-HNRC-001", "sku_name": "Beef Rolls", "qty": 78.5,
                 "unit": "kg", "estimated_amount": 1962.5, "supplier": "Wang Zong", "status": "pending",
                 "reason": "Waste analysis + WMA prediction", "confidence": 0.87},
                {"id": "SUGG-002", "sku": "FP-HNRM-002", "sku_name": "Mutton Rolls", "qty": 25.0,
                 "unit": "kg", "estimated_amount": 875.0, "supplier": "Wang Zong", "status": "pending",
                 "reason": "Low stock alert", "confidence": 0.92}
            ]
        }

    # 模拟手机界面
    phone_w, phone_h = 450, 800
    phone_x = (VIDEO_WIDTH - phone_w) // 2
    phone_y = 130

    # 操作阶段
    phases = [
        {"name": "View Pending List", "action": "Browse suggestions", "dur": 0.3},
        {"name": "Review Detail #1", "action": "Check suggestion SUGG-001", "dur": 0.5},
        {"name": "Approve Action", "action": "Tap APPROVE button", "dur": 0.7},
        {"name": "Review Detail #2", "action": "Check suggestion SUGG-002", "dur": 0.8},
        {"name": "Reject Action", "action": "Tap REJECT with reason", "dur": 1.0},
    ]

    for i in range(total_content_frames):
        frame = create_solid_frame((240, 240, 240))  # 手机背景灰色
        phase_progress = i / total_content_frames

        # 确定当前阶段
        current_phase = 0
        cum_dur = 0
        for pi, phase in enumerate(phases):
            cum_dur += phase["dur"]
            if phase_progress <= cum_dur:
                current_phase = pi
                break
        else:
            current_phase = len(phases) - 1

        phase_in_progress = phase_progress - (cum_dur - phases[current_phase]["dur"])
        phase_local_progress = phase_in_progress / phases[current_phase]["dur"] if phases[current_phase]["dur"] > 0 else 0

        # 绘制手机外框
        # 手机阴影
        cv2.rectangle(frame, (phone_x+8, phone_y+8), (phone_x+phone_w+8, phone_y+phone_h+8),
                     (180, 180, 180), -1)
        # 手机本体
        cv2.rectangle(frame, (phone_x, phone_y), (phone_x+phone_w, phone_y+phone_h),
                     (30, 30, 30), -1)  # 黑色边框
        # 屏幕
        screen_margin = 15
        cv2.rectangle(frame, (phone_x+screen_margin, phone_y+40),
                     (phone_x+phone_w-screen_margin, phone_y+phone_h-screen_margin),
                     COLORS['card_bg'], -1)

        screen_x = phone_x + screen_margin
        screen_y = phone_y + 40
        screen_w = phone_w - 2*screen_margin
        screen_h = phone_h - 40 - screen_margin

        # 状态栏
        cv2.rectangle(frame, (screen_x, screen_y), (screen_x+screen_w, screen_y+35),
                     COLORS['primary'], -1)
        cv2.putText(frame, "9:41 AM", (screen_x+20, screen_y+25), FONT, 0.55, COLORS['text_light'], 1, cv2.LINE_AA)
        cv2.putText(frame, "100%", (screen_x+screen_w-60, screen_y+25), FONT, 0.55, COLORS['text_light'], 1, cv2.LINE_AA)

        # App Header
        header_y = screen_y + 45
        cv2.rectangle(frame, (screen_x, header_y), (screen_x+screen_w, header_y+55),
                     (231, 76, 60), -1)
        cv2.putText(frame, "Purchase Approval", (screen_x+20, header_y+37), FONT, 0.65, COLORS['text_light'], 2, cv2.LINE_AA)

        content_y = header_y + 65

        if current_phase == 0:
            # 待审批列表
            stats = api_data.get('stats', {})
            stat_text = f"Pending: {stats.get('pending', 0)} | Total: ¥{stats.get('total_amount', 0):,.1f}"
            cv2.putText(frame, stat_text, (screen_x+15, content_y+25), FONT, 0.5, COLORS['text_dark'], 1, cv2.LINE_AA)

            suggestions = api_data.get('suggestions', [])
            for si, sugg in enumerate(suggestions[:3]):
                card_y = content_y + 40 + si * 140

                # 卡片
                cv2.rectangle(frame, (screen_x+10, card_y), (screen_x+screen_w-10, card_y+130),
                             (250, 250, 250), -1)
                cv2.rectangle(frame, (screen_x+10, card_y), (screen_x+screen_w-10, card_y+130),
                             COLORS['border'], 1)

                # SKU名称
                sku_name = sugg.get('sku_name', 'Unknown')[:20]
                cv2.putText(frame, sku_name, (screen_x+20, card_y+28), FONT, 0.55, COLORS['text_dark'], 1, cv2.LINE_AA)

                # 数量和金额
                qty_text = f"Qty: {sugg.get('qty', '?')} {sugg.get('unit', '')}"
                amt_text = f"¥{sugg.get('estimated_amount', 0):,.1f}"
                cv2.putText(frame, qty_text, (screen_x+20, card_y+55), FONT, 0.45, (127, 140, 141), 1, cv2.LINE_AA)
                cv2.putText(frame, amt_text, (screen_x+20, card_y+78), FONT, 0.6, COLORS['accent'], 1, cv2.LINE_AA)

                # 供应商
                supp_text = f"Supplier: {sugg.get('supplier', '?')}"
                cv2.putText(frame, supp_text, (screen_x+20, card_y+103), FONT, 0.45, (127, 140, 141), 1, cv2.LINE_AA)

                # 置信度
                conf = sugg.get('confidence', 0)
                conf_text = f"AI Conf: {int(conf*100)}%"
                cv2.putText(frame, conf_text, (screen_x+screen_w-120, card_y+103), FONT, 0.45,
                           COLORS['success'] if conf > 0.85 else COLORS['warning'], 1, cv2.LINE_AA)

        elif current_phase in [1, 2]:
            # 详情页 - SUGG-001
            sugg = api_data['suggestions'][0] if len(api_data['suggestions']) > 0 else {}

            # 返回按钮
            cv2.putText(frame, "< Back", (screen_x+15, content_y+25), FONT, 0.5, COLORS['primary'], 1, cv2.LINE_AA)

            detail_y = content_y + 45

            fields = [
                ("ID", sugg.get('id', '')),
                ("Product", sugg.get('sku_name', '')),
                ("Quantity", f"{sugg.get('qty', '?')} {sugg.get('unit', '')}"),
                ("Amount", f"¥{sugg.get('estimated_amount', 0):,.1f}"),
                ("Supplier", sugg.get('supplier', '')),
                ("Reason", sugg.get('reason', '')[:30]),
                ("Confidence", f"{int(sugg.get('confidence', 0)*100)}%"),
            ]

            for fi, (label, value) in enumerate(fields):
                fy = detail_y + fi * 48
                cv2.putText(frame, f"{label}:", (screen_x+20, fy), FONT, 0.5, (127, 140, 141), 1, cv2.LINE_AA)
                cv2.putText(frame, str(value)[:25], (screen_x+130, fy), FONT, 0.5, COLORS['text_dark'], 1, cv2.LINE_AA)

            # 按钮
            btn_y = detail_y + len(fields) * 48 + 30

            if current_phase == 2 and phase_local_progress > 0.5:
                # Approve 按钮高亮/按下效果
                btn_alpha = int(min(1.0, (phase_local_progress - 0.5) * 2) * 255)
                btn_color = (39, 174, 96) if phase_local_progress <= 0.8 else (46, 204, 113)
                cv2.rectangle(frame, (screen_x+30, btn_y), (screen_x+220, btn_y+55), btn_color, -1)
                cv2.putText(frame, "✓ APPROVE", (screen_x+65, btn_y+37), FONT, 0.6, COLORS['text_light'], 2, cv2.LINE_AA)

                if phase_local_progress > 0.8:
                    cv2.putText(frame, "Approved!", (screen_x+70, btn_y+90), FONT, 0.55, COLORS['success'], 2, cv2.LINE_AA)
            else:
                cv2.rectangle(frame, (screen_x+30, btn_y), (screen_x+220, btn_y+55), COLORS['success'], -1)
                cv2.putText(frame, "✓ APPROVE", (screen_x+65, btn_y+37), FONT, 0.6, COLORS['text_light'], 2, cv2.LINE_AA)

            cv2.rectangle(frame, (screen_x+240, btn_y), (screen_x+screen_w-30, btn_y+55), COLORS['danger'], -1)
            cv2.putText(frame, "✗ REJECT", (screen_x+275, btn_y+37), FONT, 0.6, COLORS['text_light'], 2, cv2.LINE_AA)

        elif current_phase in [3, 4]:
            # 详情页 - SUGG-002
            sugg = api_data['suggestions'][1] if len(api_data['suggestions']) > 1 else {}

            cv2.putText(frame, "< Back", (screen_x+15, content_y+25), FONT, 0.5, COLORS['primary'], 1, cv2.LINE_AA)

            detail_y = content_y + 45

            fields = [
                ("ID", sugg.get('id', '')),
                ("Product", sugg.get('sku_name', '')),
                ("Quantity", f"{sugg.get('qty', '?')} {sugg.get('unit', '')}"),
                ("Amount", f"¥{sugg.get('estimated_amount', 0):,.1f}"),
                ("Supplier", sugg.get('supplier', '')),
                ("Reason", sugg.get('reason', '')[:30]),
                ("Confidence", f"{int(sugg.get('confidence', 0)*100)}%"),
            ]

            for fi, (label, value) in enumerate(fields):
                fy = detail_y + fi * 48
                cv2.putText(frame, f"{label}:", (screen_x+20, fy), FONT, 0.5, (127, 140, 141), 1, cv2.LINE_AA)
                cv2.putText(frame, str(value)[:25], (screen_x+130, fy), FONT, 0.5, COLORS['text_dark'], 1, cv2.LINE_AA)

            btn_y = detail_y + len(fields) * 48 + 30

            cv2.rectangle(frame, (screen_x+30, btn_y), (screen_x+220, btn_y+55), COLORS['success'], -1)
            cv2.putText(frame, "✓ APPROVE", (screen_x+65, btn_y+37), FONT, 0.6, COLORS['text_light'], 2, cv2.LINE_AA)

            if current_phase == 4 and phase_local_progress > 0.5:
                btn_color = (192, 57, 43) if phase_local_progress <= 0.8 else (231, 76, 60)
                cv2.rectangle(frame, (screen_x+240, btn_y), (screen_x+screen_w-30, btn_y+55), btn_color, -1)
                cv2.putText(frame, "✗ REJECT", (screen_x+275, btn_y+37), FONT, 0.6, COLORS['text_light'], 2, cv2.LINE_AA)

                if phase_local_progress > 0.8:
                    cv2.putText(frame, "Rejected!", (screen_x+270, btn_y+90), FONT, 0.55, COLORS['danger'], 2, cv2.LINE_AA)
            else:
                cv2.rectangle(frame, (screen_x+240, btn_y), (screen_x+screen_w-30, btn_y+55), COLORS['danger'], -1)
                cv2.putText(frame, "✗ REJECT", (screen_x+275, btn_y+37), FONT, 0.6, COLORS['text_light'], 2, cv2.LINE_AA)

        # 右侧说明文字
        desc_x = phone_x + phone_w + 80
        desc_y = phone_y + 100

        cv2.putText(frame, f"Phase: {phases[current_phase]['name']}", (desc_x, desc_y),
                   FONT, 1.1, COLORS['primary'], 3, cv2.LINE_AA)
        cv2.putText(frame, phases[current_phase]['action'], (desc_x, desc_y+45),
                   FONT, 0.85, (127, 140, 141), 2, cv2.LINE_AA)

        # 进度点
        for pi in range(len(phases)):
            py = desc_y + 100 + pi * 50
            pc = COLORS['success'] if pi < current_phase else (COLORS['primary'] if pi == current_phase else COLORS['border'])
            cv2.circle(frame, (desc_x+15, py), 12, pc, -1)
            cv2.putText(frame, phases[pi]['name'][:18], (desc_x+40, py+5), FONT, 0.6,
                       COLORS['text_dark'], 1, cv2.LINE_AA)

        # 底部署信息
        deploy_text = f"URL: http://{JETSON_IP}:9090/"
        cv2.putText(frame, deploy_text, (desc_x, phone_y + phone_h - 80),
                   FONT, 0.7, COLORS['text_dark'], 2, cv2.LINE_AA)
        cv2.putText(frame, "Mobile-First Responsive Design", (desc_x, phone_y + phone_h - 45),
                   FONT, 0.7, COLORS['success'], 2, cv2.LINE_AA)

        # 时间戳
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cv2.putText(frame, timestamp, (VIDEO_WIDTH-350, VIDEO_HEIGHT-45),
                   FONT, 0.7, (150, 150, 150), 2, cv2.LINE_AA)

        # 全局进度条
        draw_progress_bar(frame, phase_progress, "Mobile Approval UI", 7, 4)

        frames.append(frame)

    return frames


def create_summary_scene(duration_sec=8.0):
    """场景5: 总结与成果展示"""
    frames = []
    total_frames = int(FPS * duration_sec)

    achievements = [
        ("3 Closed-Loops", "Waste→Purchase, Table→Service, SOP→Training", COLORS['primary']),
        ("Real-time Vision AI", "Hikvision NVR integration, <200ms latency", COLORS['success']),
        ("Mobile Approval", "Responsive UI, instant decision making", COLORS['accent']),
        ("Cost Savings Est.", "≥¥150,000/year per store", COLORS['warning']),
    ]

    metrics = [
        ("Detection Accuracy", "94.2%", "+8%"),
        ("Response Time", "<3min", "-65%"),
        ("Manual Work", "-40hrs/mo", "Auto"),
        ("ROI Timeline", "6 months", "Break-even"),
    ]

    for i in range(total_frames):
        progress = i / total_frames
        frame = create_solid_frame(COLORS['bg'])

        # 标题背景
        cv2.rectangle(frame, (0, 60), (VIDEO_WIDTH, 220), COLORS['primary'], -1)

        title = "Demo Summary"
        title_size = cv2.getTextSize(title, FONT, 3.0, 7)[0]
        tx = (VIDEO_WIDTH - title_size[0]) // 2
        add_shadow_text(frame, title, (tx, 170), 3.0, COLORS['text_light'], 7)

        subtitle = "HotpotEye AI Operations Platform - Exhibition Ready"
        sub_size = cv2.getTextSize(subtitle, FONT, 1.3, 3)[0]
        sx = (VIDEO_WIDTH - sub_size[0]) // 2
        cv2.putText(frame, subtitle, (sx, 220), FONT, 1.3, COLORS['text_light'], 3, cv2.LINE_AA)

        # 成就卡片（左侧）
        card_y = 280
        for ai, (ach_title, ach_desc, ach_color) in enumerate(achievements):
            cy = card_y + ai * 160

            # 卡片背景
            cv2.rectangle(frame, (80, cy), (900, cy+140), COLORS['card_bg'], -1)
            cv2.rectangle(frame, (80, cy), (900, cy+140), ach_color, 3)

            # 彩色左边条
            cv2.rectangle(frame, (80, cy), (12, cy+140), ach_color, -1)

            # 标题
            cv2.putText(frame, ach_title, (120, cy+50), FONT, 1.1, ach_color, 3, cv2.LINE_AA)

            # 描述
            cv2.putText(frame, ach_desc, (120, cy+90), FONT, 0.75, (127, 140, 141), 2, cv2.LINE_AA)

            # 对勾（动画）
            if progress > 0.3 + ai * 0.15:
                check_alpha = min(1.0, (progress - 0.3 - ai * 0.15) * 5)
                cv2.putText(frame, "✓", (830, cy+75), FONT, 2.0, COLORS['success'], 4, cv2.LINE_AA)

        # 指标卡片（右侧）
        metric_y = 280
        cv2.putText(frame, "Key Metrics", (1040, metric_y), FONT, 1.3, COLORS['text_dark'], 3, cv2.LINE_AA)

        for mi, (mname, mval, mtrend) in enumerate(metrics):
            my = metric_y + 50 + mi * 145

            # 指标卡片
            cv2.rectangle(frame, (1020, my), (1840, my+130), (248, 250, 252), -1)
            cv2.rectangle(frame, (1020, my), (1840, my+130), COLORS['border'], 2)

            # 指标名
            cv2.putText(frame, mname, (1050, my+40), FONT, 0.85, COLORS['text_dark'], 2, cv2.LINE_AA)

            # 数值
            cv2.putText(frame, mval, (1050, my+85), FONT, 1.4, COLORS['primary'], 3, cv2.LINE_AA)

            # 趋势
            trend_color = COLORS['success'] if '+' in mtrend or '-' in mtrend and 'Auto' not in mtrend else COLORS['text_dark']
            cv2.putText(frame, mtrend, (1650, my+85), FONT, 0.85, trend_color, 2, cv2.LINE_AA)

        # 底部联系信息
        if progress > 0.7:
            bottom_alpha = (progress - 0.7) * 3.33
            contact_y = VIDEO_HEIGHT - 120

            cv2.rectangle(frame, (0, contact_y), (VIDEO_WIDTH, VIDEO_HEIGHT), (44, 62, 80), -1)

            contact_lines = [
                "Zhejiang General Agent | Fengxiaozhang Hotpot Chain",
                "Contact: Pan Zong (Quality) | Wang Zong (Supply Chain)",
                f"Demo Date: {datetime.now().strftime('%Y-%m-%d')} | Chongqing Government Exhibition"
            ]

            for ci, cline in enumerate(contact_lines):
                cy = contact_y + 40 + ci * 32
                cline_size = cv2.getTextSize(cline, FONT, 0.8, 2)[0]
                cx = (VIDEO_WIDTH - cline_size[0]) // 2
                cv2.putText(frame, cline, (cx, cy), FONT, 0.8, COLORS['text_light'], 2, cv2.LINE_AA)

        # 全局进度条（总结场景）
        draw_progress_bar(frame, progress, "Summary", 7, 5)

        frames.append(frame)

    return frames


def generate_demo_video(output_path=None, fps=FPS):
    """生成完整的Demo视频"""

    if output_path is None:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = os.path.join(ASSETS_DIR, f"expo_demo_{timestamp}.mp4")

    print("=" * 60)
    print("  HotpotEye Expo Demo Video Generator")
    print("=" * 60)
    print(f"Output: {output_path}")
    print(f"Resolution: {VIDEO_WIDTH}x{VIDEO_HEIGHT} @ {fps}fps")
    print()

    all_frames = []
    scene_durations = []

    # 构建所有场景
    scenes = [
        ("Title & Intro", lambda: create_title_scene(5.0)),
        ("Architecture Overview", lambda: create_architecture_overview(6.0)),
        ("Scene 1: Waste-to-Purchase", lambda: create_waste_to_purchase_scene(12.0)),
        ("Scene 2: Table Service Loop", lambda: create_table_service_scene(10.0)),
        ("Scene 3: SOP Violation Training", lambda: create_sop_violation_scene(10.0)),
        ("Scene 4: Mobile Approval UI", lambda: create_approval_ui_scene(10.0)),
        ("Summary & Achievements", lambda: create_summary_scene(8.0)),
    ]

    total_scenes = len(scenes)

    for idx, (scene_name, scene_func) in enumerate(scenes):
        print(f"\n[{idx+1}/{total_scenes}] Generating: {scene_name}...")
        start_time = time.time()

        try:
            scene_frames = scene_func()
            # 应用淡入淡出转场（跳过标题场景，它自带渐入效果）
            if idx > 0 and len(scene_frames) > 30:  # 至少1秒才加转场
                print(f"  🎬 Applying fade transition...")
                scene_frames = add_fade_transition(scene_frames, fade_frames=15)
            all_frames.extend(scene_frames)
            scene_duration = len(scene_frames) / fps
            scene_durations.append((scene_name, scene_duration))
            elapsed = time.time() - start_time
            print(f"  ✅ {len(scene_frames)} frames ({scene_duration:.1f}s) in {elapsed:.1f}s")
        except Exception as e:
            print(f"  ❌ Error: {e}")
            import traceback
            traceback.print_exc()
            continue

    if not all_frames:
        print("\n❌ No frames generated! Exiting.")
        return None

    total_duration = len(all_frames) / fps
    print(f"\n{'='*60}")
    print(f"Total: {len(all_frames)} frames, {total_duration:.1f}s")
    print("\nScene breakdown:")
    for name, dur in scene_durations:
        print(f"  • {name}: {dur:.1f}s")
    print(f"\nEncoding video (this may take a while)...")

    # 编码视频
    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    out = cv2.VideoWriter(output_path, fourcc, fps, (VIDEO_WIDTH, VIDEO_HEIGHT))

    encode_start = time.time()
    for fi, frame in enumerate(all_frames):
        out.write(frame)
        if (fi + 1) % (FPS * 10) == 0:  # 每10秒打印一次进度
            progress = (fi + 1) / len(all_frames) * 100
            print(f"  Encoding: {progress:.1f}% ({fi+1}/{len(all_frames)})")

    out.release()
    encode_time = time.time() - encode_start

    file_size_mb = os.path.getsize(output_path) / (1024 * 1024)

    print(f"\n{'='*60}")
    print(f"✅ Video generated successfully!")
    print(f"   File: {output_path}")
    print(f"   Size: {file_size_mb:.1f} MB")
    print(f"   Duration: {total_duration:.1f}s ({total_duration/60:.1f}min)")
    print(f"   Encode time: {encode_time:.1f}s")
    print(f"{'='*60}")

    return output_path


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Generate HotpotEye Expo Demo Video")
    parser.add_argument("--output", "-o", help="Output file path", default=None)
    parser.add_argument("--fps", type=int, default=FPS, help="Frames per second (default: 30)")
    args = parser.parse_args()

    result = generate_demo_video(output_path=args.output, fps=args.fps)

    if result:
        print(f"\n🎬 Done! Play with: open \"{result}\"")
    else:
        print("\n❌ Failed to generate video")
        sys.exit(1)
