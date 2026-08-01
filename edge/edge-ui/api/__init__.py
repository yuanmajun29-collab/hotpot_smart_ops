"""
Edge UI API 路由注册
将所有 api/*.py 路由模块汇总注册到 FastAPI 应用
"""

from pathlib import Path


def register_routes(app):
    """注册所有 Edge UI API 路由"""

    # === 系统资源 ===
    from api.system_api import router as system_router
    app.include_router(system_router, prefix="/api/v1", tags=["系统"])

    # === 摄像头管理 ===
    from api.camera_api import router as camera_router
    app.include_router(camera_router, prefix="/api/v1", tags=["摄像头"])

    # === IoT传感器 ===
    from api.iot_api import router as iot_router
    app.include_router(iot_router, prefix="/api/v1", tags=["IoT"])

    # === 引擎状态 ===
    from api.engine_api import router as engine_router
    app.include_router(engine_router, prefix="/api/v1", tags=["引擎"])

    # === 诊断工具 ===
    from api.diagnostics_api import router as diag_router
    app.include_router(diag_router, prefix="/api/v1", tags=["诊断"])

    # === 配置管理 (v1.1) ===
    from api.config_api import router as config_router
    app.include_router(config_router, prefix="/api/v1", tags=["配置"])

    # === 平台状态只读 (v1.1) ===
    from api.platform_api import router as platform_router
    app.include_router(platform_router, prefix="/api/v1", tags=["平台"])

    # === L2 PIN认证 (Step 5) ===
    from api.auth_api import router as auth_router
    app.include_router(auth_router, prefix="/api/v1", tags=["认证"])

    # === 货品主数据 (D1-S01 · 2026-08-01) ===
    from api.product_master_api import router as product_router
    app.include_router(product_router, prefix="/api/v1", tags=["货品主数据"])

    print("[Edge UI] API路由注册完成: /api/v1/* (9个模块, 含货品主数据)")
