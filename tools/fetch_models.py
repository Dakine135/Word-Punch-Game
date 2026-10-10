"""Download the speech and pose models into models/. Safe to re-run; skips what exists."""
from __future__ import annotations

import sys
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MODELS = ROOT / "models"

POSE = {
    "pose_landmarker_lite.task":
        "https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_lite/float16/latest/pose_landmarker_lite.task",
    "pose_landmarker_full.task":
        "https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_full/float16/latest/pose_landmarker_full.task",
}
VOSK_NAME = "vosk-model-small-en-us-0.15"
VOSK_URL = f"https://alphacephei.com/vosk/models/{VOSK_NAME}.zip"


def download(url: str, dest: Path) -> None:
    print(f"downloading {url}")
    tmp = dest.with_suffix(dest.suffix + ".part")
    with urllib.request.urlopen(url) as resp, open(tmp, "wb") as f:
        total = int(resp.headers.get("Content-Length", 0))
        done = 0
        while chunk := resp.read(1 << 16):
            f.write(chunk)
            done += len(chunk)
            if total:
                print(f"\r  {done * 100 // total:3d}%", end="", flush=True)
    print()
    tmp.replace(dest)


def main() -> int:
    MODELS.mkdir(exist_ok=True)
    for name, url in POSE.items():
        dest = MODELS / name
        if not dest.exists():
            download(url, dest)
    vosk_dir = MODELS / VOSK_NAME
    if not vosk_dir.exists():
        zip_path = MODELS / f"{VOSK_NAME}.zip"
        download(VOSK_URL, zip_path)
        with zipfile.ZipFile(zip_path) as z:
            z.extractall(MODELS)
        zip_path.unlink()
    print("models ready in", MODELS)
    return 0


if __name__ == "__main__":
    sys.exit(main())
