# 模型目录

将训练导出的 ONNX 模型放置于此，视觉 worker 可通过 `--backend yolo` 加载。

| 文件名 | 用途 | 类别 |
|--------|------|------|
| `table_state.onnx` | 前厅桌态 ROI 分类 | empty, dining, need_clean, checkout |
| `kitchen_compliance.onnx` | 后厨合规分类 | kitchen_ok, kitchen_no_hat, kitchen_no_mask, kitchen_smoke |

也可通过环境变量指定路径：

```bash
export HOTPOT_TABLE_MODEL=/path/to/table_state.onnx
export HOTPOT_KITCHEN_MODEL=/path/to/kitchen_compliance.onnx
python3 edge/stream/vision_worker.py --backend yolo --store-id store_yuhuan ...
```

## 导出示例（YOLOv8 分类）

```bash
yolo export model=runs/classify/table_v1/weights/best.pt format=onnx imgsz=224
cp runs/classify/table_v1/weights/best.onnx models/table_state.onnx
```

未放置模型时，`--backend yolo` 自动回退 mock 启发式检测。
