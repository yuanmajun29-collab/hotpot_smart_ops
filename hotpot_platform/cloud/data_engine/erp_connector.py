"""
火瞳 · 数据引擎 — N06 ERP 双向连接器

适配器模式: 统一接口对接多家 ERP/供应链系统。
  - FileAdapter          : 本地 JSON 文件 (开发/演示)
  - MockAdapter          : 内存模拟 (单元测试)
  - RestApiAdapter       : 通用 REST API
  - HualalaAdapter       : 哗啦啦餐饮 SaaS
  - TflongAdapter        : 天财商龙餐饮 SaaS
  - KingdeeAdapter       : 金蝶云·星辰

核心方法 (统一门面 ErpConnector):
  pull_purchase_orders    — 拉取 ERP 采购订单
  push_order_suggestion   — 推送订货建议到 ERP (建议层, 不下单)
  push_inventory_status   — 同步当前库存到 ERP
  push_loss_report        — 推送损耗报告到 ERP

依赖: data_engine.models.ErpSyncResult
"""

from __future__ import annotations

import hashlib
import json
import time
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from hotpot_platform.cloud.data_engine.models import ErpSyncResult


# ============================================================
# 适配器注册表
# ============================================================

ADAPTER_REGISTRY: Dict[str, type] = {}


def register_adapter(name: str):
    """装饰器: 将适配器类注册到 ADAPTER_REGISTRY。"""
    def decorator(cls):
        ADAPTER_REGISTRY[name] = cls
        cls.adapter_name = name
        return cls
    return decorator


# ============================================================
# 抽象适配器基类
# ============================================================

class ErpAdapter(ABC):
    """ERP 适配器抽象基类。"""

    adapter_name: str = "base"

    @abstractmethod
    def pull_purchase_orders(self, store_id: str) -> List[Dict[str, Any]]:
        """从 ERP 拉取采购订单列表。"""
        ...

    @abstractmethod
    def push_order_suggestion(self, store_id: str, suggestion: Dict[str, Any]) -> Dict[str, Any]:
        """将订货建议写入 ERP (建议层，不生成实际 PO)。"""
        ...

    @abstractmethod
    def push_inventory_status(self, store_id: str, inventory: List[Dict[str, Any]]) -> Dict[str, Any]:
        """将库存状态同步到 ERP。"""
        ...

    def push_loss_report(self, store_id: str, date: str, report: Dict[str, Any]) -> Dict[str, Any]:
        """推送损耗报告到 ERP (可选，默认 no-op)。"""
        return {"status": "ok", "adapter": self.adapter_name, "note": "not implemented"}

    def health_check(self) -> Dict[str, Any]:
        """适配器健康检查。"""
        return {"adapter": self.adapter_name, "status": "ok"}


# ============================================================
# FileAdapter — 本地 JSON 文件
# ============================================================

