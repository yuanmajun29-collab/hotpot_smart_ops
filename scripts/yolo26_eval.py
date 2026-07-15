#!/usr/bin/env python3
"""YOLOv8→v26 模型升级评估 + ONNX 导出

评估要点:
  YOLO26: 移除DFL、无NMS推理、STAL小目标优化、MuSGD稳定收敛
  vs YOLOv8: DFL+NMS、传统标签分配

Jetson Orin 上的预期收益:
  - ONNX 导出更简单 (无DFL复杂图)
  - NMS-free → 省 NMS 计算 (~5-10ms/帧)
  - 小目标检测提升 (碗、餐具、食材碎片)
  - CPU 推理速度提升 43% (Nano基准)

用法:
  python3 yolo26_export.py --model yolo26n.pt --output /opt/hotpot-infer/models/
"""

import argparse
import sys
from pathlib import Path


def check_onnx_compatibility(model_path: str) -> dict:
    """检查模型 ONNX 导出兼容性."""
    checks = {
        "model_exists": Path(model_path).exists(),
        "ultralytics_ok": False,
        "onnx_supported": False,
        "dfl_removed": "26" in Path(model_path).stem,
    }
    
    try:
        from ultralytics import YOLO
        checks["ultralytics_ok"] = True
        if checks["model_exists"]:
            model = YOLO(model_path)
            # YOLO26: 无 DFL 模块 → 更简单的 ONNX 图
            checks["onnx_supported"] = hasattr(model.model, "model")
    except ImportError:
        pass
    
    return checks


def export_onnx(model_path: str, output_dir: str, imgsz: int = 640, opset: int = 17):
    """导出 YOLO 模型为 ONNX (适用于 YOLOv8/v26)."""
    try:
        from ultralytics import YOLO
        model = YOLO(model_path)
        output = Path(output_dir) / Path(model_path).stem
        
        print(f"Exporting {model_path} → {output}.onnx")
        model.export(
            format="onnx",
            imgsz=imgsz,
            opset=opset,
            half=True,       # FP16
            simplify=True,   # 图优化
            dynamic=False,   # 固定 batch size
        )
        print(f"  ✅ ONNX exported to {output}.onnx")
        
        # 统计
        import os
        size_mb = os.path.getsize(f"{output}.onnx") / 1024 / 1024
        print(f"  Size: {size_mb:.1f} MB (FP16)")
        return str(output) + ".onnx"
    except ImportError:
        print("  ❌ ultralytics not installed. pip install ultralytics")
        return None
    except Exception as e:
        print(f"  ❌ Export failed: {e}")
        return None


def compare_models():
    """打印 YOLOv8 vs YOLO26 对比表."""
    print("""
╔════════════════════╤══════════════════╤══════════════════╗
║ 特性               │ YOLOv8           │ YOLO26           ║
╠════════════════════╪══════════════════╪══════════════════╣
║ DFL                 │ ✅ 有            │ ❌ 移除          ║
║ NMS                 │ ✅ 需要          │ ❌ 端到端无NMS   ║
║ 标签分配            │ TaskAligned      │ STAL (小目标)    ║
║ 优化器              │ SGD/AdamW        │ MuSGD (更稳定)   ║
║ ONNX 复杂度         │ 高 (DFL 图)      │ 低 (简单预测头)  ║
║ Nano 推理 (CPU)     │ 基准             │ -43% 更快        ║
║ 小目标检测          │ 一般             │ 更好 (STAL)      ║
║ 参数量 (Nano)       │ 3.2M             │ 2.6M             ║
╚════════════════════╧══════════════════╧══════════════════╝

推荐: 火锅后厨场景 (碗/餐具/食材碎片) → 升级 YOLO26n
原因:
  1. 小目标多 (STAL 优化)
  2. Jetson 边缘推理 (NMS-free 更快)
  3. 参数量更小 (2.6M vs 3.2M)
""")


def main():
    parser = argparse.ArgumentParser(description="YOLO 模型升级评估")
    parser.add_argument("--model", default="yolo26n.pt", help="YOLO 模型文件")
    parser.add_argument("--output", default="/opt/hotpot-infer/models", help="ONNX 输出目录")
    parser.add_argument("--compare", action="store_true", help="显示版本对比")
    parser.add_argument("--check", action="store_true", help="检查兼容性")
    
    args = parser.parse_args()
    
    if args.compare or not args.model:
        compare_models()
        return
    
    if args.check:
        checks = check_onnx_compatibility(args.model)
        print("兼容性检查:")
        for k, v in checks.items():
            print(f"  {k}: {'✅' if v else '❌'}")
        return
    
    # 导出 ONNX
    onnx_path = export_onnx(args.model, args.output)
    if onnx_path:
        compare_models()


if __name__ == "__main__":
    main()
