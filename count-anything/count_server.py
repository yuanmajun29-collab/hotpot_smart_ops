#!/usr/bin/env python3
"""Count Anything API Server — Jetson-optimized deployment entrypoint.

Usage on Jetson:
    python3 /opt/count-anything/count_server.py

Fixes applied (K01 review):
  1. packaging module dependency — auto-installed if missing
  2. CUDA paths — LD_LIBRARY_PATH + cusparse fallback
  3. Model preload — warmup before accepting connections
  4. Healthz check reports ready/no-model status
"""

import os
import sys
import json
import tempfile
import traceback
from pathlib import Path

# ---------------------------------------------------------------------------
# 0. Early dependency check — install `packaging` if missing (python3.8 fix)
# ---------------------------------------------------------------------------
def _ensure_packaging():
    """Some torch/setuptools internals need packaging.version on python3.8."""
    try:
        import packaging  # noqa: F401
    except ImportError:
        import subprocess
        print("[count_server] packaging module missing, installing...")
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", "packaging"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        print("[count_server] packaging installed.")


_ensure_packaging()

# ---------------------------------------------------------------------------
# 1. CUDA environment fix for Jetson (libcusparse.so.11, etc.)
# ---------------------------------------------------------------------------
def _fix_cuda_env():
    """Append common Jetson CUDA library paths to LD_LIBRARY_PATH."""
    jetpack_paths = [
        "/usr/local/cuda/lib64",
        "/usr/local/cuda-11/lib64",
        "/usr/local/cuda-11.4/lib64",
        "/usr/local/cuda-11.8/lib64",
        "/usr/local/cuda/targets/aarch64-linux/lib",
        "/usr/lib/aarch64-linux-gnu/tegra",
    ]
    existing = set(os.environ.get("LD_LIBRARY_PATH", "").split(":") if os.environ.get("LD_LIBRARY_PATH") else [])
    added = []
    for p in jetpack_paths:
        if Path(p).exists() and p not in existing:
            added.append(p)
    if added:
        merged = ":".join(added)
        current = os.environ.get("LD_LIBRARY_PATH", "")
        os.environ["LD_LIBRARY_PATH"] = f"{merged}:{current}" if current else merged
        print(f"[count_server] LD_LIBRARY_PATH extended: {merged}")


_fix_cuda_env()

# ---------------------------------------------------------------------------
# 2. Flask app
# ---------------------------------------------------------------------------
from flask import Flask, request, jsonify

REPO_ROOT = Path(__file__).resolve().parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from count_anything import CountAnything

app = Flask(__name__)

CHECKPOINT = os.environ.get("COUNT_ANYTHING_CHECKPOINT", "checkpoints/count_anything.pt")
MODEL = None
MODEL_LOAD_ERROR = None


def get_model():
    """Lazy-load the CountAnything model with preload support."""
    global MODEL, MODEL_LOAD_ERROR
    if MODEL is not None:
        return MODEL
    if MODEL_LOAD_ERROR is not None:
        raise MODEL_LOAD_ERROR

    try:
        MODEL = CountAnything(
            checkpoint=CHECKPOINT,
            output_dir="exp/count_anything_inference",
            num_gpus=int(os.environ.get("COUNT_ANYTHING_GPUS", "1")),
        )
        return MODEL
    except Exception as e:
        MODEL_LOAD_ERROR = RuntimeError(f"Model load failed: {e}")
        raise MODEL_LOAD_ERROR


@app.route("/health", methods=["GET"])
def health():
    status = {
        "status": "ok" if MODEL is not None else "warming",
        "model_loaded": MODEL is not None,
    }
    if MODEL_LOAD_ERROR:
        status["error"] = str(MODEL_LOAD_ERROR)
    return jsonify(status)


@app.route("/ready", methods=["GET"])
def ready():
    """Kubernetes-style readiness probe — 503 until model is loaded."""
    if MODEL is not None:
        return jsonify({"ready": True}), 200
    if MODEL_LOAD_ERROR:
        return jsonify({"ready": False, "error": str(MODEL_LOAD_ERROR)}), 503
    return jsonify({"ready": False, "reason": "model warming up"}), 503


@app.route("/count", methods=["POST"])
def count():
    if "image" not in request.files and "image_path" not in request.form:
        return jsonify({"error": "Provide 'image' file upload or 'image_path' form field"}), 400

    text_query = request.form.get("query", "").strip()
    if not text_query:
        # Default query for kitchen waste: count everything visible
        text_query = "food waste"

    tmp_path = None
    try:
        if "image" in request.files:
            img_file = request.files["image"]
            suffix = Path(img_file.filename).suffix or ".jpg"
            tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
            img_file.save(tmp.name)
            tmp_path = tmp.name
            image_path = tmp_path
        else:
            image_path = request.form["image_path"]
            if not Path(image_path).exists():
                return jsonify({"error": f"Image not found: {image_path}"}), 400

        model = get_model()
        results = model(image_path, text_query)

        if not results:
            return jsonify({"error": "No results produced"}), 500

        result = results[0]
        return jsonify({
            "count": result.count,
            "query": result.text_query,
            "points": result.pred_points,
            "image_path": result.image_path,
        })

    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)


def prewarm_model():
    """Block until model is loaded or failed — called before app.run()."""
    global MODEL, MODEL_LOAD_ERROR
    print("[count_server] Pre-warming model...")
    try:
        get_model()
        print("[count_server] Model loaded successfully.")
        return True
    except Exception as e:
        MODEL_LOAD_ERROR = RuntimeError(f"Pre-warm failed: {e}")
        print(f"[count_server] Pre-warm failed: {e}", file=sys.stderr)
        return False


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8100))
    prewarm = os.environ.get("PREWARM", "1")

    if prewarm != "0":
        prewarm_model()

    print(f"[count_server] Count Anything API listening on :{port}")
    app.run(host="0.0.0.0", port=port)