@register_adapter("file")
class FileAdapter(ErpAdapter):
    """从本地 JSON 文件读取/写入 ERP 数据 (开发/演示用)。"""

    def __init__(self, data_dir: Optional[str] = None) -> None:
        self._data_dir = Path(data_dir) if data_dir else Path(__file__).resolve().parents[3] / "demo" / "data"
        self._data_dir.mkdir(parents=True, exist_ok=True)

    def pull_purchase_orders(self, store_id: str) -> List[Dict[str, Any]]:
        po_file = self._data_dir / "erp_po_orders.json"
        if not po_file.exists():
            return []
        try:
            orders = json.loads(po_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return []
        if not isinstance(orders, list):
            orders = orders.get("orders", orders.get("items", []))
        return [o for o in orders if o.get("store_id", store_id) == store_id]

    def push_order_suggestion(self, store_id: str, suggestion: Dict[str, Any]) -> Dict[str, Any]:
        wb_dir = self._data_dir / "erp_writeback"
        wb_dir.mkdir(parents=True, exist_ok=True)
        synced_at = datetime.now(timezone.utc).isoformat()
        out = wb_dir / f"order_suggestion_{store_id}_{synced_at[:10]}.json"
        payload = {"store_id": store_id, "synced_at": synced_at, "suggestion": suggestion}
        out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return {"records_pushed": 1, "status": "ok"}

    def push_inventory_status(self, store_id: str, inventory: List[Dict[str, Any]]) -> Dict[str, Any]:
        wb_dir = self._data_dir / "erp_writeback"
        wb_dir.mkdir(parents=True, exist_ok=True)
        synced_at = datetime.now(timezone.utc).isoformat()
        out = wb_dir / f"inventory_{store_id}_{synced_at[:10]}.json"
        payload = {"store_id": store_id, "synced_at": synced_at, "items": inventory}
        out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return {"records_pushed": len(inventory), "status": "ok"}

    def push_loss_report(self, store_id: str, date: str, report: Dict[str, Any]) -> Dict[str, Any]:
        wb_dir = self._data_dir / "erp_writeback"
        wb_dir.mkdir(parents=True, exist_ok=True)
        out = wb_dir / f"loss_{store_id}_{date}.json"
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        return {"status": "ok"}


# ============================================================
# MockAdapter — 内存模拟
# ============================================================

@register_adapter("mock")
class MockAdapter(ErpAdapter):
    """内存模拟适配器 — 单元测试用。"""

    def __init__(self) -> None:
        self._orders: Dict[str, List[Dict[str, Any]]] = {}
        self._suggestions: List[Dict[str, Any]] = []
        self._inventory_syncs: List[Dict[str, Any]] = []

    def seed_orders(self, store_id: str, orders: List[Dict[str, Any]]) -> None:
        """预填充模拟订单数据。"""
        self._orders[store_id] = orders

    def pull_purchase_orders(self, store_id: str) -> List[Dict[str, Any]]:
        return self._orders.get(store_id, [])

    def push_order_suggestion(self, store_id: str, suggestion: Dict[str, Any]) -> Dict[str, Any]:
        suggestion["store_id"] = store_id
        suggestion["synced_at"] = datetime.now(timezone.utc).isoformat()
        self._suggestions.append(suggestion)
        return {"records_pushed": 1, "status": "ok"}

    def push_inventory_status(self, store_id: str, inventory: List[Dict[str, Any]]) -> Dict[str, Any]:
        record = {"store_id": store_id, "synced_at": datetime.now(timezone.utc).isoformat(), "items": inventory}
        self._inventory_syncs.append(record)
        return {"records_pushed": len(inventory), "status": "ok"}

    def push_loss_report(self, store_id: str, date: str, report: Dict[str, Any]) -> Dict[str, Any]:
        return {"status": "ok"}


# ============================================================
# RestApiAdapter — 通用 REST API
# ============================================================

@register_adapter("rest_api")
class RestApiAdapter(ErpAdapter):
    """通用 REST API 适配器。"""

    def __init__(self, base_url: str, api_key: str = "", timeout: int = 30) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout

    def _headers(self) -> Dict[str, str]:
        h = {"Accept": "application/json", "Content-Type": "application/json"}
        if self.api_key:
            h["Authorization"] = f"Bearer {self.api_key}"
        return h

    def _get(self, endpoint: str, params: Optional[Dict[str, str]] = None) -> List[Dict[str, Any]]:
        import urllib.request, urllib.parse
        url = f"{self.base_url}{endpoint}"
        if params:
            url += "?" + urllib.parse.urlencode(params)
        req = urllib.request.Request(url, headers=self._headers())
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read().decode())
        except Exception as e:
            raise ConnectionError(f"REST GET {url} failed: {e}") from e
        return data if isinstance(data, list) else data.get("data", data.get("items", []))

    def _post(self, endpoint: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        import urllib.request
        url = f"{self.base_url}{endpoint}"
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers=self._headers(), method="POST")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return json.loads(resp.read().decode())
        except Exception as e:
            raise ConnectionError(f"REST POST {url} failed: {e}") from e

    def pull_purchase_orders(self, store_id: str) -> List[Dict[str, Any]]:
        return self._get(f"/stores/{store_id}/purchase-orders")

    def push_order_suggestion(self, store_id: str, suggestion: Dict[str, Any]) -> Dict[str, Any]:
        return self._post(f"/stores/{store_id}/order-suggestions", suggestion)

    def push_inventory_status(self, store_id: str, inventory: List[Dict[str, Any]]) -> Dict[str, Any]:
        return self._post(f"/stores/{store_id}/inventory-sync", {"items": inventory})

    def push_loss_report(self, store_id: str, date: str, report: Dict[str, Any]) -> Dict[str, Any]:
        return self._post(f"/stores/{store_id}/loss-report?date={date}", report)

    def health_check(self) -> Dict[str, Any]:
        try:
            import urllib.request
            req = urllib.request.Request(f"{self.base_url}/health", headers=self._headers())
            with urllib.request.urlopen(req, timeout=5) as resp:
                return {"adapter": self.adapter_name, "status": "ok", "code": resp.status}
        except Exception as e:
            return {"adapter": self.adapter_name, "status": "error", "error": str(e)}


