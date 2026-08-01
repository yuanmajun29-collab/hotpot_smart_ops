"""
火瞳边缘盒子 · Edge UI FastAPI 应用入口

用法:
  cd edge/edge-ui && python3 main.py --port 9080
  python3 main.py --config /path/to/conf/
"""

import argparse
import sys
from pathlib import Path

# 确保本目录在path最前面（用于直接导入 api/ 模块）
sys.path.insert(0, str(Path(__file__).parent))
# 确保父目录在path中（用于导入 edge.common 等）
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware


def create_app(config_dir: str = None) -> FastAPI:
    """创建 FastAPI 应用实例"""

    app = FastAPI(
        title="火瞳 Edge UI",
        description="冯校长火锅连锁 · 边缘盒子配置管理界面 v1.1",
        version="1.1.0",
        docs_url="/api/docs",       # Swagger UI (仅开发环境)
        redoc_url=None,             # 禁用ReDoc节省资源
    )

    # CORS: 仅允许局域网段
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # MVP阶段全开，后续限制局域网
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ── 注册 API 路由（直接导入，不依赖包名） ──
    from api import register_routes
    register_routes(app)

    # ── L2 PIN 认证: 通过 Depends 机制注入到各 API 模块 (Step 5) ──
    # 认证逻辑见 middleware.py (get_current_session / AuthRequired)
    # 各 api/*.py 路由函数已添加 _: AuthRequired 参数
    print("[Edge UI] L2 PIN认证已启用 (Depends模式, 保护26个端点)")

    # ── 挂载静态文件 ──
    ui_dir = Path(__file__).parent
    if (ui_dir / "index.html").exists():
        app.mount("/", StaticFiles(directory=str(ui_dir), html=True), name="edge-ui")
        print(f"[Edge UI] 静态文件目录: {ui_dir}")

    return app


def main():
    parser = argparse.ArgumentParser(description='火瞳 Edge UI (FastAPI版)')
    parser.add_argument('--port', type=int, default=9080, help=f'端口号 (默认 9080)')
    parser.add_argument('--host', type=str, default='0.0.0.0', help='监听地址')
    args = parser.parse_args()

    app = create_app()

    import uvicorn

    print(f"""
╔══════════════════════════════════════════════════╗
║     🔥 火瞳边缘盒子 · Edge UI v1.1 (FastAPI)      ║
╠══════════════════════════════════════════════════╣
║  地址: http://{args.host:<28} ║
║  首页: http://{args.host}:{args.port:<23} ║
║  API文档: http://{args.host}:{args.port}/api/docs{'':>12} ║
╚══════════════════════════════════════════════════╝
    """)

    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == '__main__':
    main()
