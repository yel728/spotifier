from __future__ import annotations

from contextlib import closing
import json
import os
import re
import sqlite3
import threading
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable

from .cache import TTLCache

LRCLIB_API = "https://lrclib.net/api/get"
LRCLIB_SEARCH_API = "https://lrclib.net/api/search"
LRCLIB_USER_AGENT = "Spotifier/0.4 (https://github.com/yel728/spotifier)"
LYRICS_DB_PATH = (
    Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share"))
    / "spotifier/lyrics.sqlite3"
)


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


def normalized(value: str) -> str:
    return "".join(
        character
        for character in unicodedata.normalize("NFKC", value).casefold()
        if character.isalnum()
    )


def artist_names(value: str) -> set[str]:
    parts = re.split(r"\s*(?:,|，|、|&|/|;|\bfeat\.?\b|\bft\.?\b)\s*", value, flags=re.IGNORECASE)
    return {normalized(part) for part in parts if normalized(part)}


def best_synced_candidate(
    candidates: list[dict[str, Any]],
    track: str,
    artist: str,
    album: str,
    duration: float,
) -> dict[str, Any] | None:
    track_key = normalized(track)
    requested_artists = artist_names(artist)
    album_key = normalized(album)
    ranked: list[tuple[tuple[int, int, int, float], dict[str, Any]]] = []
    for candidate in candidates:
        synced = candidate.get("syncedLyrics") or ""
        candidate_track = str(candidate.get("trackName") or candidate.get("name") or "")
        if not synced or normalized(candidate_track) != track_key:
            continue
        candidate_artists = artist_names(str(candidate.get("artistName") or ""))
        artist_match = bool(requested_artists.intersection(candidate_artists))
        candidate_album = normalized(str(candidate.get("albumName") or ""))
        album_match = bool(album_key) and candidate_album == album_key
        if not artist_match and not album_match:
            continue
        candidate_duration = float(candidate.get("duration") or 0)
        difference = abs(candidate_duration - duration) if candidate_duration and duration else 0.0
        if candidate_duration and duration and difference > 4:
            continue
        score = (
            int(artist_match),
            int(album_match),
            int(normalized(str(candidate.get("artistName") or "")) == normalized(artist)),
            -difference,
        )
        ranked.append((score, candidate))
    return max(ranked, key=lambda item: item[0])[1] if ranked else None