# ============================================================
# HualalaAdapter — 哗啦啦餐饮 SaaS
# ============================================================

@register_adapter("hualala")
class HualalaAdapter(RestApiAdapter):
    """哗啦啦餐饮 SaaS — 火锅连锁常用，支持采购/库存/成本模块。

    使用哗啦啦开放平台 API v2。
    """

    adapter_name = "hualala"

    def __init__(
        self,
        base_url: str = "https://openapi.hualala.com",
        app_id: str = "",
        app_secret: str = "",
        group_id: str = "",
        timeout: int = 30,
    ) -> None:
        super().__init__(base_url=base_url, api_key="", timeout=timeout)
        self.app_id = app_id
        self.app_secret = app_secret
        self.group_id = group_id

    def _sign(self, params: Dict[str, Any]) -> str:
        """哗啦啦 v2 签名: md5(app_id + sorted_params + app_secret)。"""
        sorted_items = sorted(params.items(), key=lambda x: x[0])
        raw = self.app_id + "&".join(f"{k}={v}" for k, v in sorted_items) + self.app_secret
        return hashlib.md5(raw.encode("utf-8")).hexdigest()

    def _headers(self) -> Dict[str, str]:
        return {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "X-App-Id": self.app_id,
            "X-Group-Id": self.group_id,
        }

    def _get(self, endpoint: str, params: Optional[Dict[str, str]] = None) -> List[Dict[str, Any]]:
        params = params or {}
        params["sign"] = self._sign(params)
        return super()._get(endpoint, params)

    def _post(self, endpoint: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        payload["sign"] = self._sign(payload)
        return super()._post(endpoint, payload)

    def pull_purchase_orders(self, store_id: str) -> List[Dict[str, Any]]:
        params = {"shopId": store_id, "groupId": self.group_id}
        return self._get("/v2/purchase/orders", params)

    def push_order_suggestion(self, store_id: str, suggestion: Dict[str, Any]) -> Dict[str, Any]:
        payload = {"shopId": store_id, "groupId": self.group_id, **suggestion}
        return self._post("/v2/purchase/suggestions", payload)

    def push_inventory_status(self, store_id: str, inventory: List[Dict[str, Any]]) -> Dict[str, Any]:
        payload = {"shopId": store_id, "groupId": self.group_id, "items": inventory}
        return self._post("/v2/inventory/sync", payload)


# ============================================================
# TflongAdapter — 天财商龙餐饮 SaaS
# ============================================================

@register_adapter("tflong")
class TflongAdapter(RestApiAdapter):
    """天财商龙餐饮 SaaS — 覆盖正餐/火锅，提供采购/库存 API。"""

    adapter_name = "tflong"

    def __init__(
        self,
        base_url: str = "https://openapi.tflong.com",
        access_token: str = "",
        org_code: str = "",
        timeout: int = 30,
    ) -> None:
        super().__init__(base_url=base_url, api_key=access_token, timeout=timeout)
        self.org_code = org_code

    def _headers(self) -> Dict[str, str]:
        return {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "accessToken": self.api_key,
            "orgCode": self.org_code,
        }

    def pull_purchase_orders(self, store_id: str) -> List[Dict[str, Any]]:
        return self._get("/api/purchase/list", {"storeCode": store_id})

    def push_order_suggestion(self, store_id: str, suggestion: Dict[str, Any]) -> Dict[str, Any]:
        return self._post("/api/purchase/suggestion/push", {"storeCode": store_id, **suggestion})

    def push_inventory_status(self, store_id: str, inventory: List[Dict[str, Any]]) -> Dict[str, Any]:
        return self._post("/api/stock/sync", {"storeCode": store_id, "items": inventory})


# ============================================================
# KingdeeAdapter — 金蝶云·星辰
# ============================================================

@register_adapter("kingdee")
class KingdeeAdapter(RestApiAdapter):
    """金蝶云·星辰 — 面向中小连锁，采购/销售/库存管理。

    使用金蝶云·星辰 OpenAPI，需要 client_id + client_secret 获取 access_token。
    """

    adapter_name = "kingdee"

    def __init__(
        self,
        base_url: str = "https://api.kingdee.com",
        client_id: str = "",
        client_secret: str = "",
        account_id: str = "",
        timeout: int = 30,
    ) -> None:
        super().__init__(base_url=base_url, api_key="", timeout=timeout)
        self.client_id = client_id
        self.client_secret = client_secret
        self.account_id = account_id
        self._access_token: Optional[str] = None
        self._token_expires_at: float = 0

    def _ensure_token(self) -> None:
        """获取/刷新金蝶 access_token。"""
        if self._access_token and time.time() < self._token_expires_at - 60:
            return
        import urllib.request
        url = f"{self.base_url}/jdyconnector/app_management/auth"
        payload = json.dumps({
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "account_id": self.account_id,
            "grant_type": "client_credentials",
        }).encode("utf-8")
        req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read().decode())
            self._access_token = data.get("access_token", "")
            expires_in = data.get("expires_in", 3600)
            self._token_expires_at = time.time() + int(expires_in)
        except Exception as e:
            raise ConnectionError(f"金蝶 token 获取失败: {e}") from e

    def _headers(self) -> Dict[str, str]:
        self._ensure_token()
        return {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self._access_token}",
            "X-Account-Id": self.account_id,
        }

    def pull_purchase_orders(self, store_id: str) -> List[Dict[str, Any]]:
        return self._get("/jdy/v2/scm/purchase_order/list", {"store_id": store_id})

    def push_order_suggestion(self, store_id: str, suggestion: Dict[str, Any]) -> Dict[str, Any]:
        return self._post("/jdy/v2/scm/purchase_suggestion/save", {"store_id": store_id, **suggestion})

    def push_inventory_status(self, store_id: str, inventory: List[Dict[str, Any]]) -> Dict[str, Any]:
        return self._post("/jdy/v2/scm/inventory/sync", {"store_id": store_id, "items": inventory})


