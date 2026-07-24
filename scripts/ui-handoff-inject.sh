#!/usr/bin/env bash
# ui-handoff-inject.sh — 小卡(前端Worker) handoff 注入
# 用法: bash ui-handoff-inject.sh <handoff_file_or_dir>
# 在前端任务 handoff 前运行，将 Design Tokens + .cursorrules UI 章节注入上下文
#
# Harness 第三层：执行层 — 确保 AI Agent 每次生成 UI 前拿到最新规范

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
TOKEN_FILE="$PROJECT_DIR/hotpot_platform/design-tokens.json"
RULES_FILE="$PROJECT_DIR/.cursorrules"
TARGET="${1:-}"

# 如果没有指定目标，输出到 stdout (供 cursor handoff 管道使用)
if [ -z "$TARGET" ]; then
  echo "=== 火瞳 UI 规范注入 ==="
  echo ""
  echo "📐 Design Tokens:"
  python3 -c "import json; t=json.load(open('$TOKEN_FILE')); print(f'  色板: {len(t[\"color\"])} | 间距: {len(t[\"spacing\"])} | 圆角: {len(t[\"radius\"])} | 组件: {len(t[\"components\"])}')"
  echo ""
  echo "📋 禁止事项:"
  python3 -c "import json; t=json.load(open('$TOKEN_FILE')); [print(f'  • {r}') for r in t['rules']['forbidden']]"
  echo ""
  echo "📂 Token 文件: $TOKEN_FILE"
  echo "📂 UI 规则: $RULES_FILE"
  echo ""
  echo "⚠️ 开始生成前端代码前，请先读取以上文件。禁止硬编码颜色/像素/内联样式。"
  exit 0
fi

# 注入到目标 handoff 文件
if [ -f "$TARGET" ]; then
  # 追加到文件末尾
  cat >> "$TARGET" << 'INJECT'
  
---
## UI 规范 (自动注入)

⚠️ **在生成任何 UI 代码前，必须先读取以下文件：**

1. `hotpot_platform/design-tokens.json` — 颜色/间距/圆角/字体/组件参数
2. `.cursorrules` (## UI 规范 章节) — 组件使用规则、禁止事项

### 核心规则速查：
- 禁止硬编码颜色值 → 用 var(--xxx)
- 禁止硬编码像素值 → 对照 spacing token
- 按钮用 .btn 类，卡片用 .card 类
- 新页面必须 <link> theme.css
- 移动端 max-width 480px，PDA max-width 480px
INJECT
  echo "✅ UI 规范已注入 $TARGET"
else
  echo "❌ 目标不存在: $TARGET"
  exit 1
fi
