"""火瞳 · Agent 配置加载器

从 YAML/JSON 文件加载 Agent 运行时配置，支持:
- 菜品知识库
- 门店阈值
- 服务术语
- 业务规则参数

使用方式:
    from .config_loader import load_agent_config, get_config

    config = load_agent_config()  # 加载完整配置
    dishes = get_config('dish_menu')  # 获取菜品知识库

作者: 火瞳AI团队
日期: 2026-08-05
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import yaml

logger = logging.getLogger(__name__)

# 配置文件路径（相对于本模块）
_DEFAULT_CONFIG_PATH = Path(__file__).parent / "agent_config.yaml"

# 全局配置缓存
_config_cache: Optional[Dict[str, Any]] = None


def load_agent_config(config_path: Optional[Union[str, Path]] = None) -> Dict[str, Any]:
    """加载 Agent 配置文件

    Args:
        config_path: 配置文件路径（默认为 agent_config.yaml）

    Returns:
        配置字典

    Raises:
        FileNotFoundError: 配置文件不存在
        yaml.YAMLError: YAML 解析错误
    """
    global _config_cache

    if config_path is None:
        config_path = _DEFAULT_CONFIG_PATH

    config_path = Path(config_path)

    if not config_path.exists():
        logger.warning("配置文件不存在: %s，使用默认配置", config_path)
        return _get_default_config()

    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)

        _config_cache = config
        logger.info("配置加载成功: %s (%d 项)", config_path, len(config))
        return config

    except yaml.YAMLError as e:
        logger.error("YAML 解析错误: %s", e)
        raise
    except Exception as e:
        logger.error("配置加载失败: %s", e)
        return _get_default_config()


def get_config(key: str, default: Any = None) -> Any:
    """获取配置项（支持点号分隔的嵌套键）

    Args:
        key: 配置键名（如 'stores.store_jiaojiang'）
        default: 默认值（当键不存在时返回）

    Returns:
        配置值
    """
    global _config_cache

    if _config_cache is None:
        load_agent_config()

    keys = key.split('.')
    value = _config_cache

    for k in keys:
        if isinstance(value, dict) and k in value:
            value = value[k]
        else:
            return default

    return value


def reload_config() -> Dict[str, Any]:
    """重新加载配置（清除缓存）

    Returns:
        最新的配置字典
    """
    global _config_cache
    _config_cache = None
    return load_agent_config()


def get_store_config(store_id: str) -> Dict[str, Any]:
    """获取指定门店的配置

    Args:
        store_id: 门店ID（如 'store_jiaojiang'）

    Returns:
        门店配置字典
    """
    stores = get_config('stores', {})
    return stores.get(store_id, {})


def get_dish_menu() -> List[Dict[str, Any]]:
    """获取菜品知识库

    Returns:
        菜品列表
    """
    return get_config('dish_menu', [])


def get_dish_info(sku: str) -> Optional[Dict[str, Any]]:
    """获取指定菜品信息

    Args:
        sku: 菜品SKU

    Returns:
        菜品信息字典（未找到则返回 None）
    """
    dishes = get_dish_menu()
    for dish in dishes:
        if dish.get('sku') == sku:
            return dict(dish)
    return None


def get_service_terminology() -> Dict[str, str]:
    """获取服务术语库

    Returns:
        场景→话术 映射字典
    """
    return get_config('service_terminology', {})


def get_thresholds() -> Dict[str, Any]:
    """获取业务阈值配置

    Returns:
        阈值字典
    """
    return get_config('thresholds', {})


def get_simulation_config() -> Dict[str, Any]:
    """获取模拟模式配置

    Returns:
        模拟配置字典
    """
    return get_config('simulation', {})


def _get_default_config() -> Dict[str, Any]:
    """获取默认配置（当配置文件不存在时使用）"""
    return {
        "stores": {
            "store_jiaojiang": {
                "name": "椒江店",
                "tables_count": 8,
            }
        },
        "dish_menu": [],
        "thresholds": {},
        "simulation": {
            "mode": "demo",
            "seed": 42,
        }
    }


# 模块加载时自动初始化配置
load_agent_config()
