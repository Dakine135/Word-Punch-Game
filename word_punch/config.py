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
    for section, key in (("pose", "mediapipe_model"), ("speech", "model"), ("voice", "model")):
        p = Path(cfg[section][key])
        if not p.is_absolute():
            cfg[section][key] = str(ROOT / p)
    return cfg


def _toml_value(v) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return repr(v)
    if isinstance(v, str):
        return '"' + v.replace("\\", "\\\\").replace('"', '\\"') + '"'
    if isinstance(v, list):
        return "[" + ", ".join(_toml_value(x) for x in v) + "]"
    raise TypeError(f"can't write {type(v).__name__} to settings.toml")


def save_user(section: str, key: str, value, path: Path | None = None) -> Path:
    """Set one value in settings.toml (created if missing), keeping its other settings.

    Note: comments in settings.toml are not preserved.
    """
    path = path or ROOT / "settings.toml"
    data = tomllib.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    data.setdefault(section, {})[key] = value
    lines = ["# Your overrides of word_punch/default_settings.toml", ""]
    for sec, values in data.items():
        lines.append(f"[{sec}]")
        lines += [f"{k} = {_toml_value(v)}" for k, v in values.items()]
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")
    return path
