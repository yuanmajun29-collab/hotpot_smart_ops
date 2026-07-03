#!/usr/bin/env python3
"""
Jetson VLM Bridge — 边缘推理 → Hub 对接脚本 (方案A: 离线模式)

用法:
  # 单张图片
  python3 bridge_waste_vision.py test_kitchen.jpg

  # 带参数
  python3 bridge_waste_vision.py test_hotpot_waste.jpg \
    --zone 备餐废弃区 --store store_yuhuan

  # 静默模式 (cron)
  python3 bridge_waste_vision.py test.jpg --quiet

环境变量:
  HOTPOT_HUB_URL    Hub 地址 (默认 http://192.168.2.85:8088)
  HOTPOT_HUB_TOKEN  JWT Token (默认自动获取)
  HOTPOT_HUB_USER   用户名 (默认 zhangdian)
  HOTPOT_HUB_PASS   密码 (默认 demo)
  OSTRAKON_SCRIPT   run_ostrakon_vl.sh 路径 (默认 /root/run_ostrakon_vl.sh)
"""

from __future__ import annotations

import base64
import json
import mimetypes
import os
import re
import subprocess
import sys
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


# ── Config ──────────────────────────────────────────────────────────
HUB_URL = os.environ.get("HOTPOT_HUB_URL", "http://127.0.0.1:8098")
HUB_USER = os.environ.get("HOTPOT_HUB_USER", "zhangdian")
HUB_PASS = os.environ.get("HOTPOT_HUB_PASS", "demo")
OSTRAKON_SCRIPT = os.environ.get("OSTRAKON_SCRIPT", "/root/run_ostrakon_vl.sh")
DEFAULT_STORE = "store_yuhuan"
REQUEST_TIMEOUT = 30


# ── VLM Prompt (纯 JSON 输出，已验证可行) ─────────────────────────────
VLM_PROMPT = """你是后厨废料识别系统。分析图片，输出纯 JSON 对象，不要 ```json 包裹，不要任何解释文字：

{"items":[{"sku":"食材名","waste_type":"备餐废弃|边角料|过期临界|餐后剩余","estimated_portion":0.8,"unit":"份","confidence":0.82,"reason":"判断依据","suggested_action":"建议操作"}]}

严格只输出 JSON，从 { 开始，到 } 结束。"""


# ── Helpers ─────────────────────────────────────────────────────────

def log(msg: str, quiet: bool = False) -> None:
    if not quiet:
        ts = datetime.now().strftime("%H:%M:%S")
        print(f"[{ts}] {msg}", file=sys.stderr)


def http_post(url: str, data: Dict[str, Any], token: str) -> Dict[str, Any]:
    """POST JSON to Hub, return parsed response."""
    body = json.dumps(data).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {e.code}: {detail}") from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"连接 Hub 失败: {e.reason}") from e


def get_token(store: str) -> str:
    """获取或复用 JWT token."""
    cached = os.environ.get("HOTPOT_HUB_TOKEN", "")
    if cached:
        return cached
    url = f"{HUB_URL}/auth/token"
    data = {
        "username": HUB_USER,
        "password": HUB_PASS,
        "role": "店长",
        "store_id": store,
    }
    resp = http_post(url, data, token="")  # no auth for login
    token = resp.get("access_token", "")
    if not token:
        raise RuntimeError(f"获取 token 失败: {resp}")
    return token


def run_vlm(image_path: str, quiet: bool = False) -> Dict[str, Any]:
    """调用 run_ostrakon_vl.sh 执行 VLM 推理，返回解析后的 JSON."""
    script = Path(OSTRAKON_SCRIPT)
    if not script.exists():
        raise FileNotFoundError(f"VLM 脚本不存在: {OSTRAKON_SCRIPT}")

    abs_image = Path(image_path).resolve()
    if not abs_image.exists():
        raise FileNotFoundError(f"图片不存在: {abs_image}")

    log(f"VLM 推理中: {abs_image.name}", quiet)

    # 将 Prompt 写入临时文件 (避免 shell 转义问题)
    prompt_file = Path("/tmp/vlm_bridge_prompt.txt")
    prompt_file.write_text(VLM_PROMPT, encoding="utf-8")

    cmd = [
        "bash", str(script),
        str(abs_image),
    ]
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120,
            env={**os.environ, "VLM_PROMPT_FILE": str(prompt_file)},
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"VLM 推理超时 (120s): {abs_image.name}")

    # 清理临时文件
    prompt_file.unlink(missing_ok=True)

    stdout = result.stdout.strip()
    stderr = result.stderr.strip()

    if result.returncode != 0:
        raise RuntimeError(f"VLM 推理失败 (exit={result.returncode}): {stderr[:500]}")

    log(f"VLM 输出 ({len(stdout)} 字符)", quiet)

    # 解析 JSON — 多层降级
    return parse_vlm_output(stdout)


