import os
from pathlib import Path

# Downloaded models (Whisper etc.) live with the game, not in the user's shared cache.
os.environ.setdefault("HF_HOME", str(Path(__file__).resolve().parent.parent / "models" / "hf"))
