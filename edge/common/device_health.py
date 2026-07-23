"""
Jetson 设备健康遥测 — 采集 CPU/内存/GPU/温度/磁盘 指标并上报 Hub。

边缘端模块：部署在 Jetson 设备上，周期性采集硬件指标。
云端消费：Hub 接收遥测数据后存入时序表，供 Dashboard 消费。
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import platform
import time
from dataclasses import dataclass, asdict
from typing import Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class DeviceMetrics:
    """单次采集的设备指标快照。"""
    device_id: str
    timestamp: float
    cpu_percent: float
    memory_percent: float
    memory_used_mb: float
    memory_total_mb: float
    disk_percent: float
    disk_used_gb: float
    disk_total_gb: float
    gpu_temp_c: Optional[float] = None       # Jetson 才有
    cpu_temp_c: Optional[float] = None
    gpu_util_pct: Optional[float] = None
    uptime_seconds: Optional[float] = None


# ---------------------------------------------------------------------------
# Metrics collector — cross-platform (macOS dev + Jetson prod)
# ---------------------------------------------------------------------------

class MetricsCollector:
    """采集当前机器的硬件指标。macOS 上用 psutil，Jetson 上额外读 tegrastats。"""

    def __init__(self, device_id: str = "") -> None:
        self.device_id = device_id or self._hostname()

    @staticmethod
    def _hostname() -> str:
        return platform.node()

    def is_jetson(self) -> bool:
        return os.path.exists("/sys/devices/platform/tegra-fuse")

    async def collect(self) -> DeviceMetrics:
        import psutil  # lazy import
        loop = asyncio.get_running_loop()

        cpu_pct = await loop.run_in_executor(None, psutil.cpu_percent, 1)
        mem = psutil.virtual_memory()
        disk = psutil.disk_usage("/")
        uptime = time.time() - psutil.boot_time()

        metrics = DeviceMetrics(
            device_id=self.device_id,
            timestamp=time.time(),
            cpu_percent=cpu_pct,
            memory_percent=mem.percent,
            memory_used_mb=mem.used / (1024 * 1024),
            memory_total_mb=mem.total / (1024 * 1024),
            disk_percent=disk.percent,
            disk_used_gb=disk.used / (1024 * 1024 * 1024),
            disk_total_gb=disk.total / (1024 * 1024 * 1024),
            uptime_seconds=uptime,
        )

        if self.is_jetson():
            gpu_temp, cpu_temp, gpu_util = await self._read_jetson_thermal()
            metrics.gpu_temp_c = gpu_temp
            metrics.cpu_temp_c = cpu_temp
            metrics.gpu_util_pct = gpu_util

        return metrics

    async def _read_jetson_thermal(self):
        """从 tegrastats / sysfs 读取 Jetson 温度和 GPU 使用率。"""
        gpu_temp = cpu_temp = gpu_util = None

        # 尝试 tegrastats
        try:
            proc = await asyncio.create_subprocess_exec(
                "tegrastats", "--interval", "500", "--count", "1",
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=5)
            raw = stdout.decode(errors="replace").strip()
            # 解析形如: "GR3D_FREQ 30% ... CPU@38.5C GPU@40C"
            for token in raw.split():
                if token.startswith("GPU@") and token.endswith("C"):
                    try:
                        gpu_temp = float(token[4:-1])
                    except ValueError:
                        pass
                if token.startswith("CPU@") and token.endswith("C"):
                    try:
                        cpu_temp = float(token[4:-1])
                    except ValueError:
                        pass
                if token.startswith("GR3D_FREQ"):
                    # 格式: GR3D_FREQ 30%
                    parts = raw.split(token)[1].strip().split()
                    if parts:
                        try:
                            gpu_util = float(parts[0].rstrip("%"))
                        except ValueError:
                            pass
        except Exception:
            pass

        # fallback: sysfs 温度
        for label, path in [("cpu", "/sys/devices/virtual/thermal/thermal_zone0/temp"),
                             ("gpu", "/sys/devices/virtual/thermal/thermal_zone1/temp")]:
            try:
                with open(path) as fh:
                    val = int(fh.read().strip()) / 1000.0
                if label == "cpu" and cpu_temp is None:
                    cpu_temp = val
                elif label == "gpu" and gpu_temp is None:
                    gpu_temp = val
            except Exception:
                pass

        return gpu_temp, cpu_temp, gpu_util


# ---------------------------------------------------------------------------
# Reporter — 向 Hub 上报
# ---------------------------------------------------------------------------

class HealthReporter:
    """周期性采集指标并 POST 到 Hub 的 /api/device-health 端点。"""

    def __init__(
        self,
        hub_url: str = "",
        device_id: str = "",
        interval: int = 60,
        auth_token: str = "",
    ) -> None:
        self.hub_url = hub_url.rstrip("/")
        self.device_id = device_id
        self.interval = interval
        self.auth_token = auth_token
        self.collector = MetricsCollector(device_id=device_id)
        self._stop = False

    async def run(self) -> None:
        """启动周期性采集上报循环。"""
        logger.info(
            "健康上报启动 device=%s hub=%s interval=%ds",
            self.device_id, self.hub_url, self.interval,
        )
        while not self._stop:
            try:
                metrics = await self.collector.collect()
                await self._post_metrics(metrics)
            except Exception:
                logger.exception("健康上报失败")
            await asyncio.sleep(self.interval)

    def stop(self) -> None:
        self._stop = True

    async def _post_metrics(self, metrics: DeviceMetrics) -> None:
        if not self.hub_url:
            logger.debug("未配置 hub_url，跳过上报")
            return
        import aiohttp
        payload = asdict(metrics)
        headers = {"Content-Type": "application/json"}
        if self.auth_token:
            headers["Authorization"] = f"Bearer {self.auth_token}"
        endpoint = f"{self.hub_url}/api/device-health"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    endpoint, json=payload, headers=headers, timeout=aiohttp.ClientTimeout(total=15)
                ) as resp:
                    if resp.status != 200:
                        logger.warning("Hub返回 %d: %s", resp.status, await resp.text())
        except Exception:
            logger.exception("POST %s 失败", endpoint)


# ---------------------------------------------------------------------------
# Standalone entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Jetson 设备健康遥测")
    parser.add_argument("--hub-url", default=os.getenv("HOTPOT_HUB_URL", ""))
    parser.add_argument("--device-id", default=os.getenv("HOTPOT_DEVICE_ID", ""))
    parser.add_argument("--interval", type=int, default=int(os.getenv("HEALTH_INTERVAL", "60")))
    parser.add_argument("--auth-token", default=os.getenv("HOTPOT_AUTH_TOKEN", ""))
    args = parser.parse_args()

    reporter = HealthReporter(
        hub_url=args.hub_url,
        device_id=args.device_id,
        interval=args.interval,
        auth_token=args.auth_token,
    )

    async def main():
        await reporter.run()

    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        reporter.stop()
        logger.info("健康上报已停止")
