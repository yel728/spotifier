from __future__ import annotations

from datetime import datetime, timedelta, timezone

import json
import subprocess
import threading
import tomllib
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


TOKEN_URL = "https://accounts.spotify.com/api/token"
SPOTIFY_PLAYER_TOKEN = Path.home() / ".cache/spotify-player/user_client_token.json"
SPOTIFY_PLAYER_CONFIG = Path.home() / ".config/spotify-player/app.toml"


class SpotifyPlayerOAuth:
    def __init__(
        self,
        token_path: Path = SPOTIFY_PLAYER_TOKEN,
        config_path: Path = SPOTIFY_PLAYER_CONFIG,
    ):
        self.token_path = token_path
        self.config_path = config_path
        self.process: subprocess.Popen[str] | None = None
        self.url = ""
        self.lock = threading.Lock()

    @property
    def logged_in(self) -> bool:
        return self.token_path.exists()

    def login_url(self) -> str:
        if self.logged_in:
            return ""
        with self.lock:
            if self.process is not None and self.process.poll() is None and self.url:
                return self.url
            self.close()
            self.process = subprocess.Popen(
                ["spotify_player", "authenticate"],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
            assert self.process.stdout is not None
            line = self.process.stdout.readline().strip()
            prefix = "Browse to:"
            if not line.startswith(prefix):
                self.close()
                raise RuntimeError(f"spotify_player authentication failed: {line or 'no login URL'}")
            self.url = line.removeprefix(prefix).strip()
            return self.url

    def token(self) -> dict[str, Any] | None:
        if not self.token_path.exists():
            return None
        token: dict[str, Any] = json.loads(self.token_path.read_text())
        expires_at = str(token.get("expires_at") or "")
        try:
            expiry = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
        except ValueError:
            expiry = datetime.min.replace(tzinfo=timezone.utc)
        if expiry <= datetime.now(timezone.utc) + timedelta(seconds=30):
            token = self._refresh(token)
        return token

    def _refresh(self, token: dict[str, Any]) -> dict[str, Any]:
        refresh_token = token.get("refresh_token")
        if not refresh_token:
            raise RuntimeError("Playlist login expired; reconnect Spotify")
        config = tomllib.loads(self.config_path.read_text())
        data = urllib.parse.urlencode({
            "client_id": config["client_id"],
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        }).encode()
        request = urllib.request.Request(TOKEN_URL, data=data, method="POST")
        request.add_header("Content-Type", "application/x-www-form-urlencoded")
        with urllib.request.urlopen(request, timeout=20) as response:
            refreshed: dict[str, Any] = json.loads(response.read())
        refreshed.setdefault("refresh_token", refresh_token)
        refreshed["expires_at"] = (
            datetime.now(timezone.utc) + timedelta(seconds=int(refreshed.get("expires_in", 3600)))
        ).isoformat().replace("+00:00", "Z")
        self.token_path.write_text(json.dumps(refreshed, indent=2) + "\n")
        self.token_path.chmod(0o600)
        return refreshed

    def logout(self) -> None:
        self.close()
        self.token_path.unlink(missing_ok=True)

    def close(self) -> None:
        process = self.process
        self.process = None
        self.url = ""
        if process is None or process.poll() is not None:
            return
        process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=1)

