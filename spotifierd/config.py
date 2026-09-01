from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

CONFIG_DIR = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "spotifier"
CONFIG_PATH = CONFIG_DIR / "config.json"


@dataclass
class Config:
    host: str = "127.0.0.1"
    port: int = 8765
    device_name: str = "Spotifier"
    librespot_args: list[str] = field(default_factory=lambda: [
        "--name", "Spotifier",
        "--enable-oauth",
        "--enable-volume-normalisation",
        "--cache", "~/.cache/spotifier/librespot",
    ])


def _expand_args(args: list[str]) -> list[str]:
    return [os.path.expandvars(os.path.expanduser(a)) for a in args]


def load_config() -> Config:
    if not CONFIG_PATH.exists():
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        cfg = Config()
        CONFIG_PATH.write_text(json.dumps(cfg.__dict__, indent=2) + "\n")
        return cfg

    raw: dict[str, Any] = json.loads(CONFIG_PATH.read_text())
    cfg = Config(**{k: v for k, v in raw.items() if k in Config.__dataclass_fields__})
    cfg.librespot_args = _expand_args(cfg.librespot_args)
    return cfg
