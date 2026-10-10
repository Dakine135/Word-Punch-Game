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
    "pose_landmarker_heavy.task":
        "https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_heavy/float16/latest/pose_landmarker_heavy.task",
}
VOICE = "en_US-lessac-medium"  # Piper voice for reading words aloud
VOICE_URL = "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium/"
VOSK_MODELS = ["vosk-model-small-en-us-0.15",    # fast (Raspberry Pi)
               "vosk-model-en-us-0.22-lgraph"]   # accurate, much better with kids' voices (default)
VOSK_URL = "https://alphacephei.com/vosk/models/{}.zip"


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
    for name in VOSK_MODELS:
        if not (MODELS / name).exists():
            zip_path = MODELS / f"{name}.zip"
            download(VOSK_URL.format(name), zip_path)
            with zipfile.ZipFile(zip_path) as z:
                z.extractall(MODELS)
            zip_path.unlink()
    for ext in (".onnx", ".onnx.json"):
        dest = MODELS / f"{VOICE}{ext}"
        if not dest.exists():
            download(VOICE_URL + f"{VOICE}{ext}", dest)
    print("models ready in", MODELS)
    return 0


if __name__ == "__main__":
    sys.exit(main())
