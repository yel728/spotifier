from __future__ import annotations

import fcntl
import os
from pathlib import Path

from .config import load_config
from .server import run

RUNTIME_DIR = Path(os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")) / "spotifier"
LOCK_PATH = RUNTIME_DIR / "daemon.lock"


def main() -> None:
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    with LOCK_PATH.open("w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise SystemExit("spotifierd is already running") from error
        lock.write(f"{os.getpid()}\n")
        lock.flush()
        run(load_config())


if __name__ == "__main__":
    main()
