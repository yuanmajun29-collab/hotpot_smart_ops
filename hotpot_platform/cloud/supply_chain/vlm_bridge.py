"""VLM Bridge Client — 对接 Jetson VLM 推理，为收货质检提供真实视觉分析能力。

设计目的：
    - 替代 manager.py QualityManager.inspect_batch() 中的 Mock 模拟
    - 支持两种模式：实时 VLM 调用 / Mock 兜底
    - 与 scripts/jetson_vlm_bridge.py 的 Hub 接口保持一致

Usage:
    bridge = VlmBridgeClient()
    result = await bridge.inspect_image("/tmp/receiving-snapshot.jpg", zone="收货区")
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import urllib.request
import urllib.error
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

# 延迟导入避免循环依赖
try:
    from common.env import require_not_production, get_store_id, get_hub_url, get_default_api_key
    _ENV_AVAILABLE = True
except ImportError:
    _ENV_AVAILABLE = False


# ── Data models ──────────────────────────────────────────────────────────────

@dataclass
class QualityItem:
    """单项质检结果"""
    sku: str
    grade: str  # A / B / C / D
    confidence: float
    reason: str
    suggested_action: str


@dataclass
class QualityInspectionResult:
    """收货质检结果"""
    batch_id: str
    store_id: str
    zone: str
    items: list[QualityItem] = field(default_factory=list)
    overall_grade: str = "C"
    pass_check: bool = False
    model: str = "ostrakon-vl-8b-iq4xs"
    source: str = "vlm-bridge"
    source_status: str = "real"
    ts: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    raw_response: Optional[dict] = None
    error: Optional[str] = None
    mock_fallback: bool = False


# ── VLM Bridge Client ────────────────────────────────────────────────────────

class VlmBridgeClient:
    """对接 Jetson VLM Bridge 的客户端。

    实时模式下调用 VLM API 获取视觉品质分析；
    Mock 模式下使用概率算法模拟，用于 VLM 不可用时的兜底。
    """

    def __init__(
        self,
        hub_url: str = "",
        api_key: str = "",
        store_id: str = "",
        timeout: int = 15,
        use_mock: bool = False,
    ) -> None:
        # ── 生产环境防护：Mock 模式不允许在 production 环境下运行 ──
        if use_mock and _ENV_AVAILABLE:
            require_not_production("VLM Bridge 不允许在生产环境使用 Mock 模式(use_mock=True)")

        self.hub_url = (hub_url or os.environ.get("HOTPOT_HUB_URL", "") or
                        (_ENV_AVAILABLE and get_hub_url() or "http://127.0.0.1:8098")).rstrip("/")
        self.api_key = (api_key or os.environ.get("HOTPOT_API_KEY", "") or
                        (_ENV_AVAILABLE and get_default_api_key() or "edge_yuhuan_dev_key"))
        self.store_id = (store_id or
                         os.environ.get("HOTPOT_STORE_ID", "") or
                         (_ENV_AVAILABLE and get_store_id() or "store_yuhuan"))
        self.timeout = timeout
        self._use_mock = use_mock

    # ── Public API ────────────────────────────────────────────────────────

    async def inspect_image(
        self,
        image_path: str,
        *,
        zone: str = "收货区",
        batch_id: str = "",
        sku_hint: Optional[list[str]] = None,
    ) -> QualityInspectionResult:
        """对收货图片执行 VLM 品质检测。

        Args:
            image_path: 图片路径
            zone: 分析区域（收货区/备餐废弃区/后厨出餐区）
            batch_id: 批次号
            sku_hint: 预期的 SKU 列表（用于模型提示）
        """
        result = QualityInspectionResult(
            batch_id=batch_id or f"batch_{datetime.now().strftime('%Y%m%d%H%M%S')}",
            store_id=self.store_id,
            zone=zone,
        )

        if self._use_mock:
            return self._mock_inspect(result)

        try:
            raw = await self._call_vlm(image_path, zone, sku_hint)
            result.raw_response = raw
            items = self._parse_quality_items(raw)
            result.items = items
        except Exception as e:
            logger.warning(f"VLM real call failed ({e}), falling back to mock")
            return self._mock_inspect(result)

        result.overall_grade = self._compute_overall_grade(result.items)
        result.pass_check = result.overall_grade in ("A", "B")
        return result

    async def inspect_batch(
        self,
        images: list[str],
        *,
        zone: str = "收货区",
        batch_id: str = "",
    ) -> QualityInspectionResult:
        """对多张收货图片执行批量质检（取最严格等级）。"""
        if not images:
            return QualityInspectionResult(batch_id=batch_id, store_id=self.store_id, zone=zone)

        all_items: list[QualityItem] = []
        worst_grade = "A"

        for img_path in images:
            result = await self.inspect_image(img_path, zone=zone, batch_id=batch_id)
            all_items.extend(result.items)
            grade_order = {"D": 4, "C": 3, "B": 2, "A": 1}
            if grade_order.get(result.overall_grade, 3) > grade_order.get(worst_grade, 1):
                worst_grade = result.overall_grade

        return QualityInspectionResult(
            batch_id=batch_id or f"batch_{datetime.now().strftime('%Y%m%d%H%M%S')}",
            store_id=self.store_id,
            zone=zone,
            items=all_items,
            overall_grade=worst_grade,
            pass_check=worst_grade in ("A", "B"),
        )

    # ── Real VLM call ─────────────────────────────────────────────────────

    async def _call_vlm(
        self,
        image_path: str,
        zone: str,
        sku_hint: Optional[list[str]] = None,
    ) -> dict:
        """异步调用 VLM API 进行推理。"""
        import base64

        url = f"{self.hub_url}/v1/vlm/quality-inspect"

        # Encode image
        with open(image_path, "rb") as f:
            image_b64 = base64.b64encode(f.read()).decode("ascii")

        payload = {
            "store_id": self.store_id,
            "zone": zone,
            "image_base64": image_b64,
            "image_ref": f"file://{image_path}",
            "source": "vlm-bridge-client",
            "model": "ostrakon-vl-8b-iq4xs",
            "ts": datetime.now(timezone.utc).isoformat(),
        }
        if sku_hint:
            payload["sku_hint"] = sku_hint

        # Run in executor to avoid blocking event loop
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._post_sync, url, payload)

    def _post_sync(self, url: str, payload: dict) -> dict:
        """同步 POST 请求，供 run_in_executor 调用。"""
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=body,
            headers={
                "Content-Type": "application/json",
                "X-Api-Key": self.api_key,
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"VLM Hub HTTP {e.code}: {detail[:300]}")
        except urllib.error.URLError as e:
            raise RuntimeError(f"VLM Hub unreachable: {e.reason}")

    # ── Parse & grade ─────────────────────────────────────────────────────

    def _parse_quality_items(self, raw: dict) -> list[QualityItem]:
        """解析 VLM 返回的质检结果。"""
        items = []
        raw_items = raw.get("items", [])
        if not isinstance(raw_items, list):
            raw_items = []

        grade_map = {"优质": "A", "良好": "B", "合格": "C", "不合格": "D"}

        for item in raw_items:
            if not isinstance(item, dict):
                continue
            raw_grade = str(item.get("grade", item.get("quality_grade", "C"))).strip()
            grade = grade_map.get(raw_grade, raw_grade if raw_grade in "ABCD" else "C")

            items.append(QualityItem(
                sku=str(item.get("sku", "未知")).strip(),
                grade=grade,
                confidence=float(item.get("confidence", 0.5)),
                reason=str(item.get("reason", item.get("remark", ""))).strip(),
                suggested_action=str(item.get("suggested_action", "人工复核")).strip(),
            ))
        return items

    def _compute_overall_grade(self, items: list[QualityItem]) -> str:
        """综合全部质检项目计算整体等级（取最差）。"""
        if not items:
            return "C"
        grade_order = {"D": 4, "C": 3, "B": 2, "A": 1}
        worst = "A"
        for item in items:
            if grade_order.get(item.grade, 3) > grade_order.get(worst, 1):
                worst = item.grade
        return worst

    # ── Mock fallback (probabilistic simulation) ──────────────────────────

    def _mock_inspect(self, result: QualityInspectionResult) -> QualityInspectionResult:
        """Mock 模式：基于概率算法模拟品质检测结果。

        替代 manager.py 中现有的 mock 实现，质量更高：
        - 支持多 SKU 检测
        - 支持分项等级和理由
        - 分布：A 30%, B 40%, C 20%, D 10%
        """
        import random

        # Seed for reproducibility within a batch
        random.seed(hash(result.batch_id) % (2**31))

        mock_skus = [
            {"sku": "冻毛肚1000g", "expected_grade": "A"},
            {"sku": "冻鸭肠500g", "expected_grade": "A"},
            {"sku": "冻牛肉卷1000g", "expected_grade": "B"},
            {"sku": "冻虾滑500g", "expected_grade": "A"},
        ]

        grade_pool = ["A"] * 3 + ["B"] * 4 + ["C"] * 2 + ["D"]
        grade_reasons = {
            "A": "色泽鲜亮、真空包装完好、无异味、符合标准",
            "B": "包装轻微破损但内容物完好、品质正常",
            "C": "轻微变色、包装有漏气、建议优先使用",
            "D": "明显变质、异味明显、包装破损严重、建议退回",
        }
        grade_actions = {
            "A": "正常入库",
            "B": "优先使用，关注品质变化",
            "C": "降级验收或部分退回",
            "D": "全额退回供应商",
        }

        items = []
        for mock_sku in mock_skus:
            grade = random.choice(grade_pool)
            items.append(QualityItem(
                sku=mock_sku["sku"],
                grade=grade,
                confidence=round(random.uniform(0.65, 0.98), 2),
                reason=grade_reasons.get(grade, "品质待确认"),
                suggested_action=grade_actions.get(grade, "人工复核"),
            ))

        result.items = items
        result.overall_grade = self._compute_overall_grade(items)
        result.pass_check = result.overall_grade in ("A", "B")
        result.source_status = "mock"
        result.mock_fallback = True
        return result

    def mock_inspect_sync(self, batch_id: str, store_id: str = "", zone: str = "收货区") -> QualityInspectionResult:
        """同步版本的 Mock 质检（供 QualityManager 兜底调用）。"""
        result = QualityInspectionResult(
            batch_id=batch_id,
            store_id=store_id or self.store_id,
            zone=zone,
        )
        return self._mock_inspect(result)


# ── Singleton ────────────────────────────────────────────────────────────────

_vlm_bridge: Optional[VlmBridgeClient] = None


def get_vlm_bridge(*, use_mock: bool = False) -> VlmBridgeClient:
    """获取 VLM Bridge 单例。

    Args:
        use_mock: True 时使用 Mock 模式（VLM 不可用时设置）
    """
    global _vlm_bridge
    if _vlm_bridge is None:
        _vlm_bridge = VlmBridgeClient(use_mock=use_mock)
    if use_mock:
        _vlm_bridge._use_mock = True
    return _vlm_bridge