class Lyrics:
    def __init__(
        self,
        db_path: Path = LYRICS_DB_PATH,
        spotify_fetcher: Callable[[str], dict[str, Any]] | None = None,
    ):
        self.db_path = db_path
        self.spotify_fetcher = spotify_fetcher
        self.cache: TTLCache[str, dict[str, Any]] = TTLCache(256)
        self.lock = threading.Lock()
        self._initialize_database()

    def get(
        self,
        track: str,
        artist: str,
        album: str,
        duration: float,
        track_uri: str = "",
    ) -> dict[str, Any]:
        key = track_uri or "\0".join(
            (track.casefold(), artist.casefold(), album.casefold(), str(round(duration)))
        )
        with self.lock:
            cached = self.cache.get(key)
            if cached is not None:
                return cached.value
            stored = self._stored(key)
            if stored is not None:
                self.cache.set(key, stored, 86400.0)
                return stored
            result = self._fetch(track, artist, album, duration, track_uri)
            if result.get("lines"):
                self._store(key, track, artist, album, duration, result)
            public = self._public(result)
            self.cache.set(key, public, 86400.0 if public.get("lines") else 900.0)
            return public

    def invalidate(self) -> None:
        with self.lock:
            self.cache.clear()

    def _fetch(
        self,
        track: str,
        artist: str,
        album: str,
        duration: float,
        track_uri: str,
    ) -> dict[str, Any]:
        spotify = self._fetch_spotify(track_uri) if track_uri else self._empty()
        if spotify.get("lines"):
            return spotify
        lrclib = self._fetch_lrclib(track, artist, album, duration)
        if lrclib.get("lines"):
            return lrclib
        if spotify.get("found"):
            return spotify
        return lrclib

    def _fetch_spotify(self, track_uri: str) -> dict[str, Any]:
        if self.spotify_fetcher is None:
            return self._empty()
        try:
            data = self.spotify_fetcher(track_uri)
        except (OSError, RuntimeError, ValueError):
            return self._empty()
        raw_lines = data.get("lines") or []
        plain = "\n".join(str(line.get("text") or "") for line in raw_lines).strip()
        synced = bool(data.get("synced"))
        lines = [
            {
                "time": float(line.get("time_ms") or 0) / 1000,
                "text": str(line.get("text") or ""),
            }
            for line in raw_lines
        ] if synced else []
        lrc = "\n".join(
            f"[{int(line['time'] // 60):02d}:{line['time'] % 60:06.3f}]{line['text']}"
            for line in lines
        )
        return {
            "found": bool(plain),
            "instrumental": False,
            "plain": plain,
            "lines": lines,
            "synced": lrc,
            "source": "spotify",
        }

    @staticmethod
    def _fetch_lrclib(track: str, artist: str, album: str, duration: float) -> dict[str, Any]:
        query: dict[str, str | int] = {
            "track_name": track,
            "artist_name": artist,
            "album_name": album,
            "duration": round(duration),
        }
        exact: dict[str, Any] | None
        try:
            exact = Lyrics._lrclib_request(LRCLIB_API, query)
        except urllib.error.HTTPError as error:
            if error.code != 404:
                raise
            error.close()
            exact = None
        if exact and (exact.get("syncedLyrics") or exact.get("instrumental")):
            return Lyrics._lrclib_result(exact)

        time.sleep(0.25)
        candidates = Lyrics._lrclib_request(
            LRCLIB_SEARCH_API,
            {"track_name": track},
        )
        candidate = best_synced_candidate(candidates, track, artist, album, duration)
        if candidate is not None:
            return Lyrics._lrclib_result(candidate)
        return Lyrics._lrclib_result(exact) if exact else Lyrics._empty()

    @staticmethod
    def _lrclib_request(url: str, query: dict[str, str | int]) -> Any:
        request = urllib.request.Request(
            url + "?" + urllib.parse.urlencode(query),
            headers={"User-Agent": LRCLIB_USER_AGENT},
        )
        with urllib.request.urlopen(request, timeout=10) as response:
            return json.loads(response.read())

    @staticmethod
    def _lrclib_result(data: dict[str, Any]) -> dict[str, Any]:
        synced = data.get("syncedLyrics") or ""
        return {
            "found": bool(
                synced or data.get("plainLyrics") or data.get("instrumental")
            ),
            "instrumental": bool(data.get("instrumental")),
            "plain": data.get("plainLyrics") or "",
            "lines": parse_synced_lyrics(synced),
            "synced": synced,
            "source": "lrclib",
        }
    def _initialize_database(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.db_path)) as database, database:
            database.execute("""
                CREATE TABLE IF NOT EXISTS synced_lyrics (
                    track_key TEXT PRIMARY KEY,
                    track TEXT NOT NULL,
                    artist TEXT NOT NULL,
                    album TEXT NOT NULL,
                    duration INTEGER NOT NULL,
                    source TEXT NOT NULL,
                    plain TEXT NOT NULL,
                    synced TEXT NOT NULL,
                    stored_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
            """)

    def _stored(self, key: str) -> dict[str, Any] | None:
        with closing(sqlite3.connect(self.db_path)) as database:
            row = database.execute(
                "SELECT source, plain, synced FROM synced_lyrics WHERE track_key = ?",
                (key,),
            ).fetchone()
        if row is None:
            return None
        source, plain, synced = row
        return {
            "found": True,
            "instrumental": False,
            "plain": plain,
            "lines": parse_synced_lyrics(synced),
            "source": source,
        }

    def _store(
        self,
        key: str,
        track: str,
        artist: str,
        album: str,
        duration: float,
        result: dict[str, Any],
    ) -> None:
        synced = str(result.get("synced") or "")
        if not synced:
            return
        with closing(sqlite3.connect(self.db_path)) as database, database:
            database.execute(
                """
                INSERT INTO synced_lyrics
                    (track_key, track, artist, album, duration, source, plain, synced)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(track_key) DO UPDATE SET
                    track = excluded.track,
                    artist = excluded.artist,
                    album = excluded.album,
                    duration = excluded.duration,
                    source = excluded.source,
                    plain = excluded.plain,
                    synced = excluded.synced,
                    stored_at = CURRENT_TIMESTAMP
                """,
                (
                    key,
                    track,
                    artist,
                    album,
                    round(duration),
                    result.get("source") or "",
                    result.get("plain") or "",
                    synced,
                ),
            )

    @staticmethod
    def _public(result: dict[str, Any]) -> dict[str, Any]:
        return {
            "found": bool(result.get("found")),
            "instrumental": bool(result.get("instrumental")),
            "plain": result.get("plain") or "",
            "lines": result.get("lines") or [],
            "source": result.get("source") or "",
        }

    @staticmethod
    def _empty() -> dict[str, Any]:
        return {
            "found": False,
            "instrumental": False,
            "plain": "",
            "lines": [],
            "synced": "",
            "source": "",
        }
