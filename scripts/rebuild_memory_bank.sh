#!/bin/bash
# 基于反馈样本重建 Memory Bank
# 用法: bash rebuild_memory_bank.sh [sample_dir]

SAMPLE_DIR="${1:-/tmp/hotpot_feedback/samples}"
BANK_PATH="${2:-/opt/hotpot-infer/models/kitchen_normality_bank.npz}"

echo "🧬 重建 Memory Bank ..."
echo "   样本目录: $SAMPLE_DIR"
echo "   输出路径: $BANK_PATH"

# 备份旧bank
[ -f "$BANK_PATH" ] && cp "$BANK_PATH" "${BANK_PATH}.bak.$(date +%Y%m%d)"

# 收集正确样本
CORRECT_DIR="$SAMPLE_DIR/correct_for_bank"
mkdir -p "$CORRECT_DIR"

python3 -c "
import json, shutil
from pathlib import Path

fb_file = Path('$SAMPLE_DIR').parent / 'feedback.jsonl'
if fb_file.exists():
    for line in open(fb_file):
        r = json.loads(line)
        if r.get('event_type') == 'correct' and r.get('image_path'):
            src = Path(r['image_path'])
            if src.exists():
                dst = Path('$CORRECT_DIR') / src.name
                shutil.copy(src, dst)
                print(f'  ✅ {src.name}')
print(f'共 {len(list(Path(\"$CORRECT_DIR\").glob(\"*.jpg\")))} 个正确样本')
"

# 重建 Bank
cd /opt/hotpot-infer
python3 -c "
import sys; sys.path.insert(0, '.')
from edge.kitchen.inference.anomaly_infer import AnomalyDetector
detector = AnomalyDetector()
detector.build_bank('$CORRECT_DIR', '$BANK_PATH')
print('✅ Memory Bank 重建完成')
"

echo "🧬 重建完成 · $(date)"
