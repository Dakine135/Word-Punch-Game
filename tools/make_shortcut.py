"""Make the Word Punch icon and a desktop shortcut that launches the game (Windows).

    python tools/make_shortcut.py
"""
from __future__ import annotations

import io
import os
import struct
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

import pygame

ICON = ROOT / "assets" / "word_punch.ico"


def render_icon(size: int) -> bytes:
    """A gold badge with a red boxing glove, as PNG bytes."""
    from word_punch.ui.render import Renderer
    big = 512
    surf = pygame.Surface((big, big), pygame.SRCALPHA)
    pygame.draw.circle(surf, (255, 200, 40), (big // 2, big // 2), big // 2 - 4)
    pygame.draw.circle(surf, (30, 36, 70), (big // 2, big // 2), big // 2 - 30)
    for i in range(12):  # burst rays
        import math
        a = i * math.pi / 6
        pygame.draw.line(surf, (255, 200, 40), (big / 2 + math.cos(a) * 150, big / 2 + math.sin(a) * 150),
                         (big / 2 + math.cos(a) * 215, big / 2 + math.sin(a) * 215), 18)
    glove = Renderer((1280, 720)).glove((235, 60, 60), 330)
    surf.blit(glove, glove.get_rect(center=(big // 2, big // 2 + 6)))
    img = pygame.transform.smoothscale(surf, (size, size))
    buf = io.BytesIO()
    pygame.image.save(img, buf, "icon.png")
    return buf.getvalue()


def write_ico(path: Path, sizes=(256, 64, 48, 32, 16)) -> None:
    """An .ico holding PNG images (supported since Windows Vista)."""
    pngs = [render_icon(s) for s in sizes]
    header = struct.pack("<HHH", 0, 1, len(pngs))
    entries, offset = b"", 6 + 16 * len(pngs)
    for s, data in zip(sizes, pngs):
        entries += struct.pack("<BBBBHHII", s % 256, s % 256, 0, 0, 1, 32, len(data), offset)
        offset += len(data)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(header + entries + b"".join(pngs))


def make_shortcut() -> Path:
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    launcher = ROOT / "launch_word_punch.pyw"
    ps = f"""
$desktop = [Environment]::GetFolderPath('Desktop')
$lnk = Join-Path $desktop 'Word Punch.lnk'
$s = (New-Object -ComObject WScript.Shell).CreateShortcut($lnk)
$s.TargetPath = '{pythonw}'
$s.Arguments = '"{launcher}"'
$s.WorkingDirectory = '{ROOT}'
$s.IconLocation = '{ICON},0'
$s.Description = 'Word Punch - read it, punch it!'
$s.Save()
Write-Output $lnk
"""
    out = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True, check=True)
    return Path(out.stdout.strip())


def main() -> int:
    pygame.init()
    write_ico(ICON)
    print("icon:", ICON)
    print("shortcut:", make_shortcut())
    return 0


if __name__ == "__main__":
    sys.exit(main())
