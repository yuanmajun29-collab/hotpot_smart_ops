#!/bin/bash
# 边缘盒子统一入口 — 按环境变量切模式
# HOTPOT_MODE=agent        → agent server (:9100)（默认）
# HOTPOT_MODE=pipeline     → 后厨推理管线（standalone）
# HOTPOT_MODE=front-hall   → 前厅推理（standalone）

MODE="${HOTPOT_MODE:-agent}"

case "$MODE" in
    agent)
        exec python3 edge/agent/server.py
        ;;
    pipeline)
        exec python3 edge/kitchen/inference/pipeline.py --frame "${HOTPOT_FRAME:-/tmp/ipc_frames/latest.jpg}"
        ;;
    front-hall)
        exec python3 edge/front_hall/inference/pipeline.py --image "${HOTPOT_IMAGE}" --table-id "${HOTPOT_TABLE_ID:-T01}"
        ;;
    *)
        echo "Unknown HOTPOT_MODE=$MODE (expected: agent|pipeline|front-hall)"
        exit 1
        ;;
esac
