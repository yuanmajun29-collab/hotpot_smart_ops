#!/usr/bin/env python3
"""
火瞳 Edge UI v1.1 (FastAPI) → Jetson 部署脚本
- 使用 paramiko 进行 SSH/SCP 操作
- 部署目标: 椒江店 Jetson 172.16.1.60
- 部署路径: /opt/hotpot-smart-ops/edge/edge-ui/
"""

import os
import sys
import time
import json
import tarfile
import io
import paramiko
from pathlib import Path

# ── 配置 ──
JETSON_IP = "172.16.1.60"
JETSON_USER = "root"
JETSON_PASS = "123456"
REMOTE_BASE = "/opt/hotpot-smart-ops"
EDGE_DIR = f"{REMOTE_BASE}/edge/edge-ui"
PORT = 9080

# 本地 Edge UI 目录（脚本所在位置）
LOCAL_DIR = Path(__file__).parent.resolve()

# 需要部署的文件/目录（排除旧版和归档）
EXCLUDE_PATTERNS = [
    "_archive/", "server.py", "server_v2.py",
    "__pycache__/", ".pyc", "deploy_to_jetson.sh",
    "deploy_edge_ui.py",  # 不部署自身
]

def should_include(filepath: str) -> bool:
    """检查文件是否应该包含在部署包中"""
    for pattern in EXCLUDE_PATTERNS:
        if pattern in filepath:
            return False
    return True


def create_deploy_package() -> io.BytesIO:
    """创建部署压缩包（内存中）"""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for root, dirs, files in os.walk(LOCAL_DIR):
            # 排除不需要的目录
            dirs[:] = [d for d in dirs if not any(d == p.rstrip("/") for p in EXCLUDE_PATTERNS)]
            
            for fname in files:
                fpath = os.path.join(root, fname)
                relpath = os.path.relpath(fpath, LOCAL_DIR)
                
                if should_include(relpath):
                    tar.add(fpath, arcname=relpath)
                    print(f"  📦 {relpath} ({os.path.getsize(fpath)} bytes)")
    
    buf.seek(0)
    print(f"\n  压缩包大小: {len(buf.getvalue()) // 1024} KB")
    return buf


def ssh_exec(ssh: paramiko.SSHClient, cmd: str, timeout: int = 30) -> tuple:
    """执行远程命令，返回 (exit_code, stdout, stderr)"""
    stdin, stdout, stderr = ssh.exec_command(cmd, timeout=timeout)
    exit_code = stdout.channel.recv_exit_status()
    out = stdout.read().decode("utf-8", errors="replace").strip()
    err = stderr.read().decode("utf-8", errors="replace").strip()
    return exit_code, out, err


