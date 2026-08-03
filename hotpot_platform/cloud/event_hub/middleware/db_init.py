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


def _get_sqlite_path() -> Path:
    """获取SQLite数据库文件路径"""
    default_path = Path(__file__).parent.parent.parent.parent / "data" / "hotpot_verification.db"
    return Path(os.environ.get("HOTPOT_SQLITE_PATH", str(default_path)))


def _execute_sqlite(sql: str, db_path: Optional[Path] = None) -> bool:
    """
    使用SQLite执行SQL（用于本地验证，无需安装PG）

    Args:
        sql: 要执行的SQL语句（自动转换PG语法到SQLite）
        db_path: SQLite数据库文件路径

    Returns:
        是否执行成功
    """
    import sqlite3

    db_path = db_path or _get_sqlite_path()

    # 确保目录存在
    db_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()

        # PG → SQLite 语法转换
        sql_converted = _convert_pg_to_sqlite(sql)

        # 分割多条SQL语句（按分号分割）
        statements = [s.strip() for s in sql_converted.split(';') if s.strip() and not s.strip().startswith('--')]

        success_count = 0
        for stmt in statements:
            try:
                cursor.execute(stmt)
                success_count += 1
            except Exception as e:
                # 忽略已存在的表错误（SQLite的IF NOT EXISTS会跳过）
                if "already exists" not in str(e):
                    logger.debug(f"SQLite执行语句失败: {e}")

        conn.commit()
        cursor.close()
        conn.close()

        logger.info(f"✅ SQLite执行成功: {success_count}/{len(statements)} 条语句")
        return True

    except Exception as e:
        logger.error(f"❌ SQLite执行失败: {e}")
        return False


