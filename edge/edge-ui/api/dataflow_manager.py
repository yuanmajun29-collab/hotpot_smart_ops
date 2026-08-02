"""
双向数据流管理器 (Bidirectional Data Flow Manager)

负责:
1. Edge → Cloud: 数据上报 (事件/指标/快照/日志)
2. Cloud → Edge: 指令下发 (配置更新/远程控制/命令执行)
3. 通信链路健康检查和自动重连
4. 离线队列和数据持久化

架构:
┌─────────────┐    HTTP POST     ┌─────────────┐
│   Edge UI   │ ──────────────→ │   Cloud Hub │
│  (Jetson)   │ ←────────────── │ (43.139...) │
│             │    Command Pull  │             │
└─────────────┘                  └─────────────┘

数据类型:
- events: 视觉AI检测事件 (废料/SOP违规/异常)
- metrics: 性能指标 (CPU/Memory/Latency)
- snapshots: 关键帧图像 (base64)
- logs: 运行日志 (审计/错误)
- commands: 云端指令 (配置更新/控制命令)
"""

import json
import time
import os
import sqlite3
import threading
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Callable
from dataclasses import dataclass, field
from enum import Enum
import queue
import logging

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("DataFlowManager")


class DataFlowType(Enum):
    """数据流类型"""
    EVENT = "event"
    METRIC = "metric"
    SNAPSHOT = "snapshot"
    LOG = "log"
    COMMAND = "command"
    CONFIG_UPDATE = "config_update"


@dataclass
class DataPacket:
    """数据包"""
    type: DataFlowType
    payload: Dict[str, Any]
    timestamp: str = field(default_factory=lambda: time.strftime('%Y-%m-%dT%H:%M:%S+08:00'))
    store_id: str = "store_jiaojiang"
    device_id: str = "jetson_edge_001"
    retry_count: int = 0
    max_retries: int = 3


@dataclass
class Command:
    """云端指令"""
    command_id: str
    command_type: str  # config_update / control / query / restart
    payload: Dict[str, Any]
    created_at: str
    expires_at: Optional[str] = None
    status: str = "pending"  # pending / executing / completed / failed / expired


