#!/usr/bin/env python3
"""
火瞳 · IPC视频取帧引擎
支持 RTSP拉流(OpenCV) + HTTP抓拍(Digest) 双模式自动切换

用法:
    from frame_grabber import FrameGrabber
    fg = FrameGrabber(rtsp_url="rtsp://...", http_url="http://...")
    frame = fg.get_frame()  # 返回 numpy array 或 None
"""

import time
import threading
import queue
import os
import sys
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(name)s] %(message)s')
logger = logging.getLogger("FrameGrabber")

# ── 配置 ──────────────────────────────────────────────
DEFAULT_CONFIG = {
    # 海康NVR配置（椒江店）
    "ipc_ip": "192.168.6.21",
    "ipc_port": 554,
    "username": "admin",
    "password": "hy898989",
    
    # RTSP路径
    "rtsp_channel_main": 101,   # 主码流通道
    "rtsp_channel_sub": 201,    # 子码流通道
    
    # HTTP抓拍路径
    "http_snapshot_path": "/ISAPI/Streaming/channels/101/picture",
    
    # 性能参数
    "buffer_size": 1,           # OpenCV buffer
    "rtsp_timeout_ms": 5000,    # RTSP连接超时
    "http_timeout_s": 8,        # HTTP超时
    "reconnect_interval_s": 3,  # 重连间隔
    "max_retries": 3,           # 最大重试次数
    
    # 模式: "auto" | "rtsp" | "http"
    "mode": "auto",
}


