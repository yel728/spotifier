from __future__ import annotations

import json
import signal
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from .config import Config
from .library import Library
from .lyrics import Lyrics
from .oauth import SpotifyPlayerOAuth
from .playback import EventPlaybackState, LibrespotSupervisor
from .spotify import SpotifyAPI


class ApiError(RuntimeError):
    def __init__(self, code: str, message: str, status: int = 400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


class Application:
    def __init__(self, config: Config):
        self.config = config
        self.oauth = SpotifyPlayerOAuth()
        self.spotify = SpotifyAPI(config, self.oauth)
        self.library = Library(self.spotify)
        self.playback = EventPlaybackState()
        self.librespot = LibrespotSupervisor(config, self.playback.apply)
        self.lyrics = Lyrics(spotify_fetcher=self.librespot.lyrics)

    def start(self) -> None:
        self.librespot.start()

    def close(self) -> None:
        self.librespot.stop()
        self.oauth.close()
        self.library.close()

    def invalidate(self) -> None:
        self.spotify.invalidate()
        self.library.invalidate()
        self.lyrics.invalidate()

    def status(self) -> dict[str, Any]:
        return self._decorate_status(self.playback.snapshot())

    def wait_status(self, version: int, timeout: float) -> tuple[int, dict[str, Any] | None]:
        version, state = self.playback.wait(version, timeout)
        return version, self._decorate_status(state) if state is not None else None

    def _decorate_status(self, state: dict[str, Any]) -> dict[str, Any]:
        logged_in = self.oauth.logged_in
        state.update({
            "online": True,
            "logged_in": logged_in,
            "library_logged_in": logged_in,
            "device_name": self.config.device_name,
            "streaming_ready": self.librespot.running,
            "streaming_login_url": self.librespot.login_url,
        })
        return state

    def logout(self) -> None:
        self.oauth.logout()
        self.librespot.reset_credentials()
        self.invalidate()

    def play_pause(self) -> None:
        self.librespot.command("play_pause")


class Handler(BaseHTTPRequestHandler):
    app: Application

    def log_message(self, format: str, *args: Any) -> None:
        print(f"{self.address_string()} - {format % args}")

    def do_OPTIONS(self) -> None:
        self._send(204, b"", "text/plain")

    def do_GET(self) -> None:
        if urllib.parse.urlparse(self.path).path == "/api/events":
            self._events()
            return
        try:
            response = self._route_get()
            if response is not None:
                self._send(*response)
        except ApiError as error:
            self._error(error)
        except Exception as error:
            self._error(ApiError("internal_error", str(error), 500))

    def do_POST(self) -> None:
        try:
            self._send(*self._route_post())
        except ApiError as error:
            self._error(error)
        except Exception as error:
            self._error(ApiError("internal_error", str(error), 500))

    def _events(self) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        version = -1
        try:
            while True:
                version, state = self.app.wait_status(version, 25)
                payload = b"\n" if state is None else json.dumps(state).encode() + b"\n"
                self.wfile.write(payload)
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            return

    def _route_get(self) -> tuple[int, bytes, str] | None:
        url = urllib.parse.urlparse(self.path)
        query = urllib.parse.parse_qs(url.query)
        app = self.app
        if url.path == "/":
            return self._text("Spotifier daemon\n")
        if url.path == "/api/health":
            return self._json({"ok": True, "version": "0.2.0"})
        if url.path == "/api/status":
            return self._json(app.status())
        if url.path == "/auth/login":
            location = app.oauth.login_url()
            if not location:
                return self._text("Login is already complete. You can close this tab.\n")
            self.send_response(302)
            self.send_header("Location", location)
            self.end_headers()
            return None
        if url.path == "/api/playlists":
            return self._json({"items": app.library.playlists()})
        if url.path == "/api/playlist_tracks":
            uri = query.get("uri", [""])[0]
            if not uri:
                raise ApiError("playlist_missing", "A playlist URI is required")
            if query.get("cached", ["0"])[0] == "1":
                items, art_pending, refreshing, version = app.library.cached_tracks(uri)
            else:
                items, art_pending, refreshing, version = app.library.tracks(uri)
            return self._json({
                "items": items,
                "art_pending": art_pending,
                "refreshing": refreshing,
                "version": version,
            })
        if url.path == "/api/search":
            value = query.get("q", [""])[0].strip()
            if not value:
                raise ApiError("query_missing", "A search query is required")
            return self._json({"items": app.library.search(value)})
        if url.path == "/api/lyrics":
            track = query.get("track", [""])[0].strip()
            artist = query.get("artist", [""])[0].strip()
            if not track or not artist:
                raise ApiError("track_missing", "Track and artist are required")
            album = query.get("album", [""])[0].strip()
            try:
                duration = float(query.get("duration", ["0"])[0])
            except ValueError as error:
                raise ApiError("duration_invalid", "Duration must be a number") from error
            track_uri = query.get("uri", [""])[0].strip()
            return self._json(app.lyrics.get(track, artist, album, duration, track_uri))
        if url.path == "/api/devices":
            return self._json({"items": app.spotify.devices()})
        raise ApiError("not_found", "Endpoint not found", 404)

    def _route_post(self) -> tuple[int, bytes, str]:
        url = urllib.parse.urlparse(self.path)
        payload = self._payload()
        app = self.app
        if url.path == "/auth/logout":
            self.app.logout()
        elif url.path == "/api/play":
            uri = str(payload.get("uri") or "")
            context_uri = str(payload.get("context_uri") or "")
            if not uri.startswith("spotify:"):
                raise ApiError("uri_invalid", "A Spotify URI is required")
            if context_uri and not context_uri.startswith("spotify:"):
                raise ApiError("context_uri_invalid", "context_uri must be a Spotify URI")
            app.librespot.load(uri, context_uri)
        elif url.path == "/api/playpause":
            self.app.play_pause()
        elif url.path in ("/api/pause", "/api/stop"):
            app.librespot.command("pause")
        elif url.path == "/api/resume":
            app.librespot.command("play")
        elif url.path == "/api/next":
            app.librespot.command("next")
        elif url.path == "/api/previous":
            app.librespot.command("previous")
        elif url.path == "/api/seek":
            app.librespot.command(f"seek {round(self._number(payload, 'position', minimum=0) * 1000)}")
        elif url.path == "/api/volume":
            app.librespot.command(f"volume {round(self._number(payload, 'volume', minimum=0, maximum=1) * 65535)}")
        elif url.path == "/api/shuffle":
            enabled = payload.get("enabled")
            if not isinstance(enabled, bool):
                raise ApiError("shuffle_invalid", "enabled must be boolean")
            app.librespot.command(f"shuffle {str(enabled).lower()}")
        elif url.path == "/api/repeat":
            mode = payload.get("mode")
            if mode not in ("None", "Playlist", "Track"):
                raise ApiError("repeat_invalid", "mode must be None, Playlist, or Track")
            app.librespot.command(f"repeat_mode {mode}")
        else:
            raise ApiError("not_found", "Endpoint not found", 404)
        return self._json({"ok": True})

    def _payload(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0") or 0)
        try:
            return json.loads(self.rfile.read(length) if length else b"{}")
        except json.JSONDecodeError as error:
            raise ApiError("json_invalid", "Request body must be valid JSON") from error

    @staticmethod
    def _number(payload: dict[str, Any], key: str, minimum: float, maximum: float | None = None) -> float:
        try:
            value = float(payload[key])
        except (KeyError, TypeError, ValueError) as error:
            raise ApiError(f"{key}_invalid", f"{key} must be a number") from error
        if value < minimum or maximum is not None and value > maximum:
            raise ApiError(f"{key}_invalid", f"{key} is outside the allowed range")
        return value

    def _error(self, error: ApiError) -> None:
        self._send(*self._json({"error": {"code": error.code, "message": error.message}}, error.status))

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        if body:
            self.wfile.write(body)

    @staticmethod
    def _json(value: Any, status: int = 200) -> tuple[int, bytes, str]:
        return status, (json.dumps(value) + "\n").encode(), "application/json"

    @staticmethod
    def _text(value: str, status: int = 200) -> tuple[int, bytes, str]:
        return status, value.encode(), "text/plain"


def run(config: Config) -> None:
    app = Application(config)
    app.start()
    Handler.app = app
    server = ThreadingHTTPServer((config.host, config.port), Handler)

    def stop(_signum: int, _frame: Any) -> None:
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    print(f"spotifierd listening on http://{config.host}:{config.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        app.close()
