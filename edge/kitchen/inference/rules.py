#!/usr/bin/env python3
"""
后厨推理规则 — 所有阈值、类别、提示词、降级策略

此文件不含模型加载/引擎/管线调度等"推理内容"，仅含"推理规则"：
  - YOLO 检测阈值（conf / NMS）
  - CLIP-Adapter 默认类别 & 低置信度阈值
  - VLM 提示词模板
  - 三级过滤降级矩阵
"""

# ═══════════════════════════════════════════════════════════
# 1. YOLO 检测阈值
# ═══════════════════════════════════════════════════════════

YOLO_CONF_THRESH  = 0.25   # YOLO 置信度阈值
YOLO_IOU_THRESH   = 0.45   # NMS IoU 阈值
YOLO_IMG_SIZE     = 640    # 输入分辨率


# ═══════════════════════════════════════════════════════════
# 2. CLIP-Adapter 分类规则
# ═══════════════════════════════════════════════════════════

CLIP_DEFAULT_CLASSES = "clean_kitchen,dirty_surface,food_waste,cluttered,dangerous_object"
CLIP_LOW_CONF_THRESHOLD = 0.5   # 低于此值触发 VLM
CLIP_ADAPTER_RATIO = 0.2         # 残差融合比例


# ═══════════════════════════════════════════════════════════
# 3. VLM 提示词
# ═══════════════════════════════════════════════════════════

KITCHEN_PROMPT = """你是后厨废弃物识别系统。分析图片中的废弃食材/餐余，输出严格 JSON（不含 markdown）：
{"items":[{"waste_type":"备餐废弃|边角料|过期临界|餐后剩余","sku":"食材名","estimated_portion":0.8,"unit":"份","confidence":0.82,"reason":"判断依据","suggested_action":"建议操作"}]}
只输出 JSON，不要额外文字。"""

VLM_TIMEOUT_SEC = 30          # VLM 推理超时
VLM_TEMPERATURE = 0.1         # 生成温度
VLM_MAX_TOKENS   = 512        # 最大生成 token


# ═══════════════════════════════════════════════════════════
# 4. 三级过滤降级矩阵
# ═══════════════════════════════════════════════════════════

DEGRADATION_MATRIX = {
    # 格式: (yolo_status, clip_status, vlm_status) → pipeline_status
    ("ok",     "ok",     "ok"):      "ok",
    ("ok",     "ok",     "skipped"): "ok",        # CLIP 高置信度，不触发 VLM
    ("ok",     "error",  "ok"):      "degraded",  # CLIP 挂了，直接走 VLM
    ("ok",     "error",  "error"):   "degraded",  # 只剩 YOLO
    ("error",  "*",      "*"):       "error",     # YOLO 故障 → 整体失败
}
