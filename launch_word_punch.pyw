"""Double-click launcher (used by the desktop shortcut): starts Word Punch fullscreen on the
start screen, with no console window. Output and any crash go to logs/last_run.log.

Create the desktop shortcut with:  python tools/make_shortcut.py
"""
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))


def main() -> int:
    logs = ROOT / "logs"
    logs.mkdir(exist_ok=True)
    log = open(logs / "last_run.log", "w", encoding="utf-8", buffering=1)
    sys.stdout = sys.stderr = log
    print(f"Word Punch started {time.strftime('%Y-%m-%d %H:%M:%S')}")
    try:
        from word_punch.app import main as app_main
        return app_main(["--fullscreen"] + sys.argv[1:])
    except Exception:
        traceback.print_exc()
        try:  # tell the grown-up something went wrong instead of silently closing
            import ctypes
            ctypes.windll.user32.MessageBoxW(
                0, f"Word Punch stopped with an error.\n\nDetails: {logs / 'last_run.log'}", "Word Punch", 0x10)
        except Exception:
            pass
        return 1
    finally:
        print(f"Word Punch closed {time.strftime('%Y-%m-%d %H:%M:%S')}")
        log.close()


if __name__ == "__main__":
    sys.exit(main())
