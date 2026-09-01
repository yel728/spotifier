from __future__ import annotations

from datetime import datetime, timedelta, timezone
import base64
import hashlib
import json
import secrets
import time
import urllib.parse
import subprocess
import threading
import tomllib
import urllib.request
from pathlib import Path
from typing import Any

from .config import Config, TOKEN_PATH

AUTH_URL = "https://accounts.spotify.com/authorize"
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


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


class OAuth:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.verifier: str | None = None
        self.state: str | None = None

    def login_url(self) -> str:
        self.verifier = _b64url(secrets.token_bytes(64))
        self.state = secrets.token_urlsafe(24)
        challenge = _b64url(hashlib.sha256(self.verifier.encode()).digest())
        params = {
            "client_id": self.cfg.client_id,
            "response_type": "code",
            "redirect_uri": self.cfg.redirect_uri,
            "code_challenge_method": "S256",
            "code_challenge": challenge,
            "state": self.state,
            "scope": " ".join(self.cfg.scopes),
        }
        return AUTH_URL + "?" + urllib.parse.urlencode(params)

    def exchange_code(self, code: str, state: str | None) -> dict[str, Any]:
        if self.state and state != self.state:
            raise ValueError("OAuth state mismatch")
        if not self.verifier:
            raise ValueError("No PKCE verifier; start at /auth/login first")
        data = urllib.parse.urlencode({
            "client_id": self.cfg.client_id,
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": self.cfg.redirect_uri,
            "code_verifier": self.verifier,
        }).encode()
        token = self._post_token(data)
        self._save_token(token)
        return token

    def token(self) -> dict[str, Any] | None:
        if not TOKEN_PATH.exists():
            return None
        token = json.loads(TOKEN_PATH.read_text())
        if token.get("expires_at", 0) <= time.time() + 30:
            token = self.refresh(token)
        return token

    def refresh(self, token: dict[str, Any]) -> dict[str, Any]:
        refresh_token = token.get("refresh_token")
        if not refresh_token:
            raise ValueError("Token expired and no refresh_token exists")
        data = urllib.parse.urlencode({
            "client_id": self.cfg.client_id,
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        }).encode()
        new_token = self._post_token(data)
        if "refresh_token" not in new_token:
            new_token["refresh_token"] = refresh_token
        self._save_token(new_token)
        return new_token

    def logout(self) -> None:
        TOKEN_PATH.unlink(missing_ok=True)

    def _post_token(self, data: bytes) -> dict[str, Any]:
        req = urllib.request.Request(TOKEN_URL, data=data, method="POST")
        req.add_header("Content-Type", "application/x-www-form-urlencoded")
        with urllib.request.urlopen(req, timeout=20) as resp:
            token = json.loads(resp.read())
        token["expires_at"] = time.time() + int(token.get("expires_in", 3600))
        return token

    def _save_token(self, token: dict[str, Any]) -> None:
        TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
        TOKEN_PATH.write_text(json.dumps(token, indent=2) + "\n")
        TOKEN_PATH.chmod(0o600)
