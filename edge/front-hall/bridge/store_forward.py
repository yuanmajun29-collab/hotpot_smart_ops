"""Store-and-forward buffer for IoT readings (LOSS-502).

Disk-backed, bounded, replay-safe queue so MQTT/Hub disconnects never lose sensor
readings (不丢读数). In-order head-of-line replay: on the first delivery failure we
stop and keep the rest, preserving order for the next attempt.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Callable, Dict, List


class StoreAndForwardBuffer:
    def __init__(self, path: Any, max_items: int = 10000) -> None:
        self.path = Path(path)
        self.max_items = max_items
        self._items: List[Dict[str, Any]] = self._load()

    def _load(self) -> List[Dict[str, Any]]:
        if not self.path.exists():
            return []
        items: List[Dict[str, Any]] = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                items.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return items

    def _flush(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        body = "".join(json.dumps(i, ensure_ascii=False) + "\n" for i in self._items)
        tmp.write_text(body, encoding="utf-8")
        os.replace(tmp, self.path)  # atomic, crash-safe

    def __len__(self) -> int:
        return len(self._items)

    def enqueue(self, item: Dict[str, Any]) -> None:
        self._items.append(item)
        if len(self._items) > self.max_items:
            self._items = self._items[-self.max_items:]  # drop oldest
        self._flush()

    def replay(self, sink: Callable[[Dict[str, Any]], bool]) -> int:
        """Deliver buffered items via ``sink`` in order; stop at first failure and
        keep the remainder. Returns the number successfully delivered."""
        delivered = 0
        remaining: List[Dict[str, Any]] = []
        stopped = False
        for item in self._items:
            if stopped:
                remaining.append(item)
                continue
            ok = False
            try:
                ok = bool(sink(item))
            except Exception:
                ok = False
            if ok:
                delivered += 1
            else:
                stopped = True
                remaining.append(item)
        self._items = remaining
        self._flush()
        return delivered
