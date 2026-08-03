#!/usr/bin/env python3
"""
Hub 数据库自动初始化模块

P0-B Phase 2 核心功能：
- Hub 启动时自动检查并创建审计表
- 零配置部署，无需手动执行SQL
- 支持幂等操作（重复执行安全）

使用方式:
    from hotpot_platform.cloud.event_hub.middleware.db_init import init_audit_schema
    # 在 app.py startup() 中调用
    init_audit_schema()
"""

from __future__ import annotations

import os
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# 审计Schema SQL文件路径
_AUDIT_SCHEMA_SQL = Path(__file__).parent / "audit_schema.sql"

# 产品主数据表DDL
_PRODUCT_MASTER_DDL = """
-- 产品主数据表 (从Edge UI product_master.json迁移)
CREATE TABLE IF NOT EXISTS product_master (
    id              SERIAL PRIMARY KEY,
    product_code    VARCHAR(32) NOT NULL UNIQUE,
    name            VARCHAR(128) NOT NULL,
    category        VARCHAR(64) NOT NULL DEFAULT '',
    sub_category    VARCHAR(64),
    unit            VARCHAR(16) NOT NULL DEFAULT '份',
    spec            VARCHAR(64),
    cost_price      DECIMAL(10, 2) DEFAULT 0,
    sale_price      DECIMAL(10, 2) DEFAULT 0,
    supplier        VARCHAR(128),
    supplier_code   VARCHAR(32),
    shelf_life_days INTEGER DEFAULT 7,
    storage_temp_min DECIMAL(5, 2),
    storage_temp_max DECIMAL(5, 2),
    is_frozen       BOOLEAN DEFAULT FALSE,
    is_liquid       BOOLEAN DEFAULT FALSE,
    tags            TEXT[],
    status          VARCHAR(16) NOT NULL DEFAULT 'active',
    -- active / inactive / discontinued
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    
    CONSTRAINT uk_product_code UNIQUE (product_code)
);

CREATE INDEX IF NOT EXISTS idx_product_category ON product_master(category);
CREATE INDEX IF NOT EXISTS idx_product_supplier ON product_master(supplier);
CREATE INDEX IF NOT EXISTS idx_product_status ON product_master(status);

COMMENT ON TABLE product_master IS '产品主数据 - 从Edge UI迁移，Hub唯一数据源';
"""


def _get_database_url() -> Optional[str]:
    """获取数据库连接URL"""
    return os.environ.get("HOTPOT_DATABASE_URL", "")


def _execute_sql_raw(db_url: str, sql: str) -> bool:
    """
    执行原始SQL（用于DDL）

    Args:
        db_url: PostgreSQL连接URL
        sql: 要执行的SQL语句

    Returns:
        是否执行成功
    """
    try:
        import psycopg2
        conn = psycopg2.connect(db_url)
        conn.autocommit = True  # DDL需要autocommit
        cursor = conn.cursor()
        cursor.execute(sql)
        cursor.close()
        conn.close()
        return True
    except ImportError:
        logger.warning("psycopg2未安装，尝试使用asyncpg...")
        return False
    except Exception as e:
        logger.error(f"执行SQL失败: {e}")
        return False


def _execute_sql_asyncpg(db_url: str, sql: str) -> bool:
    """使用asyncpg执行SQL（备选方案）"""
    try:
        import asyncio
        import asyncpg

        async def _run():
            conn = await asyncpg.connect(db_url)
            await conn.execute(sql)
            await conn.close()

        asyncio.get_event_loop().run_until_complete(_run())
        return True
    except Exception as e:
        logger.error(f"asyncpg执行失败: {e}")
        return False


def execute_sql(db_url: str, sql: str) -> bool:
    """执行SQL（自动选择驱动）"""
    if _execute_sql_raw(db_url, sql):
        return True
    return _execute_sql_asyncpg(db_url, sql)


def init_audit_schema() -> bool:
    """
    初始化审计Schema (5张append-only表 + 视图 + 函数)

    Returns:
        是否初始化成功
    """
    db_url = _get_database_url()
    if not db_url:
        logger.info("HOTPOT_DATABASE_URL未设置，跳过审计Schema初始化（使用SQLite模式）")
        return False

    # 检查SQL文件是否存在
    if not _AUDIT_SCHEMA_SQL.exists():
        logger.error(f"审计Schema文件不存在: {_AUDIT_SCHEMA_SQL}")
        return False

    # 读取并执行SQL
    sql_content = _AUDIT_SCHEMA_SQL.read_text(encoding='utf-8')

    logger.info("=" * 60)
    logger.info("开始初始化审计Schema (P0-B Phase 2)")
    logger.info("=" * 60)

    success = execute_sql(db_url, sql_content)

    if success:
        logger.info("✅ 审计Schema初始化成功")
        logger.info("  - audit_events (审计事件主表)")
        logger.info("  - approval_tasks (审批任务表)")
        logger.info("  - operation_log (操作日志表)")
        logger.info("  - data_change_log (数据变更追踪表)")
        logger.info("  - rbac_change_log (RBAC权限变更审计表)")
        logger.info("  - v_audit_dashboard (30天仪表盘视图)")
        logger.info("  - cleanup_old_audit_data() (清理函数)")
    else:
        logger.error("❌ 审计Schema初始化失败")

    return success