def _convert_pg_to_sqlite(sql: str) -> str:
    """
    将PostgreSQL SQL转换为SQLite兼容语法

    转换规则:
    - BIGSERIAL/SERIAL → INTEGER PRIMARY KEY AUTOINCREMENT
    - TIMESTAMPTZ → TIMESTAMP
    - DECIMAL(m,n) → REAL
    - BOOLEAN → INTEGER (0/1)
    - TEXT[] → TEXT (JSON格式存储)
    - UUID → VARCHAR(36)
    - INET → VARCHAR(45)
    - JSONB → TEXT
    - NOW() → datetime('now')
    - uuid_generate_v4() → lower(hex(randomblob(16)))
    - TRUE/FALSE → 1/0
    - ILIKE → LIKE (SQLite默认不区分大小写)
    - 删除COMMENT ON语句
    - 删除CREATE EXTENSION语句
    - 删除CREATE FUNCTION/VIEW/TRIGGER语句
    """
    import re

    # 移除注释行
    lines = sql.split('\n')
    lines = [l for l in lines if not l.strip().startswith('--') and not l.strip().startswith('#')]
    sql = '\n'.join(lines)

    # 删除不支持的语句块（按复杂度排序）
    # 1. CREATE FUNCTION ... $$ ... $$ (多行函数体)
    sql = re.sub(
        r'CREATE\s+(OR\s+REPLACE\s+)?FUNCTION\s+\w+\s*\([^)]*\)\s*'
        r'(RETURNS\s+\w+(\s+NULL)?\s*)?'
        r'\$\$.*?\$\$',  # 匹配 $$...$$ 函数体
        '', sql, flags=re.IGNORECASE | re.DOTALL
    )

    # 2. COMMENT ON TABLE/COLUMN (可能跨行)
    sql = re.sub(r'COMMENT\s+ON\s+(TABLE|COLUMN)\s+\S+\s+IS\s+\'.*?\';', '', sql, flags=re.IGNORECASE | re.DOTALL)

    # 3. 其他简单语句
    sql = re.sub(r'CREATE EXTENSION.*?;', '', sql, flags=re.IGNORECASE | re.DOTALL)
    sql = re.sub(r'COMMENT ON \w+ \w+ IS .*?;', '', sql, flags=re.DOTALL | re.IGNORECASE)  # 兼容旧模式
    sql = re.sub(r'CREATE (OR REPLACE )?VIEW.*?;', '', sql, flags=re.DOTALL | re.IGNORECASE)
    sql = re.sub(r'CREATE TRIGGER.*?;', '', sql, flags=re.DOTALL | re.IGNORECASE)

    # 4. PG特有语法
    # INTERVAL '24 hours' → 空或具体值（SQLite不支持）
    sql = re.sub(r"INTERVAL\s+'[^']+'", '', sql, flags=re.IGNORECASE)

    # 处理 DEFAULT (NOW()/CURRENT_TIMESTAMP + INTERVAL ...) 残留
    # 例: DEFAULT (CURRENT_TIMESTAMP + ) → DEFAULT CURRENT_TIMESTAMP
    sql = re.sub(r'DEFAULT\s*\(\s*CURRENT_TIMESTAMP\s*\+\s*\)', 'DEFAULT CURRENT_TIMESTAMP', sql, flags=re.IGNORECASE)
    sql = re.sub(r'DEFAULT\s*\(\s*NOW\(\)\s*\+\s*\)', 'DEFAULT CURRENT_TIMESTAMP', sql, flags=re.IGNORECASE)

    # 5. 删除外键约束中的REFERENCES（如果被引用表不存在会导致错误）
    # 保留FOREIGN KEY定义但先不强制执行（SQLite会在INSERT时检查）
    # 注意: 这里不做处理，让SQLite自然报错并跳过

    # 类型替换（按顺序，从复杂到简单）
    # 注意: BIGSERIAL/SERIAL 后面通常跟着 PRIMARY KEY，需要一起替换避免重复
    sql = re.sub(r'\bBIGSERIAL\s+PRIMARY\s+KEY\b', 'INTEGER PRIMARY KEY AUTOINCREMENT', sql, flags=re.IGNORECASE)
    sql = re.sub(r'\bSERIAL\s+PRIMARY\s+KEY\b', 'INTEGER PRIMARY KEY AUTOINCREMENT', sql, flags=re.IGNORECASE)
    # 单独的BIGSERIAL/SERIAL（无PRIMARY KEY）
    sql = re.sub(r'\bBIGSERIAL\b(?!\s*PRIMARY)', 'INTEGER PRIMARY KEY AUTOINCREMENT', sql, flags=re.IGNORECASE)
    sql = re.sub(r'\bSERIAL\b(?!\s*PRIMARY)', 'INTEGER PRIMARY KEY AUTOINCREMENT', sql, flags=re.IGNORECASE)
    sql = re.sub(r'\bTIMESTAMPTZ\b', 'TIMESTAMP', sql, flags=re.IGNORECASE)
    sql = re.sub(r'\bDECIMAL\s*\(\s*\d+\s*,\s*\d+\s*\)', 'REAL', sql, flags=re.IGNORECASE)
    sql = re.sub(r'\bBOOLEAN\b', 'INTEGER', sql, flags=re.IGNORECASE)
    sql = re.sub(r'\bTEXT\s*\[\s*\]', 'TEXT', sql, flags=re.IGNORECASE)
    sql = re.sub(r'\bUUID\b', 'VARCHAR(36)', sql, flags=re.IGNORECASE)
    sql = re.sub(r'\bINET\b', 'VARCHAR(45)', sql, flags=re.IGNORECASE)
    sql = re.sub(r'\bJSONB\b', 'TEXT', sql, flags=re.IGNORECASE)

    # 函数替换
    sql = re.sub(r'\bNOW\(\)', "CURRENT_TIMESTAMP", sql, flags=re.IGNORECASE)
    # SQLite的datetime('now')不能用于DEFAULT，改为CURRENT_TIMESTAMP
    sql = re.sub(r"datetime\('now'\)", 'CURRENT_TIMESTAMP', sql, flags=re.IGNORECASE)
    sql = re.sub(r'\buuid_generate_v4\(\)', "''", sql, flags=re.IGNORECASE)
    sql = re.sub(r'\bTRUE\b', '1', sql, flags=re.IGNORECASE)
    sql = re.sub(r'\bFALSE\b', '0', sql, flags=re.IGNORECASE)

    # ARRAY[] → JSON数组文本
    def replace_array(match):
        content = match.group(1)
        return f"'[{content}]'"

    sql = re.sub(r"ARRAY\[([^\]]*)\]::TEXT\[\]", replace_array, sql)

    # UNIQUE约束处理（删除表级CONSTRAINT ... UNIQUE）
    sql = re.sub(r',\s*CONSTRAINT \w+ UNIQUE \([^)]+\)', '', sql, flags=re.IGNORECASE)

    # DEFAULT值中的函数调用需要特殊处理
    # SQLite不支持函数调用作为DEFAULT值（除datetime/randomblob等少数）
    sql = re.sub(r"DEFAULT uuid_generate_v4\(\)", "DEFAULT (lower(hex(randomblob(16))))", sql, flags=re.IGNORECASE)
    # 将复杂的DEFAULT函数调用替换为空字符串（应用层负责填充）
    sql = re.sub(r"DEFAULT lower\(hex\(randomblob\(16\)\)\)", "DEFAULT ''", sql, flags=re.IGNORECASE)

    return sql


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

    优先使用PostgreSQL，如果未配置则自动降级到SQLite验证模式

    Returns:
        是否初始化成功
    """
    db_url = _get_database_url()

    # 检查SQL文件是否存在
    if not _AUDIT_SCHEMA_SQL.exists():
        logger.error(f"审计Schema文件不存在: {_AUDIT_SCHEMA_SQL}")
        return False

    # 读取SQL
    sql_content = _AUDIT_SCHEMA_SQL.read_text(encoding='utf-8')

    logger.info("=" * 60)
    logger.info("开始初始化审计Schema (P0-B Phase 2)")
    logger.info("=" * 60)

    if db_url:
        # PG模式
        success = execute_sql(db_url, sql_content)
        if success:
            logger.info("✅ 审计Schema初始化成功 (PostgreSQL)")
            logger.info("  - audit_events (审计事件主表)")
            logger.info("  - approval_tasks (审批任务表)")
            logger.info("  - operation_log (操作日志表)")
            logger.info("  - data_change_log (数据变更追踪表)")
            logger.info("  - rbac_change_log (RBAC权限变更审计表)")
            logger.info("  - v_audit_dashboard (30天仪表盘视图)")
            logger.info("  - cleanup_old_audit_data() (清理函数)")
        else:
            logger.error("❌ PostgreSQL审计Schema初始化失败，尝试SQLite...")
            success = _execute_sqlite(sql_content)
            if success:
                logger.info("✅ 审计Schema初始化成功 (SQLite降级模式)")
    else:
        # SQLite模式（本地验证）
        logger.info("HOTPOT_DATABASE_URL未设置，使用SQLite验证模式")
        sqlite_path = _get_sqlite_path()
        logger.info(f"SQLite数据库路径: {sqlite_path}")
        success = _execute_sqlite(sql_content)
        if success:
            logger.info("✅ 审计Schema初始化成功 (SQLite验证模式)")

    if not success:
        logger.error("❌ 审计Schema初始化失败")

    return success


def init_product_master_table() -> bool:
    """
    初始化产品主数据表

    Returns:
        是否创建成功
    """
    db_url = _get_database_url()

    logger.info("创建产品主数据表 product_master...")

    if db_url:
        # PG模式
        success = execute_sql(db_url, _PRODUCT_MASTER_DDL)
        if success:
            logger.info("✅ 产品主数据表创建成功 (PostgreSQL)")
        else:
            logger.error("❌ PostgreSQL产品主数据表创建失败，尝试SQLite...")
            success = _execute_sqlite(_PRODUCT_MASTER_DDL)
            if success:
                logger.info("✅ 产品主数据表创建成功 (SQLite降级模式)")
    else:
        # SQLite模式
        logger.info("使用SQLite验证模式")
        success = _execute_sqlite(_PRODUCT_MASTER_DDL)
        if success:
            logger.info("✅ 产品主数据表创建成功 (SQLite验证模式)")

    if not success:
        logger.error("❌ 产品主数据表创建失败")

    return success


def migrate_product_master_json(json_path: str, db_url: Optional[str] = None) -> dict:
    """
    迁移产品主数据从JSON到数据库（PG或SQLite）

    Args:
        json_path: JSON文件路径
        db_url: PG连接URL（可选，默认从环境变量获取；未设置则使用SQLite）

    Returns:
        迁移结果统计 {success: int, failed: int, errors: list}
    """
    import json

    result = {"success": 0, "failed": 0, "errors": [], "skipped": 0}

    # 获取DB URL
    db_url = db_url or _get_database_url()
    use_sqlite = not db_url

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

    # 支持多种格式:
    # 格式1: {"products": {"SKU1": {...}, "SKU2": {...}}}
    # 格式2: [{"code": ..., ...}, ...]
    # 格式3: {"SKU1": {...}, "SKU2": {...}}
    if isinstance(data, dict):
        if "products" in data and isinstance(data["products"], dict):
            # 格式1: 嵌套字典
            products = list(data["products"].values())
        elif all(isinstance(v, dict) for v in data.values()):
            # 格式3: 扁平字典（每个value是产品）
            products = list(data.values())
        else:
            products = []
    elif isinstance(data, list):
        # 格式2: 直接列表
        products = data
    else:
        products = []

    if not products:
        result["errors"].append("JSON中没有产品数据")
        return result

    logger.info(f"开始迁移 {len(products)} 个产品到{'SQLite' if use_sqlite else 'PG'}...")

    # 批量插入（使用UPSERT避免重复）
    for product in products:
        try:
            code = product.get("sku_code") or product.get("code") or product.get("product_code")
            name = product.get("name") or product.get("product_name")

            if not code or not name:
                result["skipped"] += 1
                continue

            if use_sqlite:
                # SQLite模式插入
                # 自动识别冻品/液体
                category = str(product.get("category", "")).upper()
                is_frozen = 1 if any(k in category for k in ["FROZEN", "冻", "ICE"]) else 0
                is_liquid = 1 if any(k in category for k in ["DRINK", "饮料", "LIQUID", "酒", "汁"]) else 0

                # 价格映射: unit_price -> cost_price
                cost_price = product.get("cost_price") or product.get("unit_price") or 0
                sale_price = product.get("sale_price") or product.get("unit_price") or 0

                insert_sql = f"""
                    INSERT OR REPLACE INTO product_master (
                        product_code, name, category, sub_category, unit, spec,
                        cost_price, sale_price, supplier, supplier_code,
                        shelf_life_days, is_frozen, is_liquid, tags, status
                    ) VALUES (
                        '{code}', '{name}',
                        '{product.get("category", "")}', '{product.get("sub_category", "")}',
                        '{product.get("unit", "份")}', '{product.get("specification", product.get("spec", ""))}',
                        {cost_price}, {sale_price},
                        '{product.get("supplier_name", product.get("supplier", ""))}', '{product.get("supplier_code", "")}',
                        {product.get("shelf_life_days", 7)},
                        {is_frozen},
                        {is_liquid},
                        '{str(product.get("tags", []))}',
                        '{product.get("status", "active")}'
                    )
                """
                if _execute_sqlite(insert_sql):
                    result["success"] += 1
                else:
                    result["failed"] += 1
                    result["errors"].append(f"SQLite插入失败: {code}")
            else:
                # PG模式插入
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
                    result["errors"].append(f"PG插入失败: {code}")

        except Exception as e:
            result["failed"] += 1
            result["errors"].append(f"处理异常 [{code}]: {e}")

    logger.info(
        f"迁移完成: ✅{result['success']} ❌{result['failed']} ⏭️{result['skipped']} "
        f"[{'SQLite' if use_sqlite else 'PG'}]"
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
