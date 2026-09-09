from __future__ import annotations

import json
import math
import os
import re
import signal
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable

from .config import Config

RUNTIME_DIR = Path(os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")) / "spotifier"
LIBRESPOT_PID_PATH = RUNTIME_DIR / "librespot.pid"
EVENT_SOCKET_PATH = RUNTIME_DIR / "events.sock"
CONTROL_SOCKET_PATH = RUNTIME_DIR / "control.sock"
PLAYER_BINARY_PATH = Path(__file__).parent.parent / "player/target/release/spotifier-player"


def normalize_playback(raw: dict[str, Any] | None) -> dict[str, Any]:
    if not raw:
        return {
            "has_track": False,
            "track_loaded": False,
            "context_uri": "",
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
            "playback_error": "",
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
        "track_loaded": bool(item),
        "context_uri": str((raw.get("context") or {}).get("uri") or ""),
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
        "playback_error": "",
    }

class EventPlaybackState:
    def __init__(self) -> None:
        self._state = normalize_playback(None)
        self._requested_uri = ""
        self._position_updated = time.monotonic()
        self._version = 0
        self._condition = threading.Condition()

    def apply(self, event: dict[str, str]) -> None:
        name = event.get("PLAYER_EVENT", "")
        with self._condition:
            if name == "load_requested":
                self._requested_uri = event.get("URI", "")
                self._state["playback_error"] = ""
            elif name == "context_changed":
                self._state["context_uri"] = event.get("CONTEXT_URI", "")
            elif name == "selection_restored":
                self._state.update(json.loads(event["STATE"]))
                self._state["track_loaded"] = False
                self._state["status"] = "Paused"
                self._position_updated = time.monotonic()
            elif name == "unavailable":
                if self._requested_uri != f"spotify:track:{event.get('TRACK_ID', '')}":
                    return
                self._state["playback_error"] = (
                    "The selected track is unavailable on Spotify. The player skipped it."
                )
            elif name == "track_changed":
                covers = event.get("COVERS", "").splitlines()
                self._state.update({
                    "has_track": True,
                    "uri": event.get("URI") or f"spotify:track:{event.get('TRACK_ID', '')}",
                    "title": event.get("NAME", ""),
                    "artist": ", ".join(event.get("ARTISTS", "").splitlines()),
                    "album": event.get("ALBUM", ""),
                    "art_url": covers[0] if covers else "",
                    "length_s": self._seconds(event.get("DURATION_MS")),
                    "position_s": 0.0,
                })
                self._position_updated = time.monotonic()
            elif name in ("playing", "paused", "seeked", "position_correction"):
                if not self._state["uri"] and event.get("TRACK_ID"):
                    self._state["uri"] = f"spotify:track:{event['TRACK_ID']}"
                    self._state["has_track"] = True
                if event.get("POSITION_MS") is not None:
                    self._state["position_s"] = self._seconds(event.get("POSITION_MS"))
                if name in ("playing", "paused"):
                    self._state["track_loaded"] = True
                if name == "playing":
                    self._state["status"] = "Playing"
                elif name == "paused":
                    self._state["status"] = "Paused"
                self._position_updated = time.monotonic()
            elif name in ("stopped", "session_disconnected", "player_reset"):
                # A stopped/deactivated device can still have a resumable selection.
                # Freeze its position instead of erasing metadata and controls.
                if name == "stopped" and event.get("TRACK_ID"):
                    if self._state["uri"].rsplit(":", 1)[-1] != event["TRACK_ID"]:
                        return
                self._state = self.snapshot()
                self._state["track_loaded"] = False
                self._state["status"] = "Paused" if self._state["has_track"] else "Stopped"
                self._position_updated = time.monotonic()
            elif name == "clear_selection":
                self._state = normalize_playback(None)
                self._requested_uri = ""
                self._position_updated = time.monotonic()
            elif name == "recovery_failed":
                self._state["playback_error"] = event.get("ERROR", "Unable to restore playback")
            elif name == "volume_changed":
                volume = self._number(event.get("VOLUME"))
                self._state["volume"] = max(0.0, min(1.0, volume / 65535 if volume > 1 else volume))
            elif name == "shuffle_changed":
                self._state["shuffle"] = event.get("SHUFFLE") == "true"
            elif name == "repeat_changed":
                self._state["repeat_mode"] = (
                    "Track" if event.get("REPEAT_TRACK") == "true"
                    else "Playlist" if event.get("REPEAT") == "true"
                    else "None"
                )
            elif name == "service_changed":
                pass
            else:
                return
            self._version += 1
            self._condition.notify_all()

    def snapshot(self) -> dict[str, Any]:
        with self._condition:
            state = dict(self._state)
            if state["status"] == "Playing":
                position = float(state["position_s"]) + time.monotonic() - self._position_updated
                length = float(state["length_s"])
                state["position_s"] = min(position, length) if length else position
            return state

    def wait(self, version: int, timeout: float) -> tuple[int, dict[str, Any] | None]:
        with self._condition:
            if self._version == version:
                self._condition.wait(timeout)
            if self._version == version:
                return version, None
            return self._version, self.snapshot()

    @staticmethod
    def _number(value: str | None) -> float:
        try:
            return float(value or 0)
        except ValueError:
            return 0.0

    @classmethod
    def _seconds(cls, value: str | None) -> float:
        return cls._number(value) / 1000


class LibrespotSupervisor:
    def __init__(self, config: Config, event_callback: Callable[[dict[str, str]], None] | None = None,
                 snapshot_callback: Callable[[], dict[str, Any]] | None = None,
                 checkpoint_path: Path | None = None):
        self.config = config
        self.event_callback = event_callback
        self.snapshot_callback = snapshot_callback
        self.checkpoint_path = checkpoint_path
        self.recovery: dict[str, Any] | None = None
        self.context_uri = ""
        self.player_ready = False
        self.restore_sent = False
        self.restore_requested_at = 0.0
        self.restore_attempts = 0
        self.process: subprocess.Popen[str] | None = None
        self.login_url = ""
        self.last_lines: list[str] = []
        self.stopping = threading.Event()
        self.monitor_thread: threading.Thread | None = None
        self.event_socket: socket.socket | None = None
        self.event_thread: threading.Thread | None = None
        self.load_lock = threading.RLock()
        self.load_generation = 0
        self.load_timer: threading.Timer | None = None

    @property
    def running(self) -> bool:
        return self.process is not None and self.process.poll() is None

    def start(self) -> None:
        if not PLAYER_BINARY_PATH.is_file():
            raise RuntimeError(f"Spotifier player is not built: run cargo build --release in {PLAYER_BINARY_PATH.parent.parent.parent}")
        if self.running:
            return
        self.stopping.clear()
        self._start_event_listener()
        self._terminate_stale_process()
        self._load_checkpoint()
        self._spawn()
        self.monitor_thread = threading.Thread(target=self._monitor, name="librespot-monitor", daemon=True)
        self.monitor_thread.start()

    def stop(self) -> None:
        self.stopping.set()
        with self.load_lock:
            self._save_checkpoint()
            self.recovery = None
            self.load_generation += 1
            if self.load_timer is not None:
                self.load_timer.cancel()
                self.load_timer = None
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
        event_socket = self.event_socket
        self.event_socket = None
        if event_socket is not None:
            event_socket.close()
        if self.event_thread is not None:
            self.event_thread.join(timeout=1)
            self.event_thread = None
        EVENT_SOCKET_PATH.unlink(missing_ok=True)
        CONTROL_SOCKET_PATH.unlink(missing_ok=True)

    def reset_credentials(self) -> None:
        self.stop()
        self.context_uri = ""
        if self.checkpoint_path is not None:
            self.checkpoint_path.unlink(missing_ok=True)
        if self.event_callback is not None:
            self.event_callback({"PLAYER_EVENT": "clear_selection"})
        (Path(self.config.player_cache) / "credentials.json").unlink(missing_ok=True)
        self.start()

    def request(self, value: str, timeout: float = 1.0) -> str:
        if not self.running:
            raise RuntimeError("Local Spotify player is not running")
        chunks: list[bytes] = []
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as control:
            control.settimeout(timeout)
            control.connect(str(CONTROL_SOCKET_PATH))
            control.sendall((value + "\n").encode())
            control.shutdown(socket.SHUT_WR)
            while chunk := control.recv(65536):
                chunks.append(chunk)
        response = b"".join(chunks).decode(errors="replace").strip()
        if response.startswith("error "):
            raise RuntimeError(response.removeprefix("error "))
        return response

    def command(self, value: str) -> None:
        with self.load_lock:
            state = self.snapshot_callback() if self.snapshot_callback is not None else None
            if (self.recovery is None and state and state["has_track"]
                    and not state["track_loaded"] and value in ("play", "play_pause", "pause")):
                if value == "pause":
                    return
                self.recovery = dict(state, context_uri=self.context_uri, status="Playing")
                self.restore_sent = False
                self.restore_attempts = 0
                self._restore_playback()
                return
            if self.recovery is not None and not self.restore_sent:
                if value in ("pause", "play", "play_pause"):
                    playing = self.recovery["status"] == "Playing"
                    self.recovery["status"] = "Playing" if (
                        value == "play" or (value == "play_pause" and not playing)
                    ) else "Paused"
                    return
            response = self.request(value)
            if response != "ok":
                raise RuntimeError(response or "Local playback command failed")
            self.recovery = None

    def load(self, track_uri: str, context_uri: str = "") -> None:
        if not self.running:
            raise RuntimeError("Local Spotify player is not running")
        with self.load_lock:
            self.recovery = None
            self.load_generation += 1
            generation = self.load_generation
            if self.load_timer is not None:
                self.load_timer.cancel()
            self.load_timer = threading.Timer(
                0.2,
                self._commit_load,
                args=(generation, track_uri, context_uri),
            )
            self.load_timer.daemon = True
            self.load_timer.start()

    def _commit_load(self, generation: int, track_uri: str, context_uri: str) -> None:
        with self.load_lock:
            if generation != self.load_generation:
                return
            self.load_timer = None
            command = " ".join(part for part in ("load", track_uri, context_uri) if part)
            try:
                if self.event_callback is not None:
                    self.event_callback({"PLAYER_EVENT": "load_requested", "URI": track_uri})
                self.command(command)
                self.context_uri = context_uri or (
                    track_uri if not track_uri.startswith(("spotify:track:", "spotify:episode:")) else "")
                if self.event_callback is not None:
                    self.event_callback({"PLAYER_EVENT": "context_changed", "CONTEXT_URI": self.context_uri})
            except (RuntimeError, OSError) as error:
                print(f"player load failed: {error}")

    def _save_checkpoint(self) -> None:
        if self.checkpoint_path is None or self.snapshot_callback is None:
            return
        state = self.recovery or dict(self.snapshot_callback(), context_uri=self.context_uri)
        if not state["has_track"]:
            return
        try:
            self.checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.checkpoint_path.with_suffix(".tmp")
            with temporary.open("w") as file:
                json.dump({"version": 1, "state": state}, file, ensure_ascii=False)
            temporary.chmod(0o600)
            temporary.replace(self.checkpoint_path)
        except OSError as error:
            print(f"could not save playback session: {error}", file=sys.stderr)

    def _load_checkpoint(self) -> None:
        if self.checkpoint_path is None:
            return
        try:
            saved = json.loads(self.checkpoint_path.read_text())
            state = saved["state"]
            if saved["version"] != 1 or not isinstance(state, dict):
                raise ValueError("unsupported checkpoint")
            if not state.get("has_track") or not state["uri"].startswith(("spotify:track:", "spotify:episode:")):
                raise ValueError("invalid saved track")
            context = state["context_uri"]
            if not isinstance(context, str) or (context and not context.startswith("spotify:")):
                raise ValueError("invalid saved context")
            if state["status"] not in ("Playing", "Paused") or state["repeat_mode"] not in ("None", "Playlist", "Track"):
                raise ValueError("invalid playback mode")
            if not isinstance(state["shuffle"], bool):
                raise ValueError("invalid shuffle mode")
            for key in ("position_s", "length_s", "volume"):
                if not isinstance(state[key], (int, float)) or not math.isfinite(state[key]) or state[key] < 0:
                    raise ValueError("invalid playback position or volume")
            if state["volume"] > 1:
                raise ValueError("invalid volume")
            state = {key: state.get(key, value) for key, value in normalize_playback(None).items()}
            self.recovery = state
            self.context_uri = context
            self.restore_sent = False
            self.restore_attempts = 0
            if self.event_callback is not None:
                self.event_callback({"PLAYER_EVENT": "selection_restored", "STATE": json.dumps(state)})
        except FileNotFoundError:
            return
        except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
            print(f"could not read saved playback session: {error}", file=sys.stderr)

    def lyrics(self, track_uri: str) -> dict[str, Any]:
        track_id = track_uri.rsplit(":", 1)[-1]
        return json.loads(self.request(f"lyrics {track_id}", timeout=10.0))

    def _remember_playback(self) -> None:
        with self.load_lock:
            if self.snapshot_callback is not None:
                state = self.snapshot_callback()
                if self.recovery is None and state["has_track"] and state["status"] in ("Playing", "Paused"):
                    self.recovery = dict(state, context_uri=self.context_uri)
            self._save_checkpoint()
            # Freeze the position across repeated failed reconnects.
            self.player_ready = False
            self.restore_sent = False
            self.restore_attempts = 0

    def _restore_playback(self) -> None:
        with self.load_lock:
            if self.stopping.is_set() or not self.player_ready or self.recovery is None:
                return
            if self.restore_sent:
                if time.monotonic() - self.restore_requested_at < 15:
                    return
                if self.restore_attempts >= 3:
                    if self.event_callback is not None:
                        self.event_callback({"PLAYER_EVENT": "recovery_failed", "ERROR":
                            "Spotify did not confirm playback. Press Play to retry."})
                    print("playback recovery timed out without a player confirmation", file=sys.stderr)
                    self.recovery = None
                    self.restore_sent = False
                    return
                self.restore_sent = False
            state = self.recovery
            payload = {
                "uri": state["uri"],
                "context_uri": state["context_uri"],
                "position_ms": max(0, round(state["position_s"] * 1000)),
                "playing": state["status"] == "Playing",
                "volume": round(state["volume"] * 65535),
                "shuffle": state["shuffle"],
                "repeat_mode": state["repeat_mode"],
            }
            try:
                if self.event_callback is not None:
                    self.event_callback({"PLAYER_EVENT": "load_requested", "URI": state["uri"]})
                response = self.request("restore " + json.dumps(payload))
                if response != "ok":
                    raise RuntimeError(response or "Playback recovery failed")
            except (RuntimeError, OSError) as error:
                print(f"player recovery failed; will retry: {error}", file=sys.stderr)
                return
            # Keep the checkpoint until a real playback event confirms the load.
            self.restore_sent = True
            self.restore_requested_at = time.monotonic()
            self.restore_attempts += 1
            print("requested last-track recovery; waiting for playback confirmation")

    def _spawn(self) -> None:
        # A new player has no loaded track, even if the daemon survived.
        if self.event_callback is not None:
            self.event_callback({"PLAYER_EVENT": "player_reset"})
        self.login_url = ""
        cache_path = Path(self.config.player_cache)
        command = [str(PLAYER_BINARY_PATH)]
        environment = dict(os.environ)
        environment.update({
            "SPOTIFIER_DEVICE_NAME": self.config.device_name,
            "SPOTIFIER_CACHE": str(cache_path),
            "SPOTIFIER_CONTROL_SOCKET": str(CONTROL_SOCKET_PATH),
            "SPOTIFIER_EVENT_SOCKET": str(EVENT_SOCKET_PATH),
            "SPOTIFIER_ZEROCONF_PORT": str(self.config.librespot_zeroconf_port),
        })
        self.process = subprocess.Popen(
            command,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            bufsize=1,
            env=environment,
        )
        RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
        LIBRESPOT_PID_PATH.write_text(f"{self.process.pid}\n")
        threading.Thread(target=self._capture_output, name="librespot-output", daemon=True).start()
        print("started:", " ".join(command))
        if self.event_callback is not None:
            self.event_callback({"PLAYER_EVENT": "service_changed"})

    def _start_event_listener(self) -> None:
        RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
        EVENT_SOCKET_PATH.unlink(missing_ok=True)
        event_socket = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        event_socket.bind(str(EVENT_SOCKET_PATH))
        event_socket.settimeout(0.5)
        self.event_socket = event_socket
        self.event_thread = threading.Thread(target=self._capture_events, name="librespot-events", daemon=True)
        self.event_thread.start()

    def _capture_events(self) -> None:
        while not self.stopping.is_set():
            event_socket = self.event_socket
            if event_socket is None:
                return
            try:
                payload = event_socket.recv(65536)
            except TimeoutError:
                continue
            except OSError:
                return
            try:
                event = {str(key): str(value) for key, value in json.loads(payload).items()}
                self._handle_event(event)
            except (json.JSONDecodeError, TypeError, ValueError) as error:
                print(f"invalid librespot event: {error}", file=sys.stderr)

    def _handle_event(self, event: dict[str, str]) -> None:
        with self.load_lock:
            if event.get("PLAYER_EVENT") in ("stopped", "session_disconnected"):
                print(f"player event: {event['PLAYER_EVENT']}; retaining last track")
            if self.event_callback is not None:
                self.event_callback(event)
            if self.recovery is not None and self.restore_sent:
                expected = "playing" if self.recovery["status"] == "Playing" else "paused"
                if (event.get("PLAYER_EVENT") == expected
                        and event.get("TRACK_ID") == self.recovery["uri"].rsplit(":", 1)[-1]):
                    # Activation emits the device's old default settings before
                    # LoadRequest applies the saved options, without new option events.
                    # A matching playback event confirms that load has completed.
                    saved = self.recovery
                    self.context_uri = saved["context_uri"]
                    if self.event_callback is not None:
                        self.event_callback({"PLAYER_EVENT": "context_changed", "CONTEXT_URI": self.context_uri})
                        self.event_callback({"PLAYER_EVENT": "shuffle_changed", "SHUFFLE": str(saved["shuffle"]).lower()})
                        self.event_callback({"PLAYER_EVENT": "repeat_changed",
                            "REPEAT": str(saved["repeat_mode"] == "Playlist").lower(),
                            "REPEAT_TRACK": str(saved["repeat_mode"] == "Track").lower()})
                    print("last-track recovery confirmed with context, shuffle and repeat")
                    self.recovery = None
            if event.get("PLAYER_EVENT") in (
                "track_changed", "playing", "paused", "seeked", "position_correction",
                "volume_changed", "shuffle_changed", "repeat_changed", "stopped", "session_disconnected",
            ):
                self._save_checkpoint()

    def _capture_output(self) -> None:
        process = self.process
        if not process or not process.stdout:
            return
        for line in process.stdout:
            line = line.rstrip()
            print(line)
            self.last_lines = (self.last_lines + [line])[-30:]
            if line.startswith("spotifier-player ready:") and process is self.process:
                self.player_ready = True
                self._restore_playback()
            match = re.search(r"Browse to:\s*(https?://\S+)", line)
            if match:
                self.login_url = match.group(1)
                if self.event_callback is not None:
                    self.event_callback({"PLAYER_EVENT": "service_changed"})

    def _monitor(self) -> None:
        while not self.stopping.wait(2):
            if self.process is not None and self.process.poll() is not None:
                self._remember_playback()
                if self.event_callback is not None:
                    self.event_callback({"PLAYER_EVENT": "player_reset"})
                print("librespot exited; restarting in 3s", file=sys.stderr)
                if self.stopping.wait(3):
                    return
                self._terminate_stale_process()
                self._spawn()
            elif self.player_ready:
                self._restore_playback()

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