# ============================================================
# ErpConnector — 统一门面
# ============================================================

class ErpConnector:
    """N06: ERP 双向连接器 — 适配器模式门面。

    按 adapter_type 自动选择适配器实现，对外暴露统一接口。

    Usage:
        connector = ErpConnector("hualala", app_id=..., app_secret=..., group_id=...)
        orders = connector.pull_purchase_orders("store_001")
        connector.push_order_suggestion("store_001", {"sku": "毛肚", "suggested_qty": 50})
        connector.push_inventory_status("store_001", [{"sku": "毛肚", "on_hand_qty": 30}])
    """

    def __init__(self, adapter_type: str = "file", **adapter_kwargs: Any) -> None:
        """
        Args:
            adapter_type: 适配器类型 (file / mock / rest_api / hualala / tflong / kingdee)
            **adapter_kwargs: 传递给适配器构造函数的参数
        """
        adapter_cls = ADAPTER_REGISTRY.get(adapter_type)
        if adapter_cls is None:
            raise ValueError(
                f"未知 ERP 适配器: {adapter_type}。可用: {list(ADAPTER_REGISTRY.keys())}"
            )
        self._adapter: ErpAdapter = adapter_cls(**adapter_kwargs)
        self.adapter_type = adapter_type

    # ------------------------------------------------------------------
    # pull_purchase_orders
    # ------------------------------------------------------------------

    def pull_purchase_orders(self, store_id: str) -> ErpSyncResult:
        """从 ERP 拉取采购订单。

        Returns:
            ErpSyncResult 同步结果 (records_pulled 包含订单数)
        """
        errors: List[str] = []
        orders_count = 0
        status = "ok"
        try:
            orders = self._adapter.pull_purchase_orders(store_id)
            orders_count = len(orders)
        except Exception as e:
            errors.append(str(e))
            status = "failed"

        return ErpSyncResult(
            store_id=store_id,
            synced_at=datetime.now(timezone.utc),
            records_pulled=orders_count,
            records_pushed=0,
            errors=errors,
            status=status,
        )

    # ------------------------------------------------------------------
    # push_order_suggestion
    # ------------------------------------------------------------------

    def push_order_suggestion(self, store_id: str, suggestion: Dict[str, Any]) -> ErpSyncResult:
        """将订货建议推送到 ERP (建议层，不生成实际采购单)。

        Args:
            store_id: 门店 ID
            suggestion: 订货建议 dict (sku, suggested_qty, reason 等)

        Returns:
            ErpSyncResult
        """
        errors: List[str] = []
        status = "ok"
        pushed = 0
        try:
            result = self._adapter.push_order_suggestion(store_id, suggestion)
            pushed = result.get("records_pushed", 1)
        except Exception as e:
            errors.append(str(e))
            status = "failed"

        return ErpSyncResult(
            store_id=store_id,
            synced_at=datetime.now(timezone.utc),
            records_pulled=0,
            records_pushed=pushed,
            errors=errors,
            status=status,
        )

    # ------------------------------------------------------------------
    # push_inventory_status
    # ------------------------------------------------------------------

    def push_inventory_status(self, store_id: str, inventory: List[Dict[str, Any]]) -> ErpSyncResult:
        """同步当前库存到 ERP。

        Args:
            store_id: 门店 ID
            inventory: 库存列表 [{sku, on_hand_qty, unit, ...}]

        Returns:
            ErpSyncResult
        """
        errors: List[str] = []
        status = "ok"
        pushed = 0
        try:
            result = self._adapter.push_inventory_status(store_id, inventory)
            pushed = result.get("records_pushed", len(inventory))
        except Exception as e:
            errors.append(str(e))
            status = "failed"

        return ErpSyncResult(
            store_id=store_id,
            synced_at=datetime.now(timezone.utc),
            records_pulled=0,
            records_pushed=pushed,
            errors=errors,
            status=status,
        )

    # ------------------------------------------------------------------
    # push_loss_report
    # ------------------------------------------------------------------

    def push_loss_report(self, store_id: str, date: str, report: Dict[str, Any]) -> Dict[str, Any]:
        """推送损耗报告到 ERP。"""
        try:
            return self._adapter.push_loss_report(store_id, date, report)
        except Exception as e:
            return {"status": "error", "error": str(e)}

    # ------------------------------------------------------------------
    # health_check
    # ------------------------------------------------------------------

    def health_check(self) -> Dict[str, Any]:
        """适配器健康检查。"""
        return self._adapter.health_check()

    # ------------------------------------------------------------------
    # 暴露底层适配器
    # ------------------------------------------------------------------

    @property
    def adapter(self) -> ErpAdapter:
        """暴露底层适配器供高级场景使用。"""
        return self._adapter