def init_product_master_table() -> bool:
    """
    初始化产品主数据表

    Returns:
        是否创建成功
    """
    db_url = _get_database_url()
    if not db_url:
        logger.info("HOTPOT_DATABASE_URL未设置，跳过产品主数据表初始化")
        return False

    logger.info("创建产品主数据表 product_master...")
    success = execute_sql(db_url, _PRODUCT_MASTER_DDL)

    if success:
        logger.info("✅ 产品主数据表创建成功")
    else:
        logger.error("❌ 产品主数据表创建失败")

    return success


def migrate_product_master_json(json_path: str, db_url: Optional[str] = None) -> dict:
    """
    迁移产品主数据从JSON到PG

    Args:
        json_path: JSON文件路径
        db_url: PG连接URL（可选，默认从环境变量获取）

    Returns:
        迁移结果统计 {success: int, failed: int, errors: list}
    """
    import json

    result = {"success": 0, "failed": 0, "errors": [], "skipped": 0}

    # 获取DB URL
    db_url = db_url or _get_database_url()
    if not db_url:
        result["errors"].append("HOTPOT_DATABASE_URL未设置")
        return result

    # 读取JSON
    json_file = Path(json_path)
    if not json_file.exists():
        result["errors"].append(f"JSON文件不存在: {json_path}")
        return result

    try:
        data = json.loads(json_file.read_text(encoding='utf-8'))
    except Exception as e:
        result["errors"].append(f"JSON解析失败: {e}")
        return result

    # 支持两种格式: list 或 dict
    products = data if isinstance(data, list) else data.get("products", [])

    if not products:
        result["errors"].append("JSON中没有产品数据")
        return result

    logger.info(f"开始迁移 {len(products)} 个产品到PG...")

    # 批量插入（使用UPSERT避免重复）
    for product in products:
        try:
            code = product.get("code") or product.get("product_code") or product.get("sku")
            name = product.get("name") or product.get("product_name")

            if not code or not name:
                result["skipped"] += 1
                continue

            insert_sql = f"""
                INSERT INTO product_master (
                    product_code, name, category, sub_category, unit, spec,
                    cost_price, sale_price, supplier, supplier_code,
                    shelf_life_days, is_frozen, is_liquid, tags, status
                ) VALUES (
                    '{code}', '{name}', 
                    '{product.get("category", "")}', '{product.get("sub_category", "")}',
                    '{product.get("unit", "份")}', '{product.get("spec", "")}',
                    {product.get("cost_price", 0)}, {product.get("sale_price", 0)},
                    '{product.get("supplier", "")}', '{product.get("supplier_code", "")}',
                    {product.get("shelf_life_days", 7)},
                    {str(product.get("is_frozen", False)).lower()},
                    {str(product.get("is_liquid", False)).lower()},
                    ARRAY{product.get("tags", [])}::TEXT[],
                    '{product.get("status", "active")}'
                )
                ON CONFLICT (product_code) DO UPDATE SET
                    name = EXCLUDED.name,
                    category = EXCLUDED.category,
                    updated_at = NOW()
            """

            if execute_sql(db_url, insert_sql):
                result["success"] += 1
            else:
                result["failed"] += 1
                result["errors"].append(f"插入失败: {code}")

        except Exception as e:
            result["failed"] += 1
            result["errors"].append(f"处理异常 [{code}]: {e}")

    logger.info(
        f"迁移完成: ✅{result['success']} ❌{result['failed']} ⏭️{result['skipped']}"
    )

    return result


def init_all_schemas() -> dict:
    """
    初始化所有Schema（审计 + 产品主数据）

    Returns:
        各模块初始化结果
    """
    results = {
        "audit_schema": init_audit_schema(),
        "product_master": init_product_master_table(),
    }

    all_success = all(results.values())

    if all_success:
        logger.info("=" * 60)
        logger.info("✅ 所有Schema初始化完成 (P0-B Phase 2)")
        logger.info("=" * 60)
    else:
        logger.warning("=" * 60)
        logger.warning("⚠️ 部分Schema初始化失败，请检查日志")
        logger.warning("=" * 60)

    return results


# ============================================================
# 便捷函数：供命令行直接调用
# ============================================================

if __name__ == "__main__":
    """命令行入口: python -m hotpot_platform.cloud.event_hub.middleware.db_init"""

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    )

    import sys

    if len(sys.argv) > 1:
        cmd = sys.argv[1]

        if cmd == "audit":
            success = init_audit_schema()
            sys.exit(0 if success else 1)

        elif cmd == "products":
            success = init_product_master_table()
            sys.exit(0 if success else 1)

        elif cmd == "migrate" and len(sys.argv) > 2:
            json_path = sys.argv[2]
            result = migrate_product_master_json(json_path)
            print(f"\n迁移结果:")
            print(f"  成功: {result['success']}")
            print(f"  失败: {result['failed']}")
            print(f"  跳过: {result['skipped']}")
            if result['errors']:
                print(f"\n错误:")
                for err in result['errors'][:5]:  # 只显示前5个错误
                    print(f"  - {err}")
            sys.exit(0 if result['failed'] == 0 else 1)

        elif cmd == "all":
            results = init_all_schemas()
            sys.exit(0 if all(results.values()) else 1)

        else:
            print(f"用法: python {__file__} [audit|products|migrate <json>|all]")
            sys.exit(1)

    else:
        # 默认执行全部初始化
        results = init_all_schemas()
        sys.exit(0 if all(results.values()) else 1)
