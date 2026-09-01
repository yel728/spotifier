from __future__ import annotations

import os
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

from .config import Config

RUNTIME_DIR = Path(os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")) / "spotifier"
LIBRESPOT_PID_PATH = RUNTIME_DIR / "librespot.pid"


def normalize_playback(raw: dict[str, Any] | None) -> dict[str, Any]:
    if not raw:
        return {
            "has_track": False,
            "uri": "",
            "title": "",
            "artist": "",
            "album": "",
            "art_url": "",
            "length_s": 0.0,
            "position_s": 0.0,
            "status": "Stopped",
            "volume": 0.0,
            "shuffle": False,
            "repeat_mode": "None",
        }
    item = raw.get("item") or {}
    album = item.get("album") or {}
    images = album.get("images") or []
    repeat_mode = {
        "off": "None",
        "context": "Playlist",
        "track": "Track",
    }.get(str(raw.get("repeat_state") or ""), "None")
    return {
        "has_track": bool(item),
        "uri": item.get("uri", ""),
        "title": item.get("name", ""),
        "artist": ", ".join(artist.get("name", "") for artist in item.get("artists", [])),
        "album": album.get("name", ""),
        "art_url": images[0].get("url", "") if images else "",
        "length_s": float(item.get("duration_ms") or 0) / 1000,
        "position_s": float(raw.get("progress_ms") or 0) / 1000,
        "status": "Playing" if raw.get("is_playing") else "Paused",
        "volume": float((raw.get("device") or {}).get("volume_percent") or 0) / 100,
        "shuffle": bool(raw.get("shuffle_state")),
        "repeat_mode": repeat_mode,
    }


class LibrespotSupervisor:
    def __init__(self, config: Config):
        self.config = config
        self.process: subprocess.Popen[str] | None = None
        self.login_url = ""
        self.last_lines: list[str] = []
        self.stopping = threading.Event()
        self.monitor_thread: threading.Thread | None = None

    @property
    def running(self) -> bool:
        return self.process is not None and self.process.poll() is None

    def start(self) -> None:
        if not shutil.which("librespot"):
            raise RuntimeError("librespot is not installed")
        if self.running:
            return
        self.stopping.clear()
        self._terminate_stale_process()
        self._spawn()
        self.monitor_thread = threading.Thread(target=self._monitor, name="librespot-monitor", daemon=True)
        self.monitor_thread.start()

    def stop(self) -> None:
        self.stopping.set()
        process = self.process
        if process and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2)
        self.process = None
        LIBRESPOT_PID_PATH.unlink(missing_ok=True)

    def reset_credentials(self) -> None:
        self.stop()
        try:
            cache_index = self.config.librespot_args.index("--cache")
            cache_path = Path(self.config.librespot_args[cache_index + 1])
        except (ValueError, IndexError):
            cache_path = Path.home() / ".cache/librespot"
        (cache_path / "credentials.json").unlink(missing_ok=True)
        self.start()

    def _spawn(self) -> None:
        self.login_url = ""
        command = ["librespot", *self.config.librespot_args]
        self.process = subprocess.Popen(
            command,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            bufsize=1,
        )
        RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
        LIBRESPOT_PID_PATH.write_text(f"{self.process.pid}\n")
        threading.Thread(target=self._capture_output, name="librespot-output", daemon=True).start()
        print("started:", " ".join(command))

    def _capture_output(self) -> None:
        process = self.process
        if not process or not process.stdout:
            return
        for line in process.stdout:
            line = line.rstrip()
            print(line)
            self.last_lines = (self.last_lines + [line])[-30:]
            match = re.search(r"Browse to:\s*(https?://\S+)", line)
            if match:
                self.login_url = match.group(1)

    def _monitor(self) -> None:
        while not self.stopping.wait(2):
            if self.process is not None and self.process.poll() is not None:
                print("librespot exited; restarting in 3s", file=sys.stderr)
                if self.stopping.wait(3):
                    return
                self._terminate_stale_process()
                self._spawn()

    def _terminate_stale_process(self) -> None:
        try:
            pid = int(LIBRESPOT_PID_PATH.read_text())
            command = Path(f"/proc/{pid}/cmdline").read_bytes().split(b"\0", 1)[0]
            if Path(os.fsdecode(command)).name != "librespot":
                return
            os.kill(pid, signal.SIGTERM)
            for _ in range(30):
                try:
                    os.kill(pid, 0)
                except ProcessLookupError:
                    break
                time.sleep(0.05)
        except (FileNotFoundError, ProcessLookupError, ValueError):
            pass
        finally:
            LIBRESPOT_PID_PATH.unlink(missing_ok=True)