class BidirectionalDataFlowManager:
    """
    双向数据流管理器

    功能:
    - Edge→Cloud: 异步批量上报 + 离线队列
    - Cloud→Edge: 长轮询指令拉取 + 执行回调
    - 健康检查: 心跳 + 链路质量监控
    - 自动重连: 指数退避重试策略
    """

    def __init__(
        self,
        hub_url: str,
        store_id: str = "store_jiaojiang",
        api_key: str = "",
        queue_db_path: Optional[Path] = None,
        report_interval: float = 30.0,  # 上报间隔(秒)
        command_poll_interval: float = 10.0,  # 指令轮询间隔(秒)
        heartbeat_interval: float = 60.0,  # 心跳间隔(秒)
    ):
        self.hub_url = hub_url.rstrip("/")
        self.store_id = store_id
        self.api_key = api_key or os.environ.get("HOTPOT_API_KEY", "")

        # 队列数据库路径
        self.queue_db_path = queue_db_path or Path(f"demo/data/stores/{store_id}/dataflow_queue.db")
        self.queue_db_path.parent.mkdir(parents=True, exist_ok=True)

        # 内部队列 (内存)
        self._upload_queue: queue.Queue = queue.Queue(maxsize=1000)
        self._command_queue: queue.Queue = queue.Queue(maxsize=100)

        # 线程控制
        self._running = False
        self._upload_thread: Optional[threading.Thread] = None
        self._command_thread: Optional[threading.Thread] = None
        self._heartbeat_thread: Optional[threading.Thread] = None

        # 间隔配置
        self.report_interval = report_interval
        self.command_poll_interval = command_poll_interval
        self.heartbeat_interval = heartbeat_interval

        # 统计信息
        self.stats = {
            "uploaded_total": 0,
            "uploaded_failed": 0,
            "commands_received": 0,
            "commands_executed": 0,
            "last_upload_time": None,
            "last_command_time": None,
            "heartbeat_count": 0,
            "consecutive_failures": 0,
        }

        # 回调函数注册
        self._command_handlers: Dict[str, Callable] = {}

        # 锁
        self._lock = threading.Lock()

        # 初始化数据库
        self._init_db()

    def _init_db(self) -> None:
        """初始化离线队列数据库"""
        with self._lock:
            conn = sqlite3.connect(str(self.queue_db_path))
            try:
                conn.executescript("""
                    CREATE TABLE IF NOT EXISTS upload_queue (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        type TEXT NOT NULL,
                        payload TEXT NOT NULL,
                        store_id TEXT DEFAULT 'store_jiaojiang',
                        created_at TEXT DEFAULT (datetime('now')),
                        retry_count INTEGER DEFAULT 0,
                        max_retries INTEGER DEFAULT 3
                    );

                    CREATE TABLE IF NOT EXISTS command_history (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        command_id TEXT UNIQUE NOT NULL,
                        command_type TEXT NOT NULL,
                        payload TEXT NOT NULL,
                        status TEXT DEFAULT 'pending',
                        result TEXT,
                        executed_at TEXT,
                        created_at TEXT DEFAULT (datetime('now'))
                    );

                    CREATE INDEX IF NOT EXISTS idx_upload_type ON upload_queue(type);
                    CREATE INDEX IF NOT EXISTS idx_command_status ON command_history(status);
                """)
                conn.commit()
            finally:
                conn.close()

        logger.info(f"[DataFlow] 数据库初始化完成: {self.queue_db_path}")

    def _headers(self) -> Dict[str, str]:
        """构建请求头"""
        h = {
            "Content-Type": "application/json",
            "X-Store-Id": self.store_id,
            "X-Device-Id": "jetson_edge_001",
            "X-Client-Type": "edge-ui",
        }
        if self.api_key:
            h["X-Api-Key"] = self.api_key
        return h

    # ═══════════════════════════════════════════════════════════════
    # Edge → Cloud: 数据上报
    # ═══════════════════════════════════════════════════════════════

    def enqueue_upload(self, packet: DataPacket) -> bool:
        """
        入队待上传数据包

        Returns:
            True: 入队成功
            False: 队列已满，入队失败
        """
        try:
            self._upload_queue.put_nowait(packet)
            logger.debug(f"[DataFlow] 数据入队: {packet.type.value}")
            return True
        except queue.Full:
            logger.warning("[DataFlow] 上传队列已满，丢弃数据包")
            # 持久化到数据库
            self._persist_packet(packet)
            return False

    def _persist_packet(self, packet: DataPacket) -> None:
        """持久化数据包到SQLite"""
        with self._lock:
            conn = sqlite3.connect(str(self.queue_db_path))
            try:
                conn.execute(
                    """INSERT INTO upload_queue (type, payload, store_id, retry_count, max_retries)
                       VALUES (?, ?, ?, ?, ?)""",
                    (
                        packet.type.value,
                        json.dumps(packet.payload, ensure_ascii=False),
                        packet.store_id,
                        packet.retry_count,
                        packet.max_retries,
                    ),
                )
                conn.commit()
            finally:
                conn.close()

    def _flush_persisted_queue(self) -> int:
        """刷新持久化队列到云端"""
        sent = 0
        with self._lock:
            conn = sqlite3.connect(str(self.queue_db_path))
            try:
                rows = conn.execute(
                    "SELECT id, type, payload, store_id, retry_count, max_retries FROM upload_queue ORDER BY id"
                ).fetchall()

                for row_id, ptype, payload, store_id, retry_count, max_retries in rows:
                    if retry_count >= max_retries:
                        # 超过最大重试次数，删除
                        conn.execute("DELETE FROM upload_queue WHERE id = ?", (row_id,))
                        conn.commit()
                        continue

                    # 尝试上传
                    packet_data = {
                        "type": ptype,
                        "payload": json.loads(payload),
                        "store_id": store_id,
                    }

                    success = self._do_upload("/dataflow/upload", packet_data)

                    if success:
                        conn.execute("DELETE FROM upload_queue WHERE id = ?", (row_id,))
                        conn.commit()
                        sent += 1
                    else:
                        # 更新重试计数
                        conn.execute(
                            "UPDATE upload_queue SET retry_count = retry_count + 1 WHERE id = ?",
                            (row_id,),
                        )
                        conn.commit()
                        break  # 失败则停止，避免阻塞

            finally:
                conn.close()

        if sent > 0:
            logger.info(f"[DataFlow] 刷新持久化队列: {sent} 条")

        return sent

    def _do_upload(self, path: str, data: Dict) -> bool:
        """执行HTTP POST上传"""
        url = self.hub_url + path
        req = urllib.request.Request(
            url,
            data=json.dumps(data, ensure_ascii=False).encode("utf-8"),
            headers=self._headers(),
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                if resp.status == 200:
                    with self._lock:
                        self.stats["uploaded_total"] += 1
                        self.stats["last_upload_time"] = time.strftime('%Y-%m-%dT%H:%M:%S+08:00')
                        self.stats["consecutive_failures"] = 0
                    return True
                else:
                    logger.warning(f"[DataFlow] 上传返回非200: {resp.status}")
                    return False
        except (urllib.error.URLError, TimeoutError) as ex:
            with self._lock:
                self.stats["uploaded_failed"] += 1
                self.stats["consecutive_failures"] += 1
            logger.warning(f"[DataFlow] 上传失败: {ex}")
            return False

    def _upload_worker(self) -> None:
        """上传工作线程 (持续从队列取数据并上传)"""
        logger.info("[DataFlow] 上传工作线程启动")

        while self._running:
            try:
                # 从内存队列取数据 (带超时)
                try:
                    packet = self._upload_queue.get(timeout=self.report_interval)
                except queue.Empty:
                    # 超时，尝试刷新持久化队列
                    self._flush_persisted_queue()
                    continue

                # 构建上传数据
                upload_data = {
                    "type": packet.type.value,
                    "payload": packet.payload,
                    "timestamp": packet.timestamp,
                    "store_id": packet.store_id,
                    "device_id": packet.device_id,
                }

                # 尝试上传
                success = self._do_upload("/dataflow/upload", upload_data)

                if not success and packet.retry_count < packet.max_retries:
                    # 重试入队
                    packet.retry_count += 1
                    self._persist_packet(packet)

            except Exception as ex:
                logger.error(f"[DataFlow] 上传工作线程异常: {ex}", exc_info=True)

        logger.info("[DataFlow] 上传工作线程停止")

    # ═══════════════════════════════════════════════════════════════
    # Cloud → Edge: 指令接收与执行
    # ═══════════════════════════════════════════════════════════════

    def register_command_handler(self, command_type: str, handler: Callable) -> None:
        """
        注册指令处理器

        Args:
            command_type: 指令类型 (config_update / control / query / restart)
            handler: 处理函数 (payload: dict) -> dict (result)
        """
        self._command_handlers[command_type] = handler
        logger.info(f"[DataFlow] 注册指令处理器: {command_type}")

    def poll_commands(self) -> List[Command]:
        """
        从云端拉取待执行指令 (长轮询模式)

        Returns:
            指令列表
        """
        url = f"{self.hub_url}/dataflow/commands/poll?store_id={urllib.parse.quote(self.store_id)}"
        req = urllib.request.Request(url, headers=self._headers(), method="GET")

        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode())

                commands = []
                for cmd_data in data.get("commands", []):
                    cmd = Command(
                        command_id=cmd_data.get("command_id", ""),
                        command_type=cmd_data.get("command_type", ""),
                        payload=cmd_data.get("payload", {}),
                        created_at=cmd_data.get("created_at", ""),
                        expires_at=cmd_data.get("expires_at"),
                    )
                    commands.append(cmd)
                    with self._lock:
                        self.stats["commands_received"] += 1
                        self.stats["last_command_time"] = time.strftime('%Y-%m-%dT%H:%M:%S+08:00')

                return commands

        except (urllib.error.URLError, TimeoutError) as ex:
            logger.warning(f"[DataFlow] 拉取指令失败: {ex}")
            return []
        except Exception as ex:
            logger.error(f"[DataFlow] 拉取指令异常: {ex}", exc_info=True)
            return []

    def execute_command(self, cmd: Command) -> Dict[str, Any]:
        """
        执行单条指令

        Args:
            cmd: 待执行的指令

        Returns:
            执行结果
        """
        logger.info(f"[DataFlow] 执行指令: {cmd.command_type} ({cmd.command_id})")

        # 查找处理器
        handler = self._command_handlers.get(cmd.command_type)

        if not handler:
            result = {
                "success": False,
                "error": f"未知的指令类型: {cmd.command_type}",
                "command_id": cmd.command_id,
            }
        else:
            try:
                result = handler(cmd.payload)
                result["success"] = True
            except Exception as ex:
                result = {
                    "success": False,
                    "error": str(ex),
                    "command_id": cmd.command_id,
                }

        # 记录到历史
        self._record_command_history(cmd, result)

        # 回报结果到云端
        self._report_command_result(cmd.command_id, result)

        with self._lock:
            self.stats["commands_executed"] += 1

        return result

    def _record_command_history(self, cmd: Command, result: Dict) -> None:
        """记录指令执行历史"""
        with self._lock:
            conn = sqlite3.connect(str(self.queue_db_path))
            try:
                conn.execute(
                    """INSERT INTO command_history (command_id, command_type, payload, status, result, executed_at)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (
                        cmd.command_id,
                        cmd.command_type,
                        json.dumps(cmd.payload, ensure_ascii=False),
                        "completed" if result.get("success") else "failed",
                        json.dumps(result, ensure_ascii=False),
                        time.strftime('%Y-%m-%dT%H:%M:%S+08:00'),
                    ),
                )
                conn.commit()
            finally:
                conn.close()

    def _report_command_result(self, command_id: str, result: Dict) -> bool:
        """回报指令执行结果到云端"""
        report_data = {
            "command_id": command_id,
            "result": result,
            "executed_at": time.strftime('%Y-%m-%dT%H:%M:%S+08:00'),
            "store_id": self.store_id,
        }
        return self._do_upload("/dataflow/command/result", report_data)

    def _command_worker(self) -> None:
        """指令处理工作线程"""
        logger.info("[DataFlow] 指令处理工作线程启动")

        while self._running:
            try:
                # 拉取指令
                commands = self.poll_commands()

                # 执行每条指令
                for cmd in commands:
                    if not self._running:
                        break

                    # 检查是否过期
                    if cmd.expires_at and time.strptime(cmd.expires_at, '%Y-%m-%dT%H:%M:%S+08:00') < time.localtime():
                        logger.info(f"[DataFlow] 指令已过期: {cmd.command_id}")
                        continue

                    # 执行
                    self.execute_command(cmd)

                # 等待下一轮
                time.sleep(self.command_poll_interval)

            except Exception as ex:
                logger.error(f"[DataFlow] 指令处理线程异常: {ex}", exc_info=True)
                time.sleep(5)  # 异常后等待5秒

        logger.info("[DataFlow] 指令处理工作线程停止")

    # ═══════════════════════════════════════════════════════════════
    # 心跳与健康检查
    # ═══════════════════════════════════════════════════════════════

    def _heartbeat_worker(self) -> None:
        """心跳工作线程"""
        logger.info("[DataFlow] 心跳工作线程启动")

        while self._running:
            try:
                heartbeat_data = {
                    "store_id": self.store_id,
                    "device_id": "jetson_edge_001",
                    "timestamp": time.strftime('%Y-%m-%dT%H:%M:%S+08:00'),
                    "status": "online",
                    "version": "v0.4.0-expo-ready",
                    "stats": {
                        **self.stats,
                        "queue_depth": self._upload_queue.qsize(),
                        "db_pending": self._get_db_pending_count(),
                    },
                }

                self._do_upload("/dataflow/heartbeat", heartbeat_data)

                with self._lock:
                    self.stats["heartbeat_count"] += 1

            except Exception as ex:
                logger.error(f"[DataFlow] 心跳异常: {ex}", exc_info=True)

            time.sleep(self.heartbeat_interval)

        logger.info("[DataFlow] 心跳工作线程停止")

    def _get_db_pending_count(self) -> int:
        """获取数据库中待上传数量"""
        with self._lock:
            conn = sqlite3.connect(str(self.queue_db_path))
            try:
                count = conn.execute("SELECT COUNT(*) FROM upload_queue").fetchone()[0]
                return count
            finally:
                conn.close()

    # ═══════════════════════════════════════════════════════════════
    # 生命周期管理
    # ═══════════════════════════════════════════════════════════════

    def start(self) -> None:
        """启动所有工作线程"""
        if self._running:
            logger.warning("[DataFlow] 已经在运行中")
            return

        self._running = True

        # 启动上传线程
        self._upload_thread = threading.Thread(target=self._upload_worker, daemon=True, name="DataFlow-Upload")
        self._upload_thread.start()

        # 启动指令处理线程
        self._command_thread = threading.Thread(target=self._command_worker, daemon=True, name="DataFlow-Command")
        self._command_thread.start()

        # 启动心跳线程
        self._heartbeat_thread = threading.Thread(target=self._heartbeat_worker, daemon=True, name="DataFlow-Heartbeat")
        self._heartbeat_thread.start()

        logger.info("[DataFlow] 双向数据流管理器已启动")

    def stop(self) -> None:
        """停止所有工作线程"""
        self._running = False

        # 等待线程结束
        for t in [self._upload_thread, self._command_thread, self._heartbeat_thread]:
            if t and t.is_alive():
                t.join(timeout=5)

        logger.info("[DataFlow] 双向数据流管理器已停止")

    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        with self._lock:
            return {
                **self.stats,
                "running": self._running,
                "queue_depth": self._upload_queue.qsize(),
                "db_pending": self._get_db_pending_count(),
                "registered_handlers": list(self._command_handlers.keys()),
            }

    # ═══════════════════════════════════════════════════════════════
    # 便捷方法
    # ═══════════════════════════════════════════════════════════════

    def report_event(self, event_type: str, event_data: Dict) -> bool:
        """上报事件 (视觉检测结果等)"""
        packet = DataPacket(
            type=DataFlowType.EVENT,
            payload={
                "event_type": event_type,
                **event_data,
            },
        )
        return self.enqueue_upload(packet)

    def report_metrics(self, metrics: Dict) -> bool:
        """上报性能指标"""
        packet = DataPacket(
            type=DataFlowType.METRIC,
            payload=metrics,
        )
        return self.enqueue_upload(packet)

    def report_snapshot(self, camera_id: str, image_base64: str, metadata: Dict = None) -> bool:
        """上报关键帧快照"""
        packet = DataPacket(
            type=DataFlowType.SNAPSHOT,
            payload={
                "camera_id": camera_id,
                "image_base64": image_base64,
                "metadata": metadata or {},
            },
        )
        return self.enqueue_upload(packet)

    def report_log(self, level: str, message: str, module: str = "") -> bool:
        """上报日志"""
        packet = DataPacket(
            type=DataFlowType.LOG,
            payload={
                "level": level,
                "message": message,
                "module": module,
            },
        )
        return self.enqueue_upload(packet)


# ═══════════════════════════════════════════════════════════════
# 全局实例 (单例)
# ═══════════════════════════════════════════════════════════════

_dataflow_manager: Optional[BidirectionalDataFlowManager] = None


def get_dataflow_manager() -> BidirectionalDataFlowManager:
    """获取全局数据流管理器实例"""
    global _dataflow_manager
    if _dataflow_manager is None:
        # 从配置文件读取hub_url
        hub_url = "http://43.139.143.12:8098"  # 默认值

        # 尝试从配置文件读取
        conf_dir = Path(__file__).parent.parent / "conf"
        hub_conf = conf_dir / "hub_connection.json"
        if hub_conf.exists():
            try:
                cfg = json.loads(hub_conf.read_text())
                hub_url = cfg.get("hub_url", hub_url)
            except:
                pass

        _dataflow_manager = BidirectionalDataFlowManager(
            hub_url=hub_url,
            store_id="store_jiaojiang",
        )

    return _dataflow_manager


def init_dataflow() -> None:
    """初始化并启动数据流管理器"""
    manager = get_dataflow_manager()
    manager.start()


def shutdown_dataflow() -> None:
    """关闭数据流管理器"""
    global _dataflow_manager
    if _dataflow_manager:
        _dataflow_manager.stop()
        _dataflow_manager = None
