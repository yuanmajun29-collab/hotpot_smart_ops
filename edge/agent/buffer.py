"""推断结果离线缓冲层 — SQLite 本地队列 + 自动重试 + 断点续传。

对应: RB-001, AV-003 — 推理结果无离线缓冲导致断网丢数据。

用法:
    from edge.agent.buffer import InferenceBuffer

    buffer = InferenceBuffer(db_path="/tmp/hotpot_buffer/inference.db",
                             hub_url="http://192.168.2.85:8098",
                             api_key=os.environ.get("HOTPOT_API_KEY", ""))
    await buffer.start()  # 启动后台 flush worker

    # 推理结果入队（不直接 POST Hub）
    await buffer.enqueue("/api/v1/vlm/waste-estimate", pipeline_result)

    # Agent 关闭时
    await buffer.stop()
"""

from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


# ── SQLite schema ────────────────────────────────────────────────

_SCHEMA = """
CREATE TABLE IF NOT EXISTS inference_queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT NOT NULL UNIQUE,
    endpoint TEXT NOT NULL DEFAULT '/api/v1/vlm/waste-estimate',
    payload TEXT NOT NULL,
    created_at TEXT NOT NULL,
    retry_count INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK(status IN ('pending', 'sending', 'failed')),
    store_id TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_queue_status ON inference_queue(status, created_at);
CREATE INDEX IF NOT EXISTS idx_queue_store ON inference_queue(store_id, created_at);
"""


