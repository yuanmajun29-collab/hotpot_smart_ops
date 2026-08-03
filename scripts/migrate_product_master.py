#!/usr/bin/env python3
"""
产品主数据迁移脚本: Edge UI JSON → PostgreSQL (Hub)

P0-B Phase 2 数据迁移

用法:
    # 方式1: 命令行直接执行
    python scripts/migrate_product_master.py

    # 方式2: 指定JSON路径
    python scripts/migrate_product_master.py --json edge/edge-ui/data/product_master.json

    # 方式3: 指定数据库URL
    python scripts/migrate_product_master.py --db-url "postgresql://user:pass@host:5432/hotpot"

特性:
- 支持增量迁移（UPSERT，重复不报错）
- 字段自动映射（JSON → PG列）
- 数据验证和清理
- 迁移报告生成
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

# 确保项目根目录在Python路径中
_SCRIPT_DIR = Path(__file__).parent
_PROJECT_ROOT = _SCRIPT_DIR.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)


# ============================================================
# 字段映射: JSON → PG
# ============================================================

FIELD_MAPPING = {
    # JSON字段 -> PG列名
    "sku_code": "product_code",
    "name": "name",
    "specification": "spec",
    "brand": "supplier",  # brand映射到supplier（简化）
    "unit_price": "cost_price",  # 进价
    "unit": "unit",
    "category": "category",
    "supplier_name": "supplier",
    "storage_area": None,  # 特殊处理 -> is_frozen/is_liquid
    "shelf_life_days": "shelf_life_days",
    "tags": "tags",
    "status": "status",
}

# 冻品分类关键词
FROZEN_KEYWORDS = ["FROZEN", "冷冻", "冻品", "ICE", "冰"]
LIQUID_KEYWORDS = ["液体", "饮料", "酒水", "DRINK", "BEVERAGE", "SAUCE", "酱料"]


def detect_storage_type(category: str, storage_area: Optional[str]) -> tuple:
    """
    根据分类和存储区域判断是否冻品/液体

    Returns:
        (is_frozen, is_liquid)
    """
    cat_upper = (category or "").upper()
    area_upper = (storage_area or "").upper()

    is_frozen = any(kw in cat_upper or kw in area_upper for kw in FROZEN_KEYWORDS)
    is_liquid = any(kw in cat_upper or kw in area_upper for kw in LIQUID_KEYWORDS)

    return is_frozen, is_liquid


def transform_product(sku_code: str, product_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    转换单个产品数据从JSON格式到PG格式

    Args:
        sku_code: 产品SKU编码
        product_data: JSON中的产品数据

    Returns:
        PG格式的产品字典
    """
    pg_data = {
        "product_code": sku_code,
        "name": product_data.get("name", ""),
        "category": product_data.get("category", ""),
        "sub_category": "",  # JSON中没有此字段
        "unit": product_data.get("unit", "份"),
        "spec": product_data.get("specification", ""),
        "cost_price": float(product_data.get("unit_price", 0) or 0),
        "sale_price": 0,  # JSON中没有售价，默认0
        "supplier": product_data.get("supplier_name") or product_data.get("brand", ""),
        "supplier_code": product_data.get("supplier_id", "") or "",
        "shelf_life_days": int(product_data.get("shelf_life_days", 7) or 7),
        "storage_temp_min": None,
        "storage_temp_max": None,
        "tags": product_data.get("tags") or [],
        "status": product_data.get("status", "active"),
    }

    # 检测存储类型
    is_frozen, is_liquid = detect_storage_type(
        pg_data["category"],
        product_data.get("storage_area")
    )
    pg_data["is_frozen"] = is_frozen
    pg_data["is_liquid"] = is_liquid

    return pg_data


