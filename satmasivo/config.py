"""Config local. Nunca guarda CIEC ni FIEL."""

from __future__ import annotations

import json
import os
from pathlib import Path


def _config_dir() -> Path:
    if os.name == "nt":
        return Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "satmasivo"
    return Path.home() / ".config" / "satmasivo"


CONFIG_DIR = _config_dir()
CONFIG_PATH = CONFIG_DIR / "config.json"


def load_config() -> dict:
    if not CONFIG_PATH.is_file():
        return {}
    try:
        data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def save_config(data: dict) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    clean = {k: v for k, v in data.items() if k not in {"ciec", "password", "fiel_password", "key_password"}}
    CONFIG_PATH.write_text(json.dumps(clean, indent=2) + "\n", encoding="utf-8")
    try:
        CONFIG_PATH.chmod(0o600)
    except OSError:
        pass
