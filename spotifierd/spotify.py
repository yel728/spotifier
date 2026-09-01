from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any
from threading import Lock

from .cache import TTLCache

from .config import Config
from .oauth import SpotifyPlayerOAuth

API = "https://api.spotify.com/v1"




def spotify_id(uri: str) -> str:
    if uri.startswith("spotify:"):
        return uri.split(":")[-1]
    return uri.rstrip("/").split("/")[-1].split("?", 1)[0]


class SpotifyAPI:
    def __init__(self, cfg: Config, oauth: SpotifyPlayerOAuth | None = None):
        self.cfg = cfg
        self.oauth = oauth or SpotifyPlayerOAuth()
        self._playback_cache: TTLCache[str, dict[str, Any] | None] = TTLCache(1)
        self._devices_cache: TTLCache[str, list[dict[str, Any]]] = TTLCache(1)
        self._playback_lock = Lock()
        self._devices_lock = Lock()
        self._playback_bypass_until = 0.0

    def request(self, method: str, path: str, body: dict[str, Any] | None = None) -> Any:
        token = self.oauth.token()
        if not token:
            raise PermissionError("Not logged in. Open /auth/login first.")
        payload = None if body is None else json.dumps(body).encode()
        request = urllib.request.Request(API + path, data=payload, method=method)
        request.add_header("Authorization", "Bearer " + token["access_token"])
        if body is not None:
            request.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(request, timeout=12) as response:
                raw = response.read()
                return None if method != "GET" or not raw.strip() else json.loads(raw)
        except urllib.error.HTTPError as error:
            detail = error.read().decode(errors="replace")
            raise RuntimeError(f"Spotify API {error.code}: {detail}") from error

    def playlists(self) -> dict[str, Any]:
        return self.request("GET", "/me/playlists?limit=50")

    def playlist_tracks(self, playlist_id: str) -> dict[str, Any]:
        return self.request("GET", f"/playlists/{playlist_id}/tracks?limit=100")

    def player_request(self, url: str) -> dict[str, Any]:
        token = self.oauth.token()
        if not token:
            raise PermissionError("Playlist login is incomplete. Open /auth/login.")
        request = urllib.request.Request(url)
        request.add_header("Authorization", "Bearer " + token["access_token"])
        try:
            with urllib.request.urlopen(request, timeout=12) as response:
                return json.loads(response.read())
        except urllib.error.HTTPError as error:
            detail = error.read().decode(errors="replace")
            raise RuntimeError(f"Spotify playlist API {error.code}: {detail}") from error

    def player_playlists(self) -> list[dict[str, Any]]:
        url = API + "/me/playlists?limit=50"
        playlists: list[dict[str, Any]] = []
        while url:
            page = self.player_request(url)
            for item in page.get("items", []):
                if not item:
                    continue
                owner = item.get("owner") or {}
                playlists.append({
                    **item,
                    "owner": [owner.get("display_name") or owner.get("id") or "Playlist"],
                })
            url = str(page.get("next") or "")
        return playlists

    def player_playlist(self, playlist_id: str) -> dict[str, Any]:
        url = API + f"/playlists/{playlist_id}/tracks?limit=100"
        tracks: list[dict[str, Any]] = []
        while url:
            page = self.player_request(url)
            for item in page.get("items", []):
                track = (item or {}).get("track") or (item or {}).get("item")
                if track:
                    tracks.append(track)
            url = str(page.get("next") or "")
        return {"tracks": tracks}

    def tracks(self, ids: list[str]) -> dict[str, Any]:
        query = urllib.parse.urlencode({"ids": ",".join(ids)})
        return self.request("GET", "/tracks?" + query)

    def search(self, query: str) -> dict[str, Any]:
        params = urllib.parse.urlencode({
            "q": query,
            "type": "album,artist,playlist,track",
            "limit": 10,
        })
        return self.request("GET", "/search?" + params)

    def playback(self, force: bool = False) -> dict[str, Any] | None:
        bypass = time.monotonic() < self._playback_bypass_until
        if not force and not bypass:
            hit = self._playback_cache.get("current")
            if hit is not None:
                return self._aged_playback(hit.value, hit.age)
        with self._playback_lock:
            bypass = time.monotonic() < self._playback_bypass_until
            if not force and not bypass:
                hit = self._playback_cache.get("current")
                if hit is not None:
                    return self._aged_playback(hit.value, hit.age)
            playback = self.request("GET", "/me/player")
            if not bypass:
                ttl = 1.8 if playback and playback.get("is_playing") else 4.0
                self._playback_cache.set("current", playback, ttl)
            return playback

    def devices(self, force: bool = False) -> list[dict[str, Any]]:
        if not force:
            hit = self._devices_cache.get("all")
            if hit is not None:
                return hit.value
        with self._devices_lock:
            if not force:
                hit = self._devices_cache.get("all")
                if hit is not None:
                    return hit.value
            data = self.request("GET", "/me/player/devices")
            devices = data.get("devices", [])
            self._devices_cache.set("all", devices, 30.0)
            return devices

    def local_device_id(self) -> str:
        for force in (False, True):
            for device in self.devices(force=force):
                if device.get("name") == self.cfg.device_name:
                    return str(device["id"])
        raise RuntimeError(f'Spotify device "{self.cfg.device_name}" is not available')

    def play_uri(self, uri: str, context_uri: str | None = None) -> None:
        device_id = self.local_device_id()
        query = "?" + urllib.parse.urlencode({"device_id": device_id})
        if context_uri:
            body = {"context_uri": context_uri, "offset": {"uri": uri}}
        else:
            body = {"uris": [uri]} if ":track:" in uri else {"context_uri": uri}
        self._mutation("PUT", "/me/player/play" + query, body)

    def pause(self) -> None:
        device_id = self.local_device_id()
        query = "?" + urllib.parse.urlencode({"device_id": device_id})
        self._mutation("PUT", "/me/player/pause" + query)

    def resume(self) -> None:
        device_id = self.local_device_id()
        query = "?" + urllib.parse.urlencode({"device_id": device_id})
        self._mutation("PUT", "/me/player/play" + query)

    def next(self) -> None:
        self._device_command("POST", "/me/player/next")

    def previous(self) -> None:
        self._device_command("POST", "/me/player/previous")

    def seek(self, position_seconds: float) -> None:
        self._device_command("PUT", "/me/player/seek", {"position_ms": round(position_seconds * 1000)})

    def set_volume(self, value: float) -> None:
        self._device_command("PUT", "/me/player/volume", {"volume_percent": round(value * 100)})

    def set_shuffle(self, enabled: bool) -> None:
        self._device_command("PUT", "/me/player/shuffle", {"state": str(enabled).lower()})

    def set_repeat(self, mode: str) -> None:
        state = {"None": "off", "Playlist": "context", "Track": "track"}[mode]
        self._device_command("PUT", "/me/player/repeat", {"state": state})

    def invalidate(self) -> None:
        with self._playback_lock:
            self._playback_cache.clear()
            self._playback_bypass_until = 0.0
        with self._devices_lock:
            self._devices_cache.clear()

    @staticmethod
    def _aged_playback(playback: dict[str, Any] | None, age: float) -> dict[str, Any] | None:
        if playback is None:
            return None
        result = dict(playback)
        if result.get("is_playing"):
            duration = int((result.get("item") or {}).get("duration_ms") or 0)
            progress = int(result.get("progress_ms") or 0) + round(age * 1000)
            result["progress_ms"] = min(progress, duration) if duration else progress
        return result

    def _mutation(self, method: str, path: str, body: dict[str, Any] | None = None) -> None:
        try:
            with self._playback_lock:
                if body is None:
                    self.request(method, path)
                else:
                    self.request(method, path, body)
                self._playback_cache.clear()
                self._playback_bypass_until = time.monotonic() + 5.0
        except Exception:
            self._devices_cache.clear()
            raise

    def _device_command(self, method: str, path: str, params: dict[str, Any] | None = None) -> None:
        query: dict[str, Any] = {"device_id": self.local_device_id()}
        if params:
            query.update(params)
        self._mutation(method, path + "?" + urllib.parse.urlencode(query))
