#!/usr/bin/env python3
"""
Edge ↔ Hub 数据同步引擎

P0-B Phase 2.4: 建立数据同步机制

功能:
- Edge UI 本地缓存 (JSON) ← → Hub PG (唯一数据源)
- 在线模式: 实时/准实时同步
- 离线模式: 本地队列 + 重连后批量同步
- 冲突检测: Last-Write-Wins + 人工审核选项

架构:
    ┌─────────────┐     HTTP/gRPC      ┌─────────────┐
    │  Edge UI    │ ◄────────────────► │  Cloud Hub   │
    │  (Jetson)   │                    │  (腾讯云)    │
    │             │                    │             │
    │ - JSON缓存  │                    │ - PostgreSQL│
    │ - 离线队列  │                    │ - REST API  │
    │ - 同步状态  │                    │ - 审计日志  │
    └─────────────┘                    └─────────────┘

使用方式:
    from edge.edge_ui.api.data_sync import DataSyncEngine
    engine = DataSyncEngine()
    await engine.start()  # 启动后台同步
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set

try:
    import httpx
except ImportError:  # 由运行环境显式报离线，不能伪造同步成功
    httpx = None  # type: ignore

logger = logging.getLogger(__name__)


# ============================================================
# 同步状态枚举
# ============================================================

class SyncStatus(str, Enum):
    """同步状态"""
    IDLE = "idle"              # 空闲
    SYNCING = "syncing"        # 同步中
    OFFLINE = "offline"        # 离线模式
    CONFLICT = "conflict"      # 有冲突需处理
    ERROR = "error"            # 错误


class ConflictResolution(str, Enum):
    """冲突解决策略"""
    LOCAL_WINS = "local_wins"      # 本地优先（Edge）
    REMOTE_WINS = "remote_wins"    # 远程优先（Hub）
    MANUAL = "manual"              # 人工审核
    NEWEST = "newest"              # 最新时间戳优先


# ============================================================
# 配置
# ============================================================

@dataclass
class DataSyncConfig:
    """数据同步配置"""
    # Hub连接
    hub_url: str = "http://43.139.143.12:8098"
    hub_api_key: str = ""
    timeout: float = 30.0

    # 同步策略
    sync_interval_seconds: int = 60       # 同步间隔（秒）
    batch_size: int = 100                 # 批量大小
    max_retries: int = 3                  # 最大重试次数
    retry_delay_seconds: float = 5.0      # 重试延迟

    # 冲突解决
    default_conflict_resolution: ConflictResolution = ConflictResolution.NEWEST

    # 本地存储
    local_cache_dir: str = "edge/edge-ui/data"
    offline_queue_file: str = "edge/edge-ui/data/.offline_queue.jsonl"

    # 监控
    health_check_interval: int = 30       # 健康检查间隔（秒）
    sync_stats_file: str = "edge/edge-ui/data/.sync_stats.json"


# ============================================================
# 数据记录
# ============================================================

@dataclass
class SyncRecord:
    """单条同步记录"""
    id: str = ""
    entity_type: str = ""           # product_master / purchase_order / etc.
    entity_id: str = ""
    action: str = ""                # create / update / delete
    data: Dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    status: str = "pending"         # pending / synced / failed / conflict
    retries: int = 0
    error_message: Optional[str] = None
    correlation_id: str = ""        # 关联审计ID


@dataclass
class SyncStats:
    """同步统计"""
    total_synced: int = 0
    total_failed: int = 0
    total_conflicts: int = 0
    last_sync_time: Optional[str] = None
    last_error: Optional[str] = None
    uptime_seconds: float = 0
    is_online: bool = True


# ============================================================
# 核心同步引擎
# ============================================================

class DataSyncEngine:
    """
    Edge ↔ Hub 数据同步引擎

    功能:
    1. 定期从Hub拉取最新数据到本地缓存
    2. 将本地变更推送到Hub
    3. 离线时排队，上线后批量同步
    4. 检测并解决数据冲突
    """

    def __init__(self, config: Optional[DataSyncConfig] = None):
        self.config = config or DataSyncConfig()
        self.status = SyncStatus.IDLE
        self.stats = SyncStats()

        # 内部状态
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._offline_queue: List[SyncRecord] = []
        self._sync_lock = asyncio.Lock()

        # 回调函数列表
        self._on_sync_complete: List[Callable] = []
        self._on_conflict: List[Callable] = []
        self._on_error: List[Callable] = []

    def _headers(self) -> Dict[str, str]:
        """仅使用显式配置的设备凭证；空凭证不得伪装成已登录。"""
        return {"X-Api-Key": self.config.hub_api_key} if self.config.hub_api_key else {}

    def _log_warning(self, message: str) -> None:
        logger.warning(message)

    async def start(self):
        """启动后台同步任务"""
        if self._running:
            logger.warning("DataSyncEngine已在运行")
            return

        self._running = True
        logger.info("启动数据同步引擎...")

        # 加载离线队列
        await self._load_offline_queue()

        # 启动后台同步循环
        self._task = asyncio.create_task(self._sync_loop())

        logger.info(f"数据同步引擎已启动 (间隔: {self.config.sync_interval_seconds}s)")

    async def stop(self):
        """停止同步引擎"""
        self._running = False

        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

        # 保存离线队列
        await self._save_offline_queue()

        logger.info("数据同步引擎已停止")

    async def _sync_loop(self):
        """主同步循环"""
        start_time = time.time()

        while self._running:
            try:
                # 更新运行时间
                self.stats.uptime_seconds = time.time() - start_time

                # 执行同步
                await self._perform_sync()

                # 等待下次同步
                await asyncio.sleep(self.config.sync_interval_seconds)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"同步循环异常: {e}", exc_info=True)
                self.stats.last_error = str(e)
                self.status = SyncStatus.ERROR

                # 错误后等待更长时间
                await asyncio.sleep(self.config.retry_delay_seconds)

    async def _perform_sync(self):
        """执行一次完整同步"""
        async with self._sync_lock:
            try:
                self.status = SyncStatus.SYNCING

                # 1. 推送本地变更到Hub
                pushed = await self._push_local_changes()

                # 2. 从Hub拉取最新数据
                pulled = await self._pull_remote_changes()

                # 3. 处理冲突
                conflicts = await self._detect_and_resolve_conflicts()

                # 更新统计
                self.stats.last_sync_time = datetime.now().isoformat()
                self.stats.total_synced += pushed + pulled
                self.stats.total_conflicts += conflicts

                if conflicts > 0:
                    self.status = SyncStatus.CONFLICT
                else:
                    self.status = SyncStatus.IDLE

                # 触发回调
                if pushed > 0 or pulled > 0:
                    await self._trigger_callbacks('on_sync_complete', {
                        'pushed': pushed,
                        'pulled': pulled,
                        'conflicts': conflicts
                    })

            except Exception as e:
                logger.error(f"同步失败: {e}")
                self.status = SyncStatus.ERROR
                self.stats.is_online = False
                self.stats.last_error = str(e)

                # 切换到离线模式
                await self._enter_offline_mode()

    async def _push_local_changes(self) -> int:
        """
        推送本地变更到Hub

        Returns:
            成功推送的记录数
        """
        if not self.stats.is_online:
            logger.debug("离线模式，跳过推送")
            return 0

        pushed_count = 0

        # 从离线队列取记录
        pending_records = [r for r in self._offline_queue if r.status == "pending"]

        for record in pending_records[:self.config.batch_size]:
            try:
                success = await self._send_to_hub(record)

                if success:
                    record.status = "synced"
                    record.timestamp = datetime.now().isoformat()
                    pushed_count += 1
                else:
                    record.retries += 1
                    if record.retries >= self.config.max_retries:
                        record.status = "failed"
                        record.error_message = "超过最大重试次数"

            except Exception as e:
                record.error_message = str(e)
                logger.error(f"推送记录失败 [{record.entity_id}]: {e}")

        return pushed_count

    async def _pull_remote_changes(self) -> int:
        """
        从Hub拉取最新数据到本地缓存

        Returns:
            拉取并更新的记录数
        """
        if not self.stats.is_online:
            return 0

        pulled_count = 0

        # 实际调用 Hub API 获取产品主数据
        try:
            if httpx is None:
                raise RuntimeError("httpx 未安装，无法执行 Hub 同步")
            async with httpx.AsyncClient(timeout=self.config.timeout) as client:
                response = await client.get(
                f"{self.config.hub_url}/api/v1/products",
                headers=self._headers(),
                )
            if response.status_code == 200:
                products = response.json()
                self._update_local_cache("product_master", products)
                pulled_count = len(products)
        except Exception as e:
            self._log_warning(f"产品主数据拉取失败: {e}")

        return pulled_count

    async def _detect_and_resolve_conflicts(self) -> int:
        """
        检测并解决数据冲突

        Returns:
            解决的冲突数
        """
        conflict_count = 0

        # TODO: 实现冲突检测逻辑
        # 1. 对比本地和远程的时间戳
        # 2. 应用冲突解决策略
        # 3. 记录冲突日志

        return conflict_count

    async def _send_to_hub(self, record: SyncRecord) -> bool:
        """
        发送单条记录到Hub

        Args:
            record: 同步记录

        Returns:
            是否成功
        """
        if httpx is None:
            self._log_warning("httpx 未安装，记录保留在离线队列")
            return False
        endpoint = f"{self.config.hub_url.rstrip('/')}/api/v1/{record.entity_type}"
        headers = self._headers()
        if record.correlation_id:
            headers["X-Correlation-ID"] = record.correlation_id
        try:
            async with httpx.AsyncClient(timeout=self.config.timeout) as client:
                response = await client.request(
                    "DELETE" if record.action == "delete" else "POST",
                    endpoint,
                    json=record.data,
                    headers=headers,
                )
            if response.status_code not in (200, 201, 202, 204):
                self._log_warning(f"Hub 同步失败 {record.entity_type}/{record.entity_id}: HTTP {response.status_code}")
                return False
            return True
        except Exception as exc:
            self._log_warning(f"Hub 同步异常 {record.entity_type}/{record.entity_id}: {exc}")
            return False

    async def _enter_offline_mode(self):
        """进入离线模式"""
        self.status = SyncStatus.OFFLINE
        self.stats.is_online = False
        logger.warning("进入离线模式，变更将排队等待重连后同步")

    async def _load_offline_queue(self):
        """加载离线队列"""
        queue_file = Path(self.config.offline_queue_file)

        if queue_file.exists():
            try:
                lines = queue_file.read_text(encoding='utf-8').strip().split('\n')
                for line in lines:
                    if line.strip():
                        record = SyncRecord(**json.loads(line))
                        self._offline_queue.append(record)

                logger.info(f"加载离线队列: {len(self._offline_queue)} 条记录")
            except Exception as e:
                logger.error(f"加载离线队列失败: {e}")

    async def _save_offline_queue(self):
        """保存离线队列"""
        queue_file = Path(self.config.offline_queue_file)
        queue_file.parent.mkdir(parents=True, exist_ok=True)

        pending = [r for r in self._offline_queue if r.status == "pending"]

        with open(queue_file, 'w', encoding='utf-8') as f:
            for record in pending:
                f.write(json.dumps({
                    'id': record.id,
                    'entity_type': record.entity_type,
                    'entity_id': record.entity_id,
                    'action': record.action,
                    'data': record.data,
                    'timestamp': record.timestamp,
                    'status': record.status,
                    'retries': record.retries,
                    'correlation_id': record.correlation_id,
                }) + '\n')

        logger.info(f"保存离线队列: {len(pending)} 条记录")

    def _update_local_cache(self, entity_type: str, data: List[Dict]):
        """更新本地缓存"""
        cache_dir = Path(self.config.local_cache_dir)
        cache_dir.mkdir(parents=True, exist_ok=True)

        cache_file = cache_dir / f"{entity_type}.json"

        with open(cache_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        logger.debug(f"更新本地缓存: {cache_file}")

    async def _trigger_callbacks(self, event: str, data: Dict):
        """触发回调"""
        callbacks = {
            'on_sync_complete': self._on_sync_complete,
            'on_conflict': self._on_conflict,
            'on_error': self._on_error,
        }

        for cb in callbacks.get(event, []):
            try:
                if asyncio.iscoroutinefunction(cb):
                    await cb(data)
                else:
                    cb(data)
            except Exception as e:
                logger.error(f"回调执行失败 ({event}): {e}")

    # ============================================================
    # 公共API
    # ============================================================

    async def queue_change(self, entity_type: str, entity_id: str,
                          action: str, data: Dict, correlation_id: str = "") -> str:
        """
        排队一个本地变更

        Args:
            entity_type: 实体类型
            entity_id: 实体ID
            action: 操作类型 (create/update/delete)
            data: 数据
            correlation_id: 审计关联ID

        Returns:
            记录ID
        """
        import uuid

        record = SyncRecord(
            id=str(uuid.uuid4()),
            entity_type=entity_type,
            entity_id=entity_id,
            action=action,
            data=data,
            correlation_id=correlation_id,
        )

        self._offline_queue.append(record)

        logger.debug(f"排队变更: {entity_type}/{entity_id} ({action})")

        return record.id

    def get_status(self) -> Dict[str, Any]:
        """获取同步状态"""
        return {
            'status': self.status.value,
            'is_online': self.stats.is_online,
            'stats': {
                'total_synced': self.stats.total_synced,
                'total_failed': self.stats.total_failed,
                'total_conflicts': self.stats.total_conflicts,
                'last_sync_time': self.stats.last_sync_time,
                'uptime_seconds': self.stats.uptime_seconds,
            },
            'queue_size': len([r for r in self._offline_queue if r.status == "pending"]),
        }

    def register_callback(self, event: str, callback: Callable):
        """注册回调函数"""
        valid_events = ['on_sync_complete', 'on_conflict', 'on_error']
        if event not in valid_events:
            raise ValueError(f"无效事件类型: {event}, 有效值: {valid_events}")

        if event == 'on_sync_complete':
            self._on_sync_complete.append(callback)
        elif event == 'on_conflict':
            self._on_conflict.append(callback)
        elif event == 'on_error':
            self._on_error.append(callback)


# ============================================================
# 便捷接口
# ============================================================

# 全局实例（单例）
_global_engine: Optional[DataSyncEngine] = None


def get_sync_engine() -> DataSyncEngine:
    """获取全局同步引擎实例"""
    global _global_engine
    if _global_engine is None:
        _global_engine = DataSyncEngine()
    return _global_engine


async def start_sync(config: Optional[DataSyncConfig] = None) -> DataSyncEngine:
    """启动全局同步引擎"""
    global _global_engine
    _global_engine = DataSyncEngine(config)
    await _global_engine.start()
    return _global_engine


async def stop_sync():
    """停止全局同步引擎"""
    global _global_engine
    if _global_engine:
        await _global_engine.stop()
        _global_engine = None


if __name__ == "__main__":
    # 测试入口
    import asyncio

    async def test():
        engine = DataSyncEngine()
        print(f"同步引擎创建完成: {engine.get_status()}")

        # 测试排队变更
        record_id = await engine.queue_change(
            entity_type="product_master",
            entity_id="FP-MW-001",
            action="update",
            data={"name": "精品毛肚", "unit_price": 128.0},
            correlation_id="test-corr-001"
        )
        print(f"变更已排队: {record_id}")
        print(f"当前状态: {engine.get_status()}")

    asyncio.run(test())
