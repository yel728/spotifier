from __future__ import annotations

import json
import re
import threading
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from .cache import TTLCache

LRCLIB_API = "https://lrclib.net/api/get"
LRCLIB_USER_AGENT = "Spotifier/0.2 (personal Linux desktop client)"


def parse_synced_lyrics(raw: str) -> list[dict[str, Any]]:
    lines: list[dict[str, Any]] = []
    timestamp = re.compile(r"\[(\d{1,3}):(\d{2}(?:\.\d{1,3})?)\]")
    for raw_line in raw.splitlines():
        matches = list(timestamp.finditer(raw_line))
        if not matches:
            continue
        text = raw_line[matches[-1].end():].strip()
        for match in matches:
            lines.append({
                "time": int(match.group(1)) * 60 + float(match.group(2)),
                "text": text,
            })
    lines.sort(key=lambda line: line["time"])
    return lines


class Lyrics:
    def __init__(self):
        self.cache: TTLCache[tuple[str, str, str, int], dict[str, Any]] = TTLCache(256)
        self.lock = threading.Lock()

    def get(self, track: str, artist: str, album: str, duration: float) -> dict[str, Any]:
        key = (track.casefold(), artist.casefold(), album.casefold(), round(duration))
        with self.lock:
            cached = self.cache.get(key)
            if cached is not None:
                return cached.value
            result = self._fetch(track, artist, album, duration)
            ttl = 86400.0 if result.get("found") else 900.0
            self.cache.set(key, result, ttl)
            return result


    def invalidate(self) -> None:
        with self.lock:
            self.cache.clear()

    @staticmethod
    def _fetch(track: str, artist: str, album: str, duration: float) -> dict[str, Any]:
        query: dict[str, str | int] = {
            "track_name": track,
            "artist_name": artist,
        }
        if album:
            query["album_name"] = album
        if 1 <= duration <= 3600:
            query["duration"] = round(duration)
        request = urllib.request.Request(
            LRCLIB_API + "?" + urllib.parse.urlencode(query),
            headers={"User-Agent": LRCLIB_USER_AGENT},
        )
        try:
            with urllib.request.urlopen(request, timeout=8) as response:
                data = json.loads(response.read())
        except urllib.error.HTTPError as error:
            if error.code == 404:
                return {"found": False, "instrumental": False, "plain": "", "lines": []}
            raise
        return {
            "found": True,
            "instrumental": bool(data.get("instrumental")),
            "plain": data.get("plainLyrics") or "",
            "lines": parse_synced_lyrics(data.get("syncedLyrics") or ""),
        }
