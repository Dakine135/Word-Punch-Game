"""Settings: package defaults overlaid with the optional settings.toml at the project root."""
from __future__ import annotations

import tomllib
from pathlib import Path

PACKAGE = Path(__file__).resolve().parent
ROOT = PACKAGE.parent


def _merge(base: dict, over: dict) -> dict:
    out = dict(base)
    for k, v in over.items():
        out[k] = _merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def load(path: Path | None = None) -> dict:
    cfg = tomllib.loads((PACKAGE / "default_settings.toml").read_text(encoding="utf-8"))
    user = path or ROOT / "settings.toml"
    if user.exists():
        cfg = _merge(cfg, tomllib.loads(user.read_text(encoding="utf-8")))
    # Model paths are relative to the project root.
    for section, key in (("pose", "mediapipe_model"), ("speech", "model")):
        p = Path(cfg[section][key])
        if not p.is_absolute():
            cfg[section][key] = str(ROOT / p)
    return cfg
