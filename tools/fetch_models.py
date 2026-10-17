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
    "gesture_recognizer.task":
        "https://storage.googleapis.com/mediapipe-models/gesture_recognizer/gesture_recognizer/float16/latest/gesture_recognizer.task",
    "pose_landmarker_heavy.task":
        "https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_heavy/float16/latest/pose_landmarker_heavy.task",
}
YOLO_URL = "https://github.com/ultralytics/assets/releases/download/v8.3.0/{}"
YOLO_POSE = ["yolo11n-pose.pt", "yolo11s-pose.pt", "yolo11m-pose.pt", "yolo11l-pose.pt", "yolo11x-pose.pt"]
# Background music: CC0 (public domain) tracks from OpenGameArt.org.
MUSIC_DIR = ROOT / "assets" / "music"
MUSIC = {  # local file: (url, title, artist, page)
    "menu_happy_clappy.wav": ("https://opengameart.org/sites/default/files/HappyClappyLoop.wav",
                              "Happy Clappy Loop", "(see page)", "https://opengameart.org/content/happy-clappy-loop"),
    "game_arplands.ogg": ("https://opengameart.org/sites/default/files/the_arplands_0.ogg",
                          "The Arplands", "LordZintick", "https://opengameart.org/content/the-arplands"),
    "game_happy_adventure.mp3": ("https://opengameart.org/sites/default/files/happy_adveture.mp3",
                                 "Happy Adventure (Loop)", "TinyWorlds",
                                 "https://opengameart.org/content/happy-adventure-loop"),
    "boss_fight_bounce.mp3": ("https://opengameart.org/sites/default/files/Boss%20Fight%20Bounce.mp3",
                              "Boss Fight Bounce", "Locomule", "https://opengameart.org/content/boss-fight-bounce"),
    "calm_concentration.mp3": ("https://opengameart.org/sites/default/files/game_3.mp3",
                               "8 Bit Concentration Loop", "cosmac",
                               "https://opengameart.org/content/8-bit-concentration-loop"),
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
    for name in YOLO_POSE:
        if not (MODELS / name).exists():
            download(YOLO_URL.format(name), MODELS / name)
    for ext in (".onnx", ".onnx.json"):
        dest = MODELS / f"{VOICE}{ext}"
        if not dest.exists():
            download(VOICE_URL + f"{VOICE}{ext}", dest)
    MUSIC_DIR.mkdir(parents=True, exist_ok=True)
    credits = ["Background music - all CC0 (public domain) from OpenGameArt.org. Thank you!", ""]
    for name, (url, title, artist, page) in MUSIC.items():
        if not (MUSIC_DIR / name).exists():
            download(url, MUSIC_DIR / name)
        credits.append(f"{name}: \"{title}\" by {artist} - {page} - CC0")
    (MUSIC_DIR / "CREDITS.txt").write_text("\n".join(credits) + "\n", encoding="utf-8")
    print("models ready in", MODELS)
    return 0


if __name__ == "__main__":
    sys.exit(main())
