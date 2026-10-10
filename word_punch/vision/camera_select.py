"""Pick which camera to open: an external (USB) webcam beats the laptop's built-in one.

Settings ([camera]):
    index = "auto"    pick automatically (or a number to force an OpenCV index)
    name  = ""        prefer a camera whose name contains this (e.g. "C270")
"""
from __future__ import annotations

import sys
from dataclasses import dataclass

BUILT_IN = ("integrated", "built-in", "builtin", "internal", "facetime", "front", "rear", " ir ")
VIRTUAL = ("virtual", "eos webcam", "broadcast", "obs ", "snap camera", "droidcam", "xsplit",
           "manycam", "streamlabs", "nvidia", " ndi ", "camo ")
# Raspberry Pi V4L2 nodes that are codecs/ISPs, not cameras.
NOT_CAMERAS = ("bcm2835", "unicam", "rpivid", "pispbe", "rpi-hevc", "codec", "-isp")


@dataclass
class CameraInfo:
    index: int
    name: str
    backend: int
    has_hw_id: bool  # has a USB vendor id (virtual cameras don't)


def rank(cam: CameraInfo, prefer_name: str = "") -> int | None:
    """Higher is better; None = never pick it automatically."""
    name = f" {cam.name.lower()} "
    if prefer_name and prefer_name.lower() in name:
        return 100
    if any(v in name for v in VIRTUAL) or any(n in name for n in NOT_CAMERAS):
        return None
    if any(b in name for b in BUILT_IN):
        return 10
    return 50 if cam.has_hw_id or sys.platform != "win32" else 30


def choose(cams: list[CameraInfo], prefer_name: str = "") -> CameraInfo | None:
    ranked = [(r, -c.index, c) for c in cams if (r := rank(c, prefer_name)) is not None]
    if not ranked:
        return None
    return max(ranked, key=lambda x: (x[0], x[1]))[2]


def list_cameras(backend: int) -> list[CameraInfo]:
    try:
        from cv2_enumerate_cameras import enumerate_cameras
    except ImportError:
        return []
    return [CameraInfo(c.index, c.name or "", c.backend, c.vid is not None)
            for c in enumerate_cameras(backend)]


def resolve(cam_cfg: dict, backend: int) -> tuple[int, str]:
    """(OpenCV index, display name) to open."""
    index = cam_cfg.get("index", "auto")
    cams = list_cameras(backend)
    if index != "auto":
        name = next((c.name for c in cams if c.index == int(index)), f"camera {index}")
        return int(index), name
    best = choose(cams, cam_cfg.get("name", ""))
    if best is None:
        return 0, "camera 0"
    return best.index, best.name
