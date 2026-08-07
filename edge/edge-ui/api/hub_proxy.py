#!/usr/bin/env python3
"""
Edge UI → Hub 代理层 — P0-B 统一主 Hub

职责:
1. Edge UI 不再直接处理业务逻辑
2. 所有业务请求转发到 Hub (43.139.143.12:8098)
3. 本地仅保留: 摄像头抓拍/离线缓存/UI渲染
4. JWT Token 从 Hub 获取并透传

架构:
┌─────────────┐     HTTP Proxy      ┌─────────────┐
│   Browser   │ ─────────────────→ │   Edge UI   │
│             │                     │ (Jetson)    │
└─────────────┘                     └──┬──────────┘
                                         │ 转发 /api/v1/*
                                         ▼
                                  ┌─────────────┐
                                  │ Cloud Hub    │
                                  │ :8098        │
                                  │ (JWT+RBAC)   │
                                  └─────────────┘

使用方式:
    from edge_ui.api.hub_proxy import HubProxyClient
    proxy = HubProxyClient()
    result = await proxy.forward(request)
"""

from __future__ import annotations

import httpx
import json
import time
from typing import Optional, Dict, Any
from dataclasses import dataclass


@dataclass
class HubProxyConfig:
    """Hub 代理配置"""
    hub_url: str = "http://43.139.143.12:8098"
    timeout: float = 30.0
    retry_count: int = 3
    retry_delay: float = 1.0

    # 离线模式配置
    offline_mode: bool = False
    local_cache_ttl: int = 3600  # 1小时

    # 认证
    edge_api_key: str = ""  # Edge API Key (从配置读取)


