from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

CONFIG_DIR = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "spotifier"
CONFIG_PATH = CONFIG_DIR / "config.json"


@dataclass
class Config:
    host: str = "127.0.0.1"
    port: int = 8765
    device_name: str = "Spotifier"
    librespot_zeroconf_port: int = 8766
    player_cache: str = "~/.cache/spotifier/librespot"


def _expand_path(path: str) -> str:
    return os.path.expandvars(os.path.expanduser(path))


def load_config() -> Config:
    if not CONFIG_PATH.exists():
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        cfg = Config()
        CONFIG_PATH.write_text(json.dumps(cfg.__dict__, indent=2) + "\n")
        cfg.player_cache = _expand_path(cfg.player_cache)
        return cfg

    raw: dict[str, Any] = json.loads(CONFIG_PATH.read_text())
    cfg = Config(**{k: v for k, v in raw.items() if k in Config.__dataclass_fields__})
    cfg.player_cache = _expand_path(cfg.player_cache)
    return cfg
