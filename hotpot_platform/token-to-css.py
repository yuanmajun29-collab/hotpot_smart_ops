#!/usr/bin/env python3
"""
token-to-css.py — 从 design-tokens.json 生成 theme.css 的 CSS 变量块
用法: python3 token-to-css.py [--check] [--watch]
  --check  仅检查 token 与 CSS 是否同步，不写入
  --watch  监听 token 文件变化，自动重新生成

Harness 第三层：执行层。确保 AI 和人类开发者拿到的 token 是最新的。
"""
import json
import sys
import os
from pathlib import Path

TOKEN_FILE = Path(__file__).resolve().parent / "design-tokens.json"
CSS_FILE = Path(__file__).resolve().parent / "dashboard" / "assets" / "theme-tokens.css"

def generate_css_vars(tokens: dict) -> str:
    """从 tokens JSON 生成 CSS 变量块"""
    lines = ["/* 火瞳 Design Tokens — 自动生成，禁止手动编辑 */", 
             "/* 源文件: hotpot_platform/design-tokens.json */",
             f"/* 生成时间: 由 token-to-css.py 自动维护 */",
             ":root {"]
    
    # 颜色
    for key, val in tokens.get("color", {}).items():
        css_key = f"--{_camel_to_kebab(key)}"
        lines.append(f"  {css_key}: {val};")
    
    # 间距
    for key, val in tokens.get("spacing", {}).items():
        lines.append(f"  --space-{key}: {val};")
    
    # 圆角
    for key, val in tokens.get("radius", {}).items():
        lines.append(f"  --r-{key}: {val};")
    
    # 布局
    for key, val in tokens.get("layout", {}).items():
        lines.append(f"  --{_camel_to_kebab(key)}: {val};")
    
    # 组件参数
    for comp, props in tokens.get("components", {}).items():
        for key, val in props.items():
            lines.append(f"  --cmp-{comp}-{_camel_to_kebab(key)}: {val};")
    
    lines.append("}")
    return "\n".join(lines) + "\n"

def _camel_to_kebab(s: str) -> str:
    """camelCase → kebab-case"""
    result = []
    for c in s:
        if c.isupper():
            result.append("-")
            result.append(c.lower())
        else:
            result.append(c)
    return "".join(result)

def check_sync():
    """检查 token 和 CSS 是否同步"""
    if not CSS_FILE.exists():
        print("❌ CSS 文件不存在，需要生成")
        return False
    
    with open(TOKEN_FILE) as f:
        tokens = json.load(f)
    
    new_css = generate_css_vars(tokens)
    current = CSS_FILE.read_text()
    
    if new_css.strip() != current.strip():
        print("❌ Token 与 CSS 不同步！")
        return False
    
    print("✅ Token ↔ CSS 同步")
    return True

def main():
    check_only = "--check" in sys.argv
    
    with open(TOKEN_FILE) as f:
        tokens = json.load(f)
    
    css = generate_css_vars(tokens)
    
    if check_only:
        if check_sync():
            sys.exit(0)
        else:
            sys.exit(1)
    
    # 写入
    CSS_FILE.parent.mkdir(parents=True, exist_ok=True)
    CSS_FILE.write_text(css)
    print(f"✅ 已生成 {CSS_FILE.relative_to(TOKEN_FILE.parent)}")
    print(f"   {len(tokens.get('color', {}))} 色板 | {len(tokens.get('spacing', {}))} 间距 | {len(tokens.get('radius', {}))} 圆角")
    
    # 验证新旧CSS一致性
    theme_css = Path(__file__).resolve().parent / "dashboard" / "assets" / "theme.css"
    if theme_css.exists():
        existing_vars = set()
        for line in theme_css.read_text().split("\n"):
            if line.strip().startswith("--"):
                existing_vars.add(line.strip().split(":")[0].strip())
        new_vars = set()
        for line in css.split("\n"):
            if line.strip().startswith("--"):
                new_vars.add(line.strip().split(":")[0].strip())
        
        only_new = new_vars - existing_vars
        only_old = existing_vars - new_vars
        if only_new or only_old:
            print(f"   ⚠️  theme.css 可能需要更新: 新增{len(only_new)}个 / 移除{len(only_old)}个变量")

if __name__ == "__main__":
    main()