class InferenceBuffer:
    """SQLite-backed offline buffer for inference results.

    Design:
    - enqueue() writes to SQLite and triggers async flush
    - Background flush worker runs every 30s
    - On failure: increment retry_count, keep in 'pending' for next attempt
    - On success: DELETE the row
    - max_items cap: FIFO eviction of oldest rows
    - Crash-safe: SQLite WAL mode
    """

    def __init__(
        self,
        db_path: str = "/tmp/hotpot_buffer/inference.db",
        hub_url: str = "http://127.0.0.1:8098",
        api_key: str = "",
        max_items: int = 10000,
        flush_interval: float = 30.0,
        max_retries: int = 10,
    ) -> None:
        self.db_path = db_path
        self.hub_url = hub_url.rstrip("/")
        self.api_key = api_key
        self.max_items = max_items
        self.flush_interval = flush_interval
        self.max_retries = max_retries

        self._conn: Optional[sqlite3.Connection] = None
        self._flush_task: Optional[asyncio.Task] = None
        self._stopping = False
        self._lock = asyncio.Lock()

        Path(db_path).parent.mkdir(parents=True, exist_ok=True)

    # ── lifecycle ────────────────────────────────────────────────

    async def start(self) -> None:
        """初始化 SQLite 并启动后台 flush worker。"""
        await self._init_db()
        # 恢复之前 "sending" 状态的记录（进程崩溃残留）
        self._conn.execute(
            "UPDATE inference_queue SET status='pending' WHERE status='sending'"
        )
        self._conn.commit()
        self._stopping = False
        self._flush_task = asyncio.create_task(self._flush_loop())
        print(f"[Buffer] 已启动 (db={self.db_path}, hub={self.hub_url})")

    async def stop(self) -> None:
        """优雅停止：flush 剩余队列后关闭。"""
        self._stopping = True
        if self._flush_task:
            self._flush_task.cancel()
            try:
                await self._flush_task
            except asyncio.CancelledError:
                pass
        # 最后一次flush
        await self.flush(max_per_batch=-1)
        if self._conn:
            self._conn.close()
            self._conn = None
        print("[Buffer] 已停止")

    # ── DB ops ───────────────────────────────────────────────────

    async def _init_db(self) -> None:
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def _execute(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        assert self._conn is not None
        return self._conn.execute(sql, params)

    def _enforce_max_items(self) -> None:
        """超出上限时 FIFO 删除最旧记录。"""
        count = self._execute("SELECT COUNT(*) FROM inference_queue").fetchone()[0]
        if count > self.max_items:
            excess = count - self.max_items
            self._execute(
                "DELETE FROM inference_queue WHERE id IN ("
                "  SELECT id FROM inference_queue ORDER BY created_at ASC LIMIT ?"
                ")",
                (excess,),
            )
            self._conn.commit()

    # ── public API ───────────────────────────────────────────────

    async def enqueue(
        self, endpoint: str, payload: Dict[str, Any], store_id: str = ""
    ) -> str:
        """将推断结果入队到本地缓冲。

        Returns:
            生成的 event_id (UUID4 前8字符)。
        """
        event_id = uuid.uuid4().hex[:12]
        now = datetime.now(timezone.utc).isoformat()
        store = store_id or payload.get("store_id", "")

        async with self._lock:
            self._execute(
                "INSERT INTO inference_queue (event_id, endpoint, payload, created_at, store_id) "
                "VALUES (?, ?, ?, ?, ?)",
                (event_id, endpoint, json.dumps(payload, ensure_ascii=False), now, store),
            )
            self._conn.commit()
            self._enforce_max_items()

        return event_id

    async def flush(self, max_per_batch: int = 50) -> int:
        """尝试将缓冲的推断结果发送到 Hub。

        Args:
            max_per_batch: 单次最多发送条数 (-1 表示不限)

        Returns:
            成功发送的数量。
        """
        if not self._conn:
            return 0

        async with self._lock:
            limit_clause = "" if max_per_batch < 0 else f" LIMIT {max_per_batch}"
            rows = self._execute(
                f"SELECT * FROM inference_queue WHERE status='pending' "
                f"AND retry_count < ? ORDER BY created_at ASC{limit_clause}",
                (self.max_retries,),
            ).fetchall()

            if not rows:
                return 0

            # 标记为 sending
            ids = [r["id"] for r in rows]
            placeholders = ",".join("?" for _ in ids)
            self._execute(
                f"UPDATE inference_queue SET status='sending' WHERE id IN ({placeholders})",
                ids,
            )
            self._conn.commit()

        # 释放锁后发送（避免阻塞 enqueue）
        import httpx

        sent = 0
        async with httpx.AsyncClient(timeout=httpx.Timeout(15.0)) as client:
            for row in rows:
                try:
                    payload = json.loads(row["payload"])
                    url = f"{self.hub_url}{row['endpoint']}"
                    headers = {"Content-Type": "application/json"}
                    if self.api_key:
                        headers["X-Api-Key"] = self.api_key

                    resp = await client.post(url, json=payload, headers=headers)
                    if 200 <= resp.status_code < 300:
                        # 成功 → 删除
                        async with self._lock:
                            self._execute(
                                "DELETE FROM inference_queue WHERE id=?", (row["id"],)
                            )
                            self._conn.commit()
                        sent += 1
                    else:
                        # Hub 返回错误 → 标记 failed + 增加重试计数
                        async with self._lock:
                            self._execute(
                                "UPDATE inference_queue SET status='pending', "
                                "retry_count=retry_count+1, last_error=? WHERE id=?",
                                (
                                    f"HTTP {resp.status_code}: {resp.text[:200]}",
                                    row["id"],
                                ),
                            )
                            self._conn.commit()
                except Exception as e:
                    # 网络错误 → 标记 pending 等待下次重试
                    async with self._lock:
                        self._execute(
                            "UPDATE inference_queue SET status='pending', "
                            "retry_count=retry_count+1, last_error=? WHERE id=?",
                            (str(e)[:500], row["id"]),
                        )
                        self._conn.commit()

        # 清理超过最大重试次数的记录
        async with self._lock:
            self._execute(
                "DELETE FROM inference_queue WHERE retry_count >= ?",
                (self.max_retries,),
            )
            self._conn.commit()

        return sent

    async def stats(self) -> Dict[str, Any]:
        """返回缓冲状态。"""
        if not self._conn:
            return {"status": "stopped"}

        total = self._execute("SELECT COUNT(*) FROM inference_queue").fetchone()[0]
        pending = self._execute(
            "SELECT COUNT(*) FROM inference_queue WHERE status='pending'"
        ).fetchone()[0]
        sending = self._execute(
            "SELECT COUNT(*) FROM inference_queue WHERE status='sending'"
        ).fetchone()[0]
        total_failed = self._execute(
            "SELECT COALESCE(SUM(retry_count), 0) FROM inference_queue"
        ).fetchone()[0]

        return {
            "status": "running",
            "total": total,
            "pending": pending,
            "sending": sending,
            "total_failed_attempts": total_failed,
            "db_path": self.db_path,
        }

    async def _flush_loop(self) -> None:
        """后台 flush worker — 每隔 flush_interval 秒尝试发送缓冲数据。"""
        while not self._stopping:
            try:
                await asyncio.sleep(self.flush_interval)
                sent = await self.flush(max_per_batch=50)
                if sent > 0:
                    print(f"[Buffer] flush 完成: 发送 {sent} 条")
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"[Buffer] flush 异常: {e}")
