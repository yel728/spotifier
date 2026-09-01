from __future__ import annotations

import json
import threading
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any


from .cache import TTLCache
from .spotify import SpotifyAPI, spotify_id

ART_CACHE_PATH = Path.home() / ".cache/spotifier/art.json"
SPOTIFY_PLAYER_IMAGE_DIR = Path.home() / ".cache/spotify-player/image"


def best_image(images: list[dict[str, Any]] | None) -> str:
    if not images:
        return ""
    return str(images[-1].get("url") or images[0].get("url") or "")


def collection_kind(uri: str) -> str:
    return "album" if uri.startswith("spotify:album:") or "/album/" in uri else "playlist"


def collection_key(uri: str) -> str:
    return f"{collection_kind(uri)}:{spotify_id(uri)}"


class Library:
    def __init__(self, spotify: SpotifyAPI):
        self.spotify = spotify
        self.playlists_cache: TTLCache[str, list[dict[str, Any]]] = TTLCache(1)
        self.playlist_cache: TTLCache[str, list[dict[str, Any]]] = TTLCache(24)
        self.search_cache: TTLCache[str, list[dict[str, Any]]] = TTLCache(64)
        self.art_cache = self._load_art_cache()
        self.art_index = self._build_local_art_index()
        self.art_pending: set[str] = set()
        self.lock = threading.Lock()
        self.executor = ThreadPoolExecutor(max_workers=8, thread_name_prefix="spotifier-art")

    def playlists(self) -> list[dict[str, Any]]:
        cached = self.playlists_cache.get("all")
        if cached is not None:
            return cached.value
        raw = self.spotify.player_playlists()
        image_by_id: dict[str, str] = {}
        try:
            web = self.spotify.playlists()
            for item in web.get("items", []):
                if item and item.get("id"):
                    image_by_id[item["id"]] = best_image(item.get("images"))
        except Exception:
            pass
        result = []
        for item in raw:
            owner = item.get("owner") or []
            item_id = item.get("id", "")
            result.append({
                "type": "playlist",
                "name": item.get("name", ""),
                "subtitle": owner[0] if owner else "Playlist",
                "uri": "spotify:playlist:" + item_id,
                "image": image_by_id.get(item_id, ""),
            })
        self.playlists_cache.set("all", result, 300.0)
        return result

    def tracks(self, uri: str) -> tuple[list[dict[str, Any]], bool]:
        item_id = spotify_id(uri)
        cache_key = collection_key(uri)
        cached = self.playlist_cache.get(cache_key)
        if cached is not None:
            items = cached.value
            with self.lock:
                pending = any(item.get("album_id") in self.art_pending for item in items)
            return [self._public_track(item) for item in items], pending
        raw = self.spotify.player_album(item_id) if collection_kind(uri) == "album" else self.spotify.player_playlist(item_id)
        items: list[dict[str, Any]] = []
        missing: dict[str, str] = {}
        for track in raw.get("tracks", []):
            if not track:
                continue
            album = track.get("album") or {}
            album_id = album.get("id", "")
            image = best_image(album.get("images")) or self.art_cache.get(album_id, "") or self.art_index.get(album_id[:6], "")
            track_uri = track.get("uri", "") or "spotify:track:" + track.get("id", "")
            items.append({
                "type": "track",
                "name": track.get("name", ""),
                "subtitle": ", ".join(artist.get("name", "") for artist in track.get("artists", [])),
                "uri": track_uri,
                "image": image,
                "album_id": album_id,
            })
            if album_id and not image and album_id not in missing:
                missing[album_id] = track_uri
        self.playlist_cache.set(cache_key, items, 600.0)
        for album_id, track_uri in missing.items():
            self._schedule_art(album_id, track_uri)
        return [self._public_track(item) for item in items], bool(missing)

    def cached_tracks(self, uri: str) -> tuple[list[dict[str, Any]], bool]:
        cached = self.playlist_cache.get(collection_key(uri))
        if cached is None:
            return [], False
        items = cached.value
        with self.lock:
            pending = any(item.get("album_id") in self.art_pending for item in items)
        return [self._public_track(item) for item in items], pending

    def search(self, query: str) -> list[dict[str, Any]]:
        key = query.casefold().strip()
        cached = self.search_cache.get(key)
        if cached is not None:
            return cached.value
        raw = self.spotify.search(query)
        results: list[dict[str, Any]] = []
        for track in raw.get("tracks", {}).get("items", []):
            album = track.get("album") or {}
            results.append({
                "type": "track",
                "name": track.get("name", ""),
                "subtitle": ", ".join(artist.get("name", "") for artist in track.get("artists", [])),
                "uri": track.get("uri", ""),
                "context_uri": album.get("uri", ""),
                "image": best_image(album.get("images")),
            })
        for album in raw.get("albums", {}).get("items", []):
            results.append({
                "type": "album",
                "name": album.get("name", ""),
                "subtitle": ", ".join(artist.get("name", "") for artist in album.get("artists", [])),
                "uri": album.get("uri", ""),
                "image": best_image(album.get("images")),
            })
        for artist in raw.get("artists", {}).get("items", []):
            results.append({
                "type": "artist",
                "name": artist.get("name", ""),
                "subtitle": "Artist",
                "uri": artist.get("uri", ""),
                "image": best_image(artist.get("images")),
            })
        for playlist in raw.get("playlists", {}).get("items", []):
            if playlist:
                results.append({
                    "type": "playlist",
                    "name": playlist.get("name", ""),
                    "subtitle": "Playlist",
                    "uri": playlist.get("uri", ""),
                    "image": best_image(playlist.get("images")),
                })
        self.search_cache.set(key, results, 120.0)
        return results

    def close(self) -> None:
        self.executor.shutdown(wait=False, cancel_futures=True)

    def invalidate(self) -> None:
        self.playlists_cache.clear()
        self.playlist_cache.clear()
        self.search_cache.clear()

    def _schedule_art(self, album_id: str, track_uri: str) -> None:
        with self.lock:
            if album_id in self.art_pending:
                return
            self.art_pending.add(album_id)
        self.executor.submit(self._resolve_art, album_id, track_uri)

    def _resolve_art(self, album_id: str, track_uri: str) -> None:
        try:
            track_id = track_uri.rsplit(":", 1)[-1]
            url = "https://open.spotify.com/oembed?" + urllib.parse.urlencode({
                "url": f"https://open.spotify.com/track/{track_id}",
            })
            with urllib.request.urlopen(url, timeout=8) as response:
                image = json.loads(response.read()).get("thumbnail_url", "")
            if image:
                with self.lock:
                    self.art_cache[album_id] = image
                    for tracks in self.playlist_cache.values():
                        for item in tracks:
                            if item.get("album_id") == album_id:
                                item["image"] = image
                    self._save_art_cache()
        except Exception:
            pass
        finally:
            with self.lock:
                self.art_pending.discard(album_id)

    @staticmethod
    def _public_track(item: dict[str, Any]) -> dict[str, Any]:
        return {key: value for key, value in item.items() if key != "album_id"}

    @staticmethod
    def _load_art_cache() -> dict[str, str]:
        try:
            return json.loads(ART_CACHE_PATH.read_text())
        except Exception:
            return {}

    @staticmethod
    def _build_local_art_index() -> dict[str, str]:
        index: dict[str, str] = {}
        if not SPOTIFY_PLAYER_IMAGE_DIR.exists():
            return index
        for path in SPOTIFY_PLAYER_IMAGE_DIR.iterdir():
            marker = "-cover-"
            if marker not in path.name:
                continue
            prefix = path.name.rsplit(marker, 1)[-1].split(".", 1)[0]
            index[prefix] = path.resolve().as_uri()
        return index

    def _save_art_cache(self) -> None:
        ART_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        temporary = ART_CACHE_PATH.with_suffix(".tmp")
        temporary.write_text(json.dumps(self.art_cache) + "\n")
        temporary.replace(ART_CACHE_PATH)