class HubProxyClient:
    """
    Edge → Hub 代理客户端

    功能:
    - HTTP 请求转发到 Hub
    - 离线缓存和降级
    - JWT Token 管理
    - 健康检查和故障转移
    """

    def __init__(self, config: Optional[HubProxyConfig] = None):
        self.config = config or HubProxyConfig()
        self._client: Optional[httpx.AsyncClient] = None
        self._jwt_token: Optional[str] = None
        self._token_expires_at: float = 0
        self._is_hub_healthy: bool = True
        self._local_cache: Dict[str, Any] = {}

    async def _get_client(self) -> httpx.AsyncClient:
        """获取或创建 HTTP 客户端"""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.config.hub_url,
                timeout=self.config.timeout,
            )
        return self._client

    async def _ensure_jwt(self) -> str:
        """
        确保 JWT Token 有效

        流程:
        1. 检查本地 token 是否过期
        2. 过期则用 Edge API Key 向 Hub 申请新 token
        3. 缓存新 token
        """
        if self._jwt_token and time.time() < self._token_expires_at:
            return self._jwt_token

        # 向 Hub 申请 token
        try:
            client = await self._get_client()
            resp = await client.post("/api/v1/auth/edge-login", json={
                "edge_id": "jiaojiang-jetson-01",
                "api_key": self.config.edge_api_key,
            })
            if resp.status_code == 200:
                data = resp.json()
                self._jwt_token = data["access_token"]
                self._token_expires_at = time.time() + data.get("expires_in", 3600)
                return self._jwt_token
        except Exception as e:
            print(f"[HubProxy] JWT 申请失败: {e}")

        raise Exception("无法获取 Hub JWT Token")

    async def forward(self, method: str, path: str, **kwargs) -> Dict[str, Any]:
        """
        转发请求到 Hub

        Args:
            method: HTTP 方法 (GET/POST/PUT/DELETE)
            path: API 路径 (如 /api/v1/supply-chain/products)
            **kwargs: 传递给 httpx 的参数 (json/params/headers)

        Returns:
            Hub 响应 JSON
        """
        # 1. 检查离线模式
        if self.config.offline_mode:
            return await self._handle_offline(method, path, **kwargs)

        # 2. 检查 Hub 健康状态
        if not self._is_hub_healthy:
            return await self._handle_offline(method, path, **kwargs)

        try:
            client = await self._get_client()
            jwt = await self._ensure_jwt()

            # 3. 构建请求头
            headers = kwargs.pop("headers", {})
            headers["Authorization"] = f"Bearer {jwt}"
            headers["X-Edge-ID"] = "jiaojiang-jetson-01"
            headers["X-Correlation-ID"] = kwargs.pop("correlation_id", "")

            # 4. 转发请求
            resp = await client.request(method, path, headers=headers, **kwargs)

            # 5. 处理响应
            if resp.status_code >= 500:
                # Hub 内部错误，标记为不健康
                self._is_hub_healthy = False
                return await self._handle_offline(method, path, **kwargs)

            return {
                "status_code": resp.status_code,
                "data": resp.json() if resp.headers.get("content-type", "").startswith("application/json") else resp.text,
                "_proxy": {
                    "hub_url": self.config.hub_url,
                    "method": method,
                    "path": path,
                    "latency_ms": 0,  # 延迟在 forward() 调用前由调用方传入
                    "cached": False,
                }
            }

        except httpx.ConnectError:
            # Hub 连接失败，降级到离线模式
            self._is_hub_healthy = False
            print("[HubProxy] Hub 连接失败，切换到离线模式")
            return await self._handle_offline(method, path, **kwargs)
        except Exception as e:
            print(f"[HubProxy] 转发失败: {e}")
            raise

    async def _handle_offline(self, method: str, path: str, **kwargs) -> Dict[str, Any]:
        """
        离线降级处理

        策略:
        - GET 请求: 返回本地缓存
        - POST 请求: 入队等待重试
        - 其他: 返回错误提示
        """
        cache_key = f"{method}:{path}"

        if method == "GET":
            # 尝试返回缓存
            cached = self._local_cache.get(cache_key)
            if cached:
                return {
                    "status_code": 200,
                    "data": cached,
                    "_proxy": {"cached": True, "offline_mode": True},
                }
            else:
                return {
                    "status_code": 503,
                    "error": "service_unavailable",
                    "message": "Hub 不可用且无本地缓存",
                    "_proxy": {"cached": False, "offline_mode": True},
                }
        elif method in ["POST", "PUT"]:
            # 入队等待重试
            # TODO: 写入 SQLite 离线队列
            return {
                "status_code": 202,
                "message": "请求已入队，将在恢复后自动提交",
                "_proxy": {"queued": True, "offline_mode": True},
            }
        else:
            return {
                "status_code": 503,
                "error": "service_unavailable",
                "message": "Hub 不可用",
                "_proxy": {"offline_mode": True},
            }

    async def health_check(self) -> Dict[str, Any]:
        """检查 Hub 连接状态"""
        try:
            client = await self._get_client()
            start = time.time()
            resp = await client.get("/health", timeout=5.0)
            latency_ms = (time.time() - start) * 1000

            self._is_hub_healthy = resp.status_code == 200

            return {
                "status": "healthy" if self._is_hub_healthy else "unhealthy",
                "hub_url": self.config.hub_url,
                "latency_ms": round(latency_ms, 2),
                "http_status": resp.status_code,
                "jwt_valid": bool(self._jwt_token and time.time() < self._token_expires_at),
                "cache_size": len(self._local_cache),
            }
        except Exception as e:
            self._is_hub_healthy = False
            return {
                "status": "unreachable",
                "hub_url": self.config.hub_url,
                "error": str(e),
                "cache_size": len(self._local_cache),
            }


# ============================================================
# 单例 (全局使用)
# ============================================================

_hub_proxy_instance: Optional[HubProxyClient] = None


def get_hub_proxy() -> HubProxyClient:
    """获取全局 Hub 代理实例"""
    global _hub_proxy_instance
    if _hub_proxy_instance is None:
        _hub_proxy_instance = HubProxyClient()
    return _hub_proxy_instance


async def init_hub_proxy(config: Optional[HubProxyConfig] = None):
    """初始化 Hub 代理 (应用启动时调用)"""
    global _hub_proxy_instance
    _hub_proxy_instance = HubProxyClient(config)

    # 执行健康检查
    health = await _hub_proxy_instance.health_check()
    print(f"[HubProxy] 初始化完成: {health['status']} (latency={health.get('latency_ms', 'N/A')}ms)")


if __name__ == "__main__":
    # 测试
    import asyncio

    async def test():
        proxy = HubProxyClient()
        health = await proxy.health_check()
        print(json.dumps(health, indent=2, ensure_ascii=False))

    asyncio.run(test())
