"""Frame sources for edge vision — file demo mode (no real RTSP required)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import cv2
import numpy as np


class FrameSource(ABC):
    @abstractmethod
    def read(self) -> Tuple[Optional[np.ndarray], Dict[str, Any]]:
        """Return BGR frame and metadata."""


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


class RtspFrameSource(FrameSource):
    """RTSP placeholder — not enabled in PoC without real cameras."""

    def __init__(self, rtsp_url: str, fallback: Path, camera_id: str = "", zone: str = "front") -> None:
        self.rtsp_url = rtsp_url
        self.fallback = FileFrameSource(fallback, camera_id, zone)
        self.camera_id = camera_id
        self.zone = zone
        self._warned = False

    def read(self) -> Tuple[Optional[np.ndarray], Dict[str, Any]]:
        if not self._warned:
            print(
                f"[FrameSource] RTSP disabled in PoC, using file fallback for {self.camera_id or self.zone}",
                file=__import__("sys").stderr,
            )
            self._warned = True
        frame, meta = self.fallback.read()
        meta["source"] = "rtsp_fallback_file"
        meta["rtsp_url"] = self.rtsp_url
        return frame, meta


def create_source(camera: Dict[str, Any], zone: str, file_path: Path) -> FrameSource:
    mode = camera.get("stream_mode", "file")
    cam_id = camera.get("id", zone)
    if mode == "rtsp" and camera.get("rtsp"):
        return RtspFrameSource(camera["rtsp"], file_path, cam_id, zone)
    return FileFrameSource(file_path, cam_id, zone)
