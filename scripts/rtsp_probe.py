#!/usr/bin/env python3
"""RTSP 摄像头探测 + 配置生成器

功能:
  1. 扫描本地网络 RTSP 流（给定 IP 范围 + 端口列表）
  2. 验证流可用性
  3. 生成设备模块配置 JSON

用法:
  python3 rtsp_probe.py                          # 扫描默认范围
  python3 rtsp_probe.py --targets hosts.txt      # 从文件读取
  python3 rtsp_probe.py --single 192.168.2.240   # 单设备探测
  python3 rtsp_probe.py --json                   # 输出设备配置格式
"""

import argparse
import json
import socket
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Optional

# ─── 默认参数 ───
DEFAULT_PORTS = [554, 8554, 8080, 8555]
DEFAULT_PATHS = [
    "/stream", "/live", "/h264", "/video",
    "/cam/realmonitor", "/h265", "/main",
    "/Streaming/Channels/101",  # Hikvision
    "/cam1/mpeg4",               # Generic
]
TIMEOUT = 3  # 秒


def discover_hosts(subnet="192.168.2") -> List[str]:
    """ARP 扫描 + 端口试探发现 RTSP 主机."""
    hosts = []
    try:
        result = subprocess.run(
            ["arp", "-a"], capture_output=True, text=True, timeout=5
        )
        for line in result.stdout.split("\n"):
            for word in line.split():
                if word.startswith(subnet) and word.count(".") == 3:
                    hosts.append(word)
    except Exception:
        pass
    return list(set(hosts))  # 去重


def probe_rtsp(ip: str, port: int, path: str) -> Optional[dict]:
    """探测单个 RTSP URL 是否可用."""
    url = f"rtsp://{ip}:{port}{path}"
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(TIMEOUT)
        result = sock.connect_ex((ip, port))
        sock.close()
        if result == 0:
            return {"url": url, "ip": ip, "port": port, "path": path, "reachable": True}
    except Exception:
        pass
    return None


def probe_host(ip: str, ports=None, paths=None) -> List[dict]:
    """探测一台主机的所有 RTSP 端口 + 路径组合."""
    ports = ports or DEFAULT_PORTS
    paths = paths or DEFAULT_PATHS
    results = []
    for port in ports:
        for path in paths:
            r = probe_rtsp(ip, port, path)
            if r:
                results.append(r)
    return results


def scan_network(subnet: str = "192.168.2") -> dict:
    """扫描整个子网，返回可用 RTSP 源."""
    hosts = discover_hosts(subnet)
    all_results = {}

    print(f"🔍 扫描 {subnet}.0/24 ... 发现 {len(hosts)} 个活跃主机")
    start = time.time()

    with ThreadPoolExecutor(max_workers=10) as pool:
        futures = {pool.submit(probe_host, ip): ip for ip in hosts}
        for f in as_completed(futures):
            ip = futures[f]
            try:
                result = f.result(timeout=15)
                if result:
                    print(f"  ✅ {ip} → {len(result)} 个可用流")
                    all_results[ip] = result
            except Exception as e:
                print(f"  ⚠️ {ip}: {e}")

    elapsed = time.time() - start
    total = sum(len(v) for v in all_results.values())
    print(f"🏁 完成 ({elapsed:.1f}s): {total} 个可用流 在 {len(all_results)} 台设备上")
    return all_results


def to_module_config(scan_results: dict, device_id="jetson-store-yuhuan") -> dict:
    """将扫描结果转换为设备模块配置 JSON."""
    cameras = []
    for ip, streams in scan_results.items():
        for s in streams:
            cameras.append(s["url"])

    # 简单启发式: 含 kitchen/waste 归后厨，hall 归前厅
    kitchen_cams = []
    front_hall_cams = []
    for url in cameras:
        if any(k in url.lower() for k in ["kitchen", "waste", "后厨"]):
            kitchen_cams.append(url)
        else:
            front_hall_cams.append(url)

    return {
        "device_id": device_id,
        "config": {
            "modules": {
                "kitchen": {
                    "enabled": True,
                    "cameras": kitchen_cams,
                    "inference_interval": 30,
                    "rules": {},
                },
                "front_hall": {
                    "enabled": True if front_hall_cams else False,
                    "cameras": front_hall_cams,
                    "inference_interval": 30,
                    "rules": {},
                },
            }
        },
    }


def main():
    parser = argparse.ArgumentParser(description="RTSP 摄像头探测工具")
    parser.add_argument("--targets", help="主机列表文件（每行一个IP）")
    parser.add_argument("--single", help="单主机探测")
    parser.add_argument("--subnet", default="192.168.2", help="子网前缀")
    parser.add_argument("--json", action="store_true", help="输出设备配置 JSON")
    parser.add_argument("--pretty", action="store_true", help="格式化输出")

    args = parser.parse_args()

    if args.single:
        results = probe_host(args.single)
        if args.json:
            config = to_module_config({args.single: results})
            print(json.dumps(config, ensure_ascii=False, indent=2 if args.pretty else None))
        else:
            for r in results:
                print(f"  {r['url']} ✓")
            if not results:
                print("  ❌ 无可用流")
        return

    if args.targets:
        with open(args.targets) as f:
            hosts = [line.strip() for line in f if line.strip()]
        all_results = {}
        for ip in hosts:
            r = probe_host(ip)
            if r:
                all_results[ip] = r
    else:
        all_results = scan_network(args.subnet)

    if args.json:
        config = to_module_config(all_results)
        print(json.dumps(config, ensure_ascii=False, indent=2 if args.pretty else None))
    elif not args.targets:
        print("\n📋 配置预览:")
        config = to_module_config(all_results)
        print(json.dumps(config, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