def parse_vlm_output(raw: str) -> Dict[str, Any]:
    """从 VLM 原始输出中提取 JSON。VLM 已验证稳定输出纯 JSON，两层兜底。"""

    # Level 1: 直接解析 (VLM 已验证纯 JSON 输出)
    try:
        data = json.loads(raw.strip())
        if "items" in data:
            return data
    except json.JSONDecodeError:
        pass

    # Level 2: 正则提取第一个 { ... } 块 (极端边缘兜底)
    m = re.search(r'\{.*\}', raw, re.DOTALL)
    if m:
        try:
            data = json.loads(m.group(0))
            if "items" in data:
                return data
        except json.JSONDecodeError:
            pass

    raise RuntimeError(f"无法从 VLM 输出中解析 JSON items:\n{raw[:500]}")


def validate_items(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """确保每项有必填字段，补默认值."""
    cleaned = []
    for i, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        cleaned.append({
            "waste_type": str(item.get("waste_type", "未分类")),
            "sku": str(item.get("sku", f"未知-{i}")),
            "estimated_portion": float(item.get("estimated_portion", 0)),
            "unit": str(item.get("unit", "份")),
            "confidence": float(item.get("confidence", 0.5)),
            "reason": str(item.get("reason", "")),
            "suggested_action": str(item.get("suggested_action", "人工复核")),
        })
    return cleaned


def encode_image(image_path: str) -> tuple[str, str]:
    """返回 (base64_data, mime_type)。"""
    mime, _ = mimetypes.guess_type(image_path)
    mime = mime or 'image/jpeg'
    with open(image_path, 'rb') as f:
        b64 = base64.b64encode(f.read()).decode('ascii')
    return b64, mime


def submit_to_hub(
    items: List[Dict[str, Any]],
    image_ref: str,
    store: str,
    zone: Optional[str] = None,
    quiet: bool = False,
    skip_image: bool = False,
) -> Dict[str, Any]:
    """提交 VLM 结果到 Hub."""
    token = get_token(store)
    url = f"{HUB_URL}/v1/vlm/waste-estimate"

    payload: Dict[str, Any] = {
        "store_id": store,
        "items": items,
        "source": "vlm-shadow",
        "model": "ostrakon-vl-8b-iq4xs",
        "image_ref": f"file://{Path(image_ref).resolve()}",
        "ts": datetime.now(timezone.utc).isoformat(),
    }
    if zone:
        payload["zone"] = zone

    # ── 原图 base64 编码 ──
    if not skip_image:
        image_path = Path(image_ref)
        if image_path.exists():
            try:
                b64, mime = encode_image(str(image_path))
                payload['image_data'] = b64
                payload['image_mime'] = mime
            except Exception:
                pass  # 编码失败不阻断主流程

    log(f"POST {url} ({len(items)} 项)", quiet)
    resp = http_post(url, payload, token)

    if not resp.get("ok"):
        raise RuntimeError(f"Hub 返回异常: {resp}")

    return resp


# ── Main ────────────────────────────────────────────────────────────

def main() -> None:
    import argparse

    global HUB_URL

    parser = argparse.ArgumentParser(
        description="Jetson VLM Bridge — 边缘推理 → Hub 废料识别",
    )
    parser.add_argument("image", help="图片路径")
    parser.add_argument("--store", default=DEFAULT_STORE, help="门店ID")
    parser.add_argument("--zone", default=None, help="识别区域")
    parser.add_argument("--quiet", "-q", action="store_true", help="静默模式")
    parser.add_argument("--hub", default=None, help=f"Hub URL (默认 {HUB_URL})")
    parser.add_argument("--no-image", action="store_true", help="不传原图 (base64 体积大时使用)")
    args = parser.parse_args()
    if args.hub:
        HUB_URL = args.hub

    image_path = args.image
    store = args.store
    zone = args.zone
    quiet = args.quiet
    skip_image = args.no_image

    # ── Step 1: VLM 推理 ──
    try:
        vlm_output = run_vlm(image_path, quiet)
    except Exception as e:
        log(f"❌ VLM 推理失败: {e}", quiet)
        sys.exit(1)

    items_raw = vlm_output.get("items", [])
    items = validate_items(items_raw)

    if not items:
        log("⚠️ VLM 未识别到任何废弃物，跳过提交", quiet)
        sys.exit(0)

    log(f"✅ 识别 {len(items)} 项: {[i['sku'] for i in items]}", quiet)

    # ── Step 2: 提交 Hub ──
    try:
        resp = submit_to_hub(items, image_path, store, zone, quiet, skip_image=skip_image)
    except Exception as e:
        log(f"❌ Hub 提交失败: {e}", quiet)
        sys.exit(1)

    # ── Step 3: 输出结果 ──
    event_id = resp.get("event_id", "?")
    log(f"🎯 完成 → Hub event: {event_id}", quiet)

    if not quiet:
        print(json.dumps({
            "ok": True,
            "event_id": event_id,
            "items": items,
        }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
