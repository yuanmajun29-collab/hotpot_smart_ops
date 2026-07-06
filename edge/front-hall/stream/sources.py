"""Frame sources for edge vision — file demo mode + RTSP with reconnect."""

from __future__ import annotations

import os
import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import cv2
import numpy as np


class FrameSource(ABC):
    @abstractmethod
    def read(self) -> Tuple[Optional[np.ndarray], Dict[str, Any]]:
        """Return BGR frame and metadata."""

    def close(self) -> None:
        pass


class FileFrameSource(FrameSource):
    """Static image or looping video file."""

    def __init__(self, path: Path, camera_id: str = "", zone: str = "front") -> None:
        self.path = path
        self.camera_id = camera_id
        self.zone = zone
        self._cap = None
        if path.suffix.lower() in (".mp4", ".avi", ".mkv", ".mov"):
            self._cap = cv2.VideoCapture(str(path))

    def read(self) -> Tuple[Optional[np.ndarray], Dict[str, Any]]:
        meta = {
            "source": "file",
            "path": str(self.path),
            "camera_id": self.camera_id,
            "zone": self.zone,
        }
        if self._cap is not None:
            ok, frame = self._cap.read()
            if not ok:
                self._cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                ok, frame = self._cap.read()
            return (frame if ok else None), meta
        frame = cv2.imread(str(self.path))
        return frame, meta

    def close(self) -> None:
        if self._cap is not None:
            self._cap.release()
            self._cap = None


class RtspFrameSource(FrameSource):
    """RTSP live stream with reconnect and file fallback."""

    def __init__(
        self,
        rtsp_url: str,
        fallback: Path,
        camera_id: str = "",
        zone: str = "front",
        *,
        open_timeout_sec: float = 5.0,
        max_failures: int = 3,
        reconnect_delay_sec: float = 2.0,
    ) -> None:
        self.rtsp_url = rtsp_url
        self.fallback_path = fallback
        self.camera_id = camera_id
        self.zone = zone
        self.open_timeout_sec = open_timeout_sec
        self.max_failures = max_failures
        self.reconnect_delay_sec = reconnect_delay_sec
        self._cap: Optional[cv2.VideoCapture] = None
        self._failures = 0
        self._using_fallback = False
        self._file_fallback = FileFrameSource(fallback, camera_id, zone)
        self._rtsp_enabled = os.environ.get("HOTPOT_RTSP_ENABLED", "1") != "0"

    def _open_stream(self) -> bool:
        if self._cap is not None:
            self._cap.release()
            self._cap = None
        if not self._rtsp_enabled:
            return False
        cap = cv2.VideoCapture(self.rtsp_url, cv2.CAP_FFMPEG)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        deadline = time.time() + self.open_timeout_sec
        while time.time() < deadline:
            if cap.isOpened():
                ok, frame = cap.read()
                if ok and frame is not None:
                    self._cap = cap
                    self._failures = 0
                    self._using_fallback = False
                    return True
            time.sleep(0.2)
        cap.release()
        return False

    def read(self) -> Tuple[Optional[np.ndarray], Dict[str, Any]]:
        meta: Dict[str, Any] = {
            "camera_id": self.camera_id,
            "zone": self.zone,
            "rtsp_url": self.rtsp_url,
        }

        if self._using_fallback or not self._rtsp_enabled:
            frame, file_meta = self._file_fallback.read()
            meta.update(file_meta)
            meta["source"] = "rtsp_fallback_file"
            meta["rtsp_failures"] = self._failures
            return frame, meta

        if self._cap is None and not self._open_stream():
            self._failures += 1
            if self._failures >= self.max_failures:
                print(
                    f"[FrameSource] RTSP unavailable for {self.camera_id or self.zone}, "
                    f"using file fallback ({self.fallback_path})",
                    file=__import__("sys").stderr,
                )
                self._using_fallback = True
            frame, file_meta = self._file_fallback.read()
            meta.update(file_meta)
            meta["source"] = "rtsp_fallback_file"
            meta["rtsp_failures"] = self._failures
            return frame, meta

        ok, frame = self._cap.read() if self._cap else (False, None)
        if ok and frame is not None:
            meta["source"] = "rtsp"
            return frame, meta

        self._failures += 1
        if self._cap:
            self._cap.release()
            self._cap = None
        if self._failures >= self.max_failures:
            self._using_fallback = True
            frame, file_meta = self._file_fallback.read()
            meta.update(file_meta)
            meta["source"] = "rtsp_fallback_file"
            meta["rtsp_failures"] = self._failures
            return frame, meta

        time.sleep(self.reconnect_delay_sec)
        self._open_stream()
        meta["source"] = "rtsp_reconnecting"
        return None, meta

    def close(self) -> None:
        if self._cap is not None:
            self._cap.release()
            self._cap = None
        self._file_fallback.close()


def create_source(camera: Dict[str, Any], zone: str, file_path: Path) -> FrameSource:
    mode = camera.get("stream_mode", "file")
    cam_id = camera.get("id", zone)
    if mode == "rtsp" and camera.get("rtsp"):
        return RtspFrameSource(camera["rtsp"], file_path, cam_id, zone)
    return FileFrameSource(file_path, cam_id, zone)