def main():
    print("")
    print("╔══════════════════════════════════════════════════╗")
    print("║   🔥 火瞳 Edge UI v1.1 (FastAPI) 部署工具      ║")
    print("╠══════════════════════════════════════════════════╣")
    print(f"║  目标: {JETSON_IP}:{PORT}")
    print(f"║  路径: {EDGE_DIR}")
    print(f"║  本地: {LOCAL_DIR}")
    print("╚══════════════════════════════════════════════════╝")
    print("")

    # ── Step 1: SSH连接 ──
    print("🔗 [1/6] 连接 Jetson...")
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    
    try:
        ssh.connect(JETSON_IP, username=JETSON_USER, password=JETSON_PASS, timeout=10)
        print(f"  ✅ SSH连接成功")
    except Exception as e:
        print(f"  ❌ SSH连接失败: {e}")
        sys.exit(1)

    # 获取远程信息
    code, out, _ = ssh_exec(ssh, "uname -a && python3 --version")
    print(f"  📋 {out.split(chr(10))[0]}")
    print(f"  🐍 {out.split(chr(10))[1] if chr(10) in out else ''}")

    # ── Step 2: 备份旧文件 ──
    print("\n📦 [2/6] 备份远程旧文件...")
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    code, out, _ = ssh_exec(ssh, f"""
        if [ -d '{EDGE_DIR}' ]; then
            mv '{EDGE_DIR}' '{EDGE_DIR}.bak_{timestamp}' && echo 'BACKUP_OK'
        else
            echo 'NO_OLD_FILES'
        fi
    """)
    if "BACKUP_OK" in out:
        print(f"  ✅ 旧文件已备份为 .bak_{timestamp}")
    else:
        print(f"  ℹ️ 无旧文件或首次部署")

    # ── Step 3: 创建部署包并上传 ──
    print("\n📦 [3/6] 创建部署包...")
    pkg = create_deploy_package()

    print("\n🚀 [4/6] 上传到 Jetson...")
    sftp = ssh.open_sftp()
    
    try:
        # 创建远程目录
        try: sftp.mkdir(f"{REMOTE_BASE}/edge")
        except Exception: pass  # 部署操作失败不阻塞
        try: sftp.mkdir(EDGE_DIR)
        except Exception: pass  # 部署操作失败不阻塞
        
        # 上传压缩包
        remote_pkg = "/tmp/hotpot-edge-ui.tar.gz"
        sftp.putfo(pkg, remote_pkg)
        print(f"  ✅ 压缩包已上传 ({len(pkg.getvalue()) // 1024} KB)")
        
        # 远程解压
        print("  📂 解压中...")
        code, out, err = ssh_exec(ssh, f"tar -xzf {remote_pkg} -C {EDGE_DIR} && rm {remote_pkg} && echo 'EXTRACT_OK'")
        if "EXTRACT_OK" in out:
            print("  ✅ 解压完成")
        else:
            print(f"  ❌ 解压失败: {err}")
            sftp.close()
            ssh.close()
            sys.exit(1)
    finally:
        sftp.close()

    # ── Step 4: 安装依赖 ──
    print("\n📦 [5/6] 检查/安装 Python 依赖...")
    code, out, err = ssh_exec(ssh, """
        pip3 install fastapi uvicorn pydantic psutil pyyaml httpx --quiet 2>&1 | tail -3 && echo 'DEPS_OK' || echo 'DEPS_FAIL'
    """, timeout=120)
    if "DEPS_OK" in out or code == 0:
        print("  ✅ Python 依赖已就绪")
    else:
        print(f"  ⚠️ 依赖安装警告: {err[-200:] if len(err) > 200 else err}")

    # 验证关键依赖
    for mod in ["fastapi", "uvicorn", "pydantic", "psutil"]:
        code, out, _ = ssh_exec(ssh, f"python3 -c 'import {mod}; print({mod}.__version__)' 2>/dev/null || echo 'MISSING'")
        status = "✅" if "MISSING" not in out else "❌"
        print(f"  {status} {mod}: {out.strip()}")

    # ── Step 5: 重启服务 ──
    print("\n🔄 [6/6] 启动 Edge UI 服务...")
    
    # 停止旧服务
    ssh_exec(ssh, f"pkill -f 'main.py.*{PORT}' 2>/dev/null; pkill -f 'server.*{PORT}' 2>/dev/null; sleep 1; echo 'STOPPED'")
    print("  ⏹️  旧服务已停止")
    
    # 启动新服务 (FastAPI + uvicorn)
    code, out, err = ssh_exec(ssh, f"""
        cd '{EDGE_DIR}'
        nohup python3 main.py --port {PORT} > /tmp/hotpot-edge-ui.log 2>&1 &
        echo $! > /tmp/hotpot-edge-ui.pid
        sleep 3
        
        if kill -0 $(cat /tmp/hotpot-edge-ui.pid) 2>/dev/null; then
            echo 'START_OK'
        else
            echo 'START_FAIL'
            tail -20 /tmp/hotpot-edge-ui.log
        fi
    """, timeout=15)
    
    if "START_OK" in out:
        pid_out = ssh_exec(ssh, "cat /tmp/hotpot-edge-ui.pid")[1]
        print(f"  ✅ Edge UI v1.1 启动成功! PID={pid_out.strip()}")
    else:
        print(f"  ❌ 启动失败:")
        print(f"     {out}")
        ssh.close()
        sys.exit(1)

    ssh.close()

    # ── 最终报告 ──
    print("")
    print("╔══════════════════════════════════════════════════╗")
    print("║           🎉 部署完成！                        ║")
    print("╠══════════════════════════════════════════════════╣")
    print(f"║                                                ║")
    print(f"║  🔗 Edge UI 地址:                              ║")
    print(f"║     http://{JETSON_IP}:{PORT}/                   ║")
    print(f"║     http://{JETSON_IP}:{PORT}/login.html         ║")
    print(f"║                                                ║")
    print(f"║  📡 API文档:                                    ║")
    print(f"║     http://{JETSON_IP}:{PORT}/api/docs           ║")
    print(f"║                                                ║")
    print(f"║  🔐 认证端点:                                   ║")
    print(f"║     POST /api/v1/auth/setup                     ║")
    print(f"║     POST /api/v1/auth/login                     ║")
    print(f"║                                                ║")
    print(f"║  📝 日志:                                       ║")
    print(f"║     ssh {JETSON_USER}@{JETSON_IP} tail -f /tmp/hotpot-edge-ui.log")
    print(f"║                                                ║")
    print(f"║  📂 部署路径:                                   ║")
    print(f"║     {EDGE_DIR}")
    print("╚══════════════════════════════════════════════════╝")
    print("")

    # 连通性测试提示
    print("💡 提示: 首次访问需要设置PIN码 (访问 /login.html 或调用 /api/v1/auth/setup)")
    print("")


if __name__ == "__main__":
    main()