def load_json(json_path: str) -> Dict[str, Any]:
    """加载JSON文件"""
    path = Path(json_path)

    if not path.exists():
        raise FileNotFoundError(f"JSON文件不存在: {json_path}")

    with open(path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    logger.info(f"成功加载JSON: {json_path} ({len(data.get('products', {}))} 个产品)")

    return data


def generate_upsert_sql(pg_data: Dict[str, Any]) -> str:
    """生成UPSERT SQL语句"""

    # 安全转义字符串值
    def escape(val):
        if val is None:
            return "NULL"
        if isinstance(val, bool):
            return "TRUE" if val else "FALSE"
        if isinstance(val, (int, float)):
            return str(val)
        if isinstance(val, list):
            # PG数组
            items = ["'" + str(v).replace("'", "''") + "'" for v in val]
            return f"ARRAY[{','.join(items)}]::TEXT[]"
        # 字符串
        escaped = str(val).replace("'", "''")
        return f"'{escaped}'"

    sql = f"""
        INSERT INTO product_master (
            product_code, name, category, sub_category, unit, spec,
            cost_price, sale_price, supplier, supplier_code,
            shelf_life_days, is_frozen, is_liquid, tags, status,
            created_at, updated_at
        ) VALUES (
            {escape(pg_data['product_code'])},
            {escape(pg_data['name'])},
            {escape(pg_data['category'])},
            {escape(pg_data['sub_category'])},
            {escape(pg_data['unit'])},
            {escape(pg_data['spec'])},
            {pg_data['cost_price']},
            {pg_data['sale_price']},
            {escape(pg_data['supplier'])},
            {escape(pg_data['supplier_code'])},
            {pg_data['shelf_life_days']},
            {escape(pg_data['is_frozen'])},
            {escape(pg_data['is_liquid'])},
            ARRAY{pg_data['tags']}::TEXT[],
            {escape(pg_data['status'])},
            NOW(),
            NOW()
        )
        ON CONFLICT (product_code) DO UPDATE SET
            name = EXCLUDED.name,
            category = EXCLUDED.category,
            unit = EXCLUDED.unit,
            spec = EXCLUDED.spec,
            cost_price = EXCLUDED.cost_price,
            supplier = EXCLUDED.supplier,
            shelf_life_days = EXCLUDED.shelf_life_days,
            is_frozen = EXCLUDED.is_frozen,
            is_liquid = EXCLUDED.is_liquid,
            tags = EXCLUDED.tags,
            status = EXCLUDED.status,
            updated_at = NOW()
    """

    return sql


def migrate(
    json_path: str,
    db_url: Optional[str] = None,
    dry_run: bool = False
) -> Dict[str, Any]:
    """
    执行迁移

    Args:
        json_path: JSON文件路径
        db_url: PG连接URL
        dry_run: 是否只预览不执行

    Returns:
        迁移结果统计
    """
    result = {
        "total": 0,
        "success": 0,
        "failed": 0,
        "skipped": 0,
        "errors": [],
        "start_time": datetime.now().isoformat(),
        "end_time": None,
        "dry_run": dry_run,
    }

    # 加载数据
    try:
        data = load_json(json_path)
    except Exception as e:
        result["errors"].append(f"加载数据失败: {e}")
        return result

    products_dict = data.get("products", {})
    result["total"] = len(products_dict)

    if not products_dict:
        result["errors"].append("JSON中没有产品数据")
        return result

    logger.info(f"开始迁移 {result['total']} 个产品...")

    # 如果是dry_run，只打印预览
    if dry_run:
        logger.info("=" * 60)
        logger.info("DRY RUN 模式 - 不执行实际写入")
        logger.info("=" * 60)

        for i, (sku_code, prod_data) in enumerate(products_dict.items(), 1):
            pg_data = transform_product(sku_code, prod_data)
            logger.info(f"\n[{i}/{result['total']}] {pg_data['product_code']}: {pg_data['name']}")
            logger.info(f"  分类: {pg_data['category']} | 单位: {pg_data['unit']} | 价格: ¥{pg_data['cost_price']}")
            logger.info(f"  冻品: {pg_data['is_frozen']} | 液体: {pg_data['is_liquid']}")

        result["success"] = result["total"]
        result["end_time"] = datetime.now().isoformat()
        return result

    # 实际执行迁移
    try:
        from hotpot_platform.cloud.event_hub.middleware.db_init import execute_sql
    except ImportError as e:
        result["errors"].append(f"无法导入db_init模块: {e}")
        return result

    db_url = db_url or os.environ.get("HOTPOT_DATABASE_URL", "")
    if not db_url:
        result["errors"].append("HOTPOT_DATABASE_URL未设置")
        return result

    for sku_code, prod_data in products_dict.items():
        try:
            # 转换数据
            pg_data = transform_product(sku_code, prod_data)

            # 验证必填字段
            if not pg_data["product_code"] or not pg_data["name"]:
                result["skipped"] += 1
                continue

            # 生成并执行SQL
            sql = generate_upsert_sql(pg_data)

            if execute_sql(db_url, sql):
                result["success"] += 1
            else:
                result["failed"] += 1
                result["errors"].append(f"SQL执行失败: {sku_code}")

        except Exception as e:
            result["failed"] += 1
            result["errors"].append(f"处理异常 [{sku_code}]: {e}")

    result["end_time"] = datetime.now().isoformat()

    # 打印摘要
    logger.info("=" * 60)
    logger.info("迁移完成")
    logger.info("=" * 60)
    logger.info(f"总计: {result['total']}")
    logger.info(f"成功: ✅{result['success']}")
    logger.info(f"失败: ❌{result['failed']}")
    logger.info(f"跳过: ⏭️{result['skipped']}")

    if result["errors"]:
        logger.warning(f"\n错误详情 (前10条):")
        for err in result["errors"][:10]:
            logger.warning(f"  - {err}")

    return result


def main():
    """命令行入口"""
    parser = argparse.ArgumentParser(
        description="产品主数据迁移工具: Edge UI JSON → PostgreSQL",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 默认迁移
  python %(prog)s

  # Dry run (预览不执行)
  python %(prog)s --dry-run

  # 指定JSON路径
  python %(prog)s --json /path/to/product_master.json
"""
    )

    parser.add_argument(
        "--json", "-j",
        default="edge/edge-ui/data/product_master.json",
        help="产品主数据JSON路径 (默认: edge/edge-ui/data/product_master.json)"
    )

    parser.add_argument(
        "--db-url", "-d",
        default=None,
        help="PostgreSQL连接URL (默认: 从HOTPOT_DATABASE_URL环境变量读取)"
    )

    parser.add_argument(
        "--dry-run", "-n",
        action="store_true",
        help="Dry run模式，只预览不实际写入"
    )

    args = parser.parse_args()

    # 执行迁移
    result = migrate(
        json_path=args.json,
        db_url=args.db_url,
        dry_run=args.dry_run
    )

    # 输出结果
    print("\n" + "=" * 60)
    print("迁移结果报告")
    print("=" * 60)
    print(f"时间: {result['start_time']} ~ {result.get('end_time', '进行中')}")
    print(f"模式: {'DRY RUN' if result['dry_run'] else '正式执行'}")
    print(f"\n总计: {result['total']}")
    print(f"成功: ✅ {result['success']}")
    print(f"失败: ❌ {result['failed']}")
    print(f"跳过: ⏭️ {result['skipped']}")

    if result["errors"]:
        print(f"\n错误列表:")
        for err in result["errors"]:
            print(f"  ⚠️ {err}")

    # 返回退出码
    sys.exit(0 if result["failed"] == 0 else 1)


if __name__ == "__main__":
    main()
