#!/usr/bin/env python3
"""CLIP 场景语义服务 — 独立子进程，避免 hotpot platform/ 污染。
   
协议（stdin/stdout，每行一条 JSON）：
  输入: {"image_path": "/abs/path/to/image.jpg"}
  输出: {"table": "dining", "table_conf": 0.46, "service": "clearing", "svc_conf": 0.38, ...}
        {"error": "..."}
        {"ready": true}  ← 启动完成信号
"""
import sys, json, os

# 确保不乱导入 hotpot 项目
sys.path = [p for p in sys.path if 'hotpot' not in str(p).lower()]

import torch
from PIL import Image
from transformers import CLIPModel, CLIPProcessor

TABLE_STATES = [
    "customers eating hotpot at the table",
    "a messy table with leftover food and dirty dishes",
    "staff cleaning the table",
]
SERVICE_EVENTS = [
    "a waiter serving food or drinks to the table",
    "a waiter clearing dishes from the table",
    "a waiter taking orders at the table",
]
CUSTOMER_EVENTS = [
    "customers eating and chatting happily",
    "customers waving or looking around for waiter",
    "customers getting up to leave",
    "customers paying the bill",
]

# 映射
TABLE_MAP = {
    "customers eating hotpot at the table":       "dining",
    "a messy table with leftover food and dirty dishes": "needs_cleaning",
    "staff cleaning the table":                   "cleaning",
}
SERVICE_MAP = {
    "a waiter serving food or drinks to the table": "serving",
    "a waiter clearing dishes from the table":      "clearing",
    "a waiter taking orders at the table":          "taking_order",
}
CUSTOMER_MAP = {
    "customers eating and chatting happily":       "eating",
    "customers waving or looking around for waiter": "calling_waiter",
    "customers getting up to leave":               "leaving",
    "customers paying the bill":                   "paying",
}

def load_models():
    sys.stderr.write("[clip_server] Loading CLIP...\n")
    sys.stderr.flush()
    model = CLIPModel.from_pretrained("openai/clip-vit-base-patch32")
    proc = CLIPProcessor.from_pretrained("openai/clip-vit-base-patch32")
    sys.stderr.write("[clip_server] CLIP ready\n")
    sys.stderr.flush()
    return model, proc

def classify(img, labels, model, proc):
    inputs = proc(text=labels, images=img, return_tensors="pt", padding=True)
    with torch.no_grad():
        probs = model(**inputs).logits_per_image.softmax(dim=1)[0]
    idx = probs.argmax().item()
    return labels[idx], round(probs[idx].item(), 3)

def main():
    model, proc = load_models()
    # 发就绪信号
    print(json.dumps({"ready": True}), flush=True)

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
            path = req.get("image_path", "")
            if not path or not os.path.exists(path):
                print(json.dumps({"error": f"image not found: {path}"}), flush=True)
                continue

            img = Image.open(path).convert("RGB")

            table_label, table_conf = classify(img, TABLE_STATES, model, proc)
            svc_label, svc_conf = classify(img, SERVICE_EVENTS, model, proc)
            cust_label, cust_conf = classify(img, CUSTOMER_EVENTS, model, proc)

            print(json.dumps({
                "table": TABLE_MAP.get(table_label, "unknown"),
                "table_conf": table_conf,
                "service": SERVICE_MAP.get(svc_label, "none"),
                "svc_conf": svc_conf,
                "customer": CUSTOMER_MAP.get(cust_label, "none"),
                "cust_conf": cust_conf,
            }), flush=True)

        except Exception as e:
            print(json.dumps({"error": str(e)}), flush=True)

if __name__ == "__main__":
    main()
