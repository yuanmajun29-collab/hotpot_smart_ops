#!/usr/bin/env python3
"""Export a demo ONNX table classifier for local testing (no trained weights required)."""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = PROJECT_ROOT / "models" / "table_state.onnx"


def main() -> None:
    parser = argparse.ArgumentParser(description="Create minimal demo ONNX classifier")
    parser.add_argument("--output", default=str(DEFAULT_OUT))
    args = parser.parse_args()

    try:
        import onnx
        from onnx import helper, TensorProto
    except ImportError:
        raise SystemExit("pip install onnx first")

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # Tiny conv model: 3x224x224 -> 4 classes (for pipeline integration testing)
    inp = helper.make_tensor_value_info("input", TensorProto.FLOAT, [1, 3, 224, 224])
    out = helper.make_tensor_value_info("output", TensorProto.FLOAT, [1, 4])

    w = np.random.randn(4, 3, 3, 3).astype(np.float32) * 0.01
    b = np.zeros(4, dtype=np.float32)
    w_init = helper.make_tensor("W", TensorProto.FLOAT, list(w.shape), w.flatten().tolist())
    b_init = helper.make_tensor("B", TensorProto.FLOAT, list(b.shape), b.flatten().tolist())

    node = helper.make_node("Conv", ["input", "W", "B"], ["conv_out"], kernel_shape=[3, 3], pads=[1, 1, 1, 1])
    pool = helper.make_node("GlobalAveragePool", ["conv_out"], ["pooled"])
    flatten = helper.make_node("Flatten", ["pooled"], ["flat"])
    fc_w = helper.make_tensor("FCW", TensorProto.FLOAT, [4, 4], (np.eye(4, dtype=np.float32).flatten().tolist()))
    fc_b = helper.make_tensor("FCB", TensorProto.FLOAT, [4], [0.0, 0.0, 0.0, 0.0])
    gemm = helper.make_node("Gemm", ["flat", "FCW", "FCB"], ["output"])

    graph = helper.make_graph(
        [node, pool, flatten, gemm],
        "hotpot_table_demo",
        [inp],
        [out],
        [w_init, b_init, fc_w, fc_b],
    )
    model = helper.make_model(graph, opset_imports=[helper.make_opsetid("", 13)])
    onnx.save(model, str(out_path))
    print(f"[OK] Demo model written to {out_path}")
    print("     Replace with real YOLO-exported ONNX for production accuracy.")


if __name__ == "__main__":
    main()