class FrameGrabber:
    """
    IPC视频取帧引擎
    - 优先使用RTSP连续拉流（高帧率、低延迟）
    - RTSP不可用时自动降级到HTTP抓拍
    - 支持多通道切换
    """
    
    def __init__(self, config=None):
        self.cfg = {**DEFAULT_CONFIG, **(config or {})}
        self._mode = None  # "rtsp" | "http" | None
        self._cap = None   # OpenCV VideoCapture
        self._running = False
        self._frame_queue = queue.Queue(maxsize=2)
        self._thread = None
        self._stats = {
            "frames_captured": 0,
            "errors": 0,
            "last_frame_time": 0,
            "avg_latency_ms": 0,
            "mode_switches": 0,
        }
        
        logger.info("FrameGrabber initialized (IPC: %s)" % self.cfg["ipc_ip"])
    
    @property
    def mode(self):
        return self._mode or "none"
    
    @property
    def stats(self):
        return dict(self._stats)
    
    def _build_rtsp_url(self, channel=None):
        """构建RTSP URL"""
        ch = channel or self.cfg["rtsp_channel_main"]
        return "rtsp://{username}:{password}@{ip}:{port}/Streaming/Channels/{ch}".format(
            username=self.cfg["username"],
            password=self.cfg["password"],
            ip=self.cfg["ipc_ip"],
            port=self.cfg["ipc_port"],
            ch=ch,
        )
    
    def _build_http_url(self, channel=None):
        """构建HTTP抓拍URL"""
        ch = channel or self.cfg["rtsp_channel_main"]
        path = "/ISAPI/Streaming/channels/{}/picture".format(ch)
        return "http://{ip}{path}".format(ip=self.cfg["ipc_ip"], path=path)
    
    # ── RTSP模式 ───────────────────────────────────────
    
    def _init_rtsp(self, channel=None):
        """初始化RTSP连接"""
        import cv2
        
        url = self._build_rtsp_url(channel)
        logger.info("Connecting RTSP: %s", url.replace(self.cfg["password"], "***"))
        
        try:
            cap = cv2.VideoCapture(url)
            cap.set(cv2.CAP_PROP_BUFFERSIZE, self.cfg["buffer_size"])
            
            # 测试读取一帧
            t0 = time.time()
            ret, frame = cap.read()
            dt = int((time.time() - t0) * 1000)
            
            if ret and frame is not None:
                h, w = frame.shape[:2]
                logger.info("RTSP connected! %dx%d, first frame %dms", w, h, dt)
                self._cap = cap
                self._mode = "rtsp"
                self._stats["avg_latency_ms"] = dt
                return True
            else:
                logger.warning("RTSP connect OK but no frame (ret=%s)", ret)
                cap.release()
                return False
                
        except Exception as ex:
            logger.error("RTSP init failed: %s", ex)
            return False
    
    def _read_rtsp_frame(self):
        """从RTSP读取一帧"""
        if not self._cap:
            return None
        
        t0 = time.time()
        ret, frame = self._cap.read()
        dt = int((time.time() - t0) * 1000)
        
        if ret and frame is not None:
            # 更新延迟统计（指数平滑）
            alpha = 0.3
            self._stats["avg_latency_ms"] = (
                alpha * dt + (1 - alpha) * self._stats["avg_latency_ms"]
            )
            self._stats["frames_captured"] += 1
            self._stats["last_frame_time"] = time.time()
            return frame
        else:
            self._stats["errors"] += 1
            logger.warning("RTSP read failed (ret=%s)", ret)
            return None
    
    def _close_rtsp(self):
        """关闭RTSP连接"""
        if self._cap:
            try:
                self._cap.release()
            except:
                pass
            self._cap = None
            logger.info("RTSP connection closed")
    
    # ── HTTP抓拍模式 ───────────────────────────────────
    
    def _do_http_snapshot(self, channel=None):
        """HTTP Digest认证抓拍JPEG → 解码为numpy array"""
        try:
            from requests.auth import HTTPDigestAuth
            import requests
            import numpy as np
            from io import BytesIO
            from PIL import Image
            
            url = self._build_http_url(channel)
            
            t0 = time.time()
            r = requests.get(
                url,
                auth=HTTPDigestAuth(self.cfg["username"], self.cfg["password"]),
                timeout=self.cfg["http_timeout_s"],
            )
            dt = int((time.time() - t0) * 1000)
            
            r.raise_for_status()
            data = r.content
            
            if data[:2] != b"\xff\xd8":
                logger.warning("HTTP response not JPEG (%dB)", len(data))
                return None
            
            # JPEG → numpy array (BGR for OpenCV compatibility)
            img = Image.open(BytesIO(data))
            frame = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)
            
            self._stats["avg_latency_ms"] = (
                0.3 * dt + 0.7 * self._stats["avg_latency_ms"]
            )
            self._stats["frames_captured"] += 1
            self._stats["last_frame_time"] = time.time()
            
            return frame
            
        except ImportError:
            # fallback without PIL
            import cv2
            import numpy as np
            
            url = self._build_http_url(channel)
            t0 = time.time()
            r = requests.get(
                url,
                auth=HTTPDigestAuth(self.cfg["username"], self.cfg["password"]),
                timeout=self.cfg["http_timeout_s"],
            )
            dt = int((time.time() - t0) * 1000)
            r.raise_for_status()
            
            arr = np.frombuffer(r.content, dtype=np.uint8)
            frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
            
            if frame is not None:
                self._stats["avg_latency_ms"] = 0.3 * dt + 0.7 * self._stats["avg_latency_ms"]
                self._stats["frames_captured"] += 1
                self._stats["last_frame_time"] = time.time()
            
            return frame
            
        except Exception as ex:
            self._stats["errors"] += 1
            logger.error("HTTP snapshot failed: %s", ex)
            return None
    
    # ── 自动模式切换 ───────────────────────────────────
    
    def _try_init(self):
        """尝试初始化最佳可用模式"""
        target_mode = self.cfg["mode"]
        
        if target_mode == "http":
            self._mode = "http"
            logger.info("Mode: HTTP snapshot (forced)")
            return True
        
        if target_mode in ("rtsp", "auto"):
            # 尝试RTSP
            if self._init_rtsp():
                logger.info("Mode: RTSP streaming")
                return True
            
            if target_mode == "rtsp":
                logger.error("RTSP forced but failed!")
                return False
            
            # auto模式下RTSP失败，降级到HTTP
            logger.info("RTSP unavailable, falling back to HTTP snapshot")
            self._mode = "http"
            self._stats["mode_switches"] += 1
            return True
        
        return False
    
    # ── 公共API ────────────────────────────────────────
    
    def start(self):
        """启动取帧引擎"""
        if self._running:
            logger.warning("Already running")
            return False
        
        if not self._try_init():
            logger.error("Failed to initialize any capture mode")
            return False
        
        self._running = True
        
        # 启动后台取帧线程
        self._thread = threading.Thread(target=self._capture_loop, daemon=True)
        self._thread.start()
        
        logger.info("FrameGrabber started (mode=%s)", self._mode)
        return True
    
    def stop(self):
        """停止取帧引擎"""
        self._running = False
        self._close_rtsp()
        if self._thread:
            self._thread.join(timeout=3)
        logger.info("FrameGrabber stopped")
    
    def _capture_loop(self):
        """后台取帧循环"""
        consecutive_errors = 0
        
        while self._running:
            frame = None
            
            if self._mode == "rtsp":
                frame = self._read_rtsp_frame()
                
                # RTSP连续错误，尝试重连或降级
                if frame is None:
                    consecutive_errors += 1
                    if consecutive_errors >= self.cfg["max_retries"]:
                        logger.warning("RTSP %d consecutive errors, reconnecting...", consecutive_errors)
                        self._close_rtsp()
                        time.sleep(self.cfg["reconnect_interval_s"])
                        if not self._init_rtsp():
                            logger.info("RTSP reconnect failed, switching to HTTP")
                            self._mode = "http"
                            self._stats["mode_switches"] += 1
                            consecutive_errors = 0
                else:
                    consecutive_errors = 0
                    
            elif self._mode == "http":
                frame = self._do_http_snapshot()
                
                if frame is None:
                    consecutive_errors += 1
                    if consecutive_errors >= self.cfg["max_retries"]:
                        logger.warning("HTTP %d consecutive errors, waiting...", consecutive_errors)
                        time.sleep(self.cfg["reconnect_interval_s"])
                        consecutive_errors = 0
                else:
                    consecutive_errors = 0
            
            # 将帧放入队列（非阻塞，丢弃旧帧）
            if frame is not None:
                try:
                    self._frame_queue.put_nowait(frame)
                except queue.Full:
                    try:
                        self._frame_queue.get_nowait()  # 丢弃旧帧
                        self._frame_queue.put_nowait(frame)
                    except queue.Empty:
                        pass
            
            # 控制帧率（HTTP模式下不需要太频繁）
            if self._mode == "http":
                time.sleep(0.15)  # ~6fps上限
    
    def get_frame(self, timeout_ms=1000):
        """
        获取最新帧
        返回: numpy array (BGR格式) 或 None
        """
        try:
            return self._frame_queue.get(timeout=timeout_ms / 1000.0)
        except queue.Empty:
            return None
    
    def get_frame_base64(self, timeout_ms=1000, quality=85):
        """
        获取最新帧的Base64编码JPEG
        返回: {"ok": bool, "data": str(base64), "size": int, ...}
        """
        frame = self.get_frame(timeout_ms)
        if frame is None:
            return {"ok": False, "error": "no frame available"}
        
        try:
            import cv2
            encode_params = [cv2.IMWRITE_JPEG_QUALITY, quality]
            _, jpeg_data = cv2.imencode(".jpg", frame, encode_params)
            
            import base64
            b64 = base64.b64encode(jpeg_data.tobytes()).decode()
            
            return {
                "ok": True,
                "data": b64,
                "size": len(b64),
                "width": frame.shape[1],
                "height": frame.shape[0],
                "mode": self._mode,
                "latency_ms": self._stats["avg_latency_ms"],
            }
        except Exception as ex:
            return {"ok": False, "error": str(ex)}
    
    def switch_channel(self, channel):
        """切换通道"""
        old_mode = self._mode
        
        if self._mode == "rtsp":
            self._close_rtsp()
        
        if self._mode == "rtsp":
            self._init_rtsp(channel)
        # HTTP模式下直接在_do_http_snapshot中用新channel
        
        logger.info("Switched to channel %d", channel)
    
    def __enter__(self):
        self.start()
        return self
    
    def __exit__(self, *args):
        self.stop()


# ── CLI测试 ───────────────────────────────────────────
if __name__ == "__main__":
    print("=" * 55)
    print("火瞳 FrameGrabber CLI Test")
    print("=" * 55)
    
    fg = FrameGrabber()
    
    print("\nStarting...")
    if not fg.start():
        print("Failed to start!")
        sys.exit(1)
    
    print("Mode: %s" % fg.mode)
    print("Capturing 5 frames...\n")
    
    for i in range(5):
        result = fg.get_frame_base64(timeout_ms=3000)
        if result["ok"]:
            print("  Frame %d: OK  %dx%d  %dB  mode=%s  latency=%dms" % (
                i+1, result["width"], result["height"],
                result["size"], result["mode"], result["latency_ms"]))
        else:
            print("  Frame %d: FAIL - %s" % (i+1, result.get("error", "?")))
    
    print("\nStats:", fg.stats)
    fg.stop()
    print("Done!")
