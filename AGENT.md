# AGENT.md

## Purpose

Spotifier is a personal Spotify desktop client for Omarchy/Hyprland. It combines a Python daemon, one supervised `librespot` streaming device, Spotify Web API control, read-only `spotify_player` library access, and an Omarchy QuickShell plugin.

Read `plan.md` before architectural or product changes.

## Repository layout

```text
spotifierd/
  __main__.py       python -m spotifierd entry point
  main.py           single-instance process lock and startup
  server.py         HTTP API, routes, structured errors, shutdown
  playback.py       librespot lifecycle and Web API state normalization
  library.py        playlists, tracks, search, artwork cache/enrichment
  lyrics.py         LRCLIB lookup and synchronized lyric parsing
  spotify.py        Spotify Web API and read-only spotify_player commands
  oauth.py          Spotify OAuth PKCE/token persistence
  config.py         machine-local paths and defaults

quickshell/omarchy-plugin/
  manifest.json
  Service.qml       API client and frontend state machine
  BarWidget.qml     bar widget and popup UI

systemd/spotifierd.service.in
scripts/install-service.sh
scripts/install-omarchy-plugin.sh
```

## Machine-local state

Never commit these paths:

```text
~/.config/spotifier/config.json
~/.config/spotifier/token.json
~/.cache/spotifier/
~/.cache/spotify-player/
~/.config/systemd/user/spotifierd.service
~/.config/omarchy/plugins/yel728.spotifier
```

The repository plugin is symlinked from:

```text
~/.config/omarchy/plugins/yel728.spotifier
```

## Authoritative architecture

There is exactly one playback session design:

1. `spotifierd.service` owns exactly one `spotifierd` process.
2. `spotifierd` owns exactly one `librespot` child named `Spotifier`.
3. systemd `KillMode=control-group` and `LibrespotSupervisor.stop()` terminate the entire process tree.
4. Spotify Web API is the only playback-state and transport authority.
5. Every playback mutation includes the exact `Spotifier` device ID.
6. `spotify_player` is read-only and used only for playlist discovery and playlist contents.
7. MPRIS/playerctl is not part of the playback control path.

Do not add fallback playback commands. Multiple control authorities caused duplicate sessions and audio that could not be stopped.

## Cache invariants

- Use `TTLCache` from `spotifierd/cache.py`; do not introduce a second cache implementation.
- Playback TTL is 1.8 seconds while playing and 4 seconds while paused or idle.
- Extrapolate cached playing position from monotonic cache age.
- Every successful playback mutation clears playback state and bypasses caching for five seconds so Spotify's eventually consistent response cannot be cached as current state.
- Cache devices for 30 seconds; invalidate them after command failure and force-refresh once when the configured device is absent.
- Cache the playlist index for 5 minutes and normalized search queries for 2 minutes. Persist up to 24 playlist and album track snapshots, serve them immediately, refresh them in the background on access, and rewrite storage only when normalized content changes.
- Cache found lyrics for 24 hours and negative lyric results for 15 minutes.
- OAuth completion invalidates playback, devices, library, search, and lyrics.
- All variable-key caches must remain bounded.

## Backend source rules

Use `spotify_player` only for:

```sh
spotify_player get key user-playlists
spotify_player get item playlist --id ID
```

The public Spotify playlist-items endpoint returns HTTP 403 for this account/app. Never silently replace a `spotify_player` playlist error with that known-forbidden endpoint.

Use Spotify Web API for:

- OAuth;
- playback state;
- play, pause/stop, next, previous, seek, volume, shuffle, repeat;
- exact local-device selection;
- search;
- playlist images and supplemental metadata.

`spotify_player` cache corruption can produce `expected u8` parsing errors. Back up and regenerate `~/.cache/spotify-player/Playlists_cache.json`; do not delete credentials or the whole cache.

## Process lifecycle

Install and start the daemon:

```sh
./scripts/install-service.sh
```

Inspect it:

```sh
systemctl --user status spotifierd.service
journalctl --user -u spotifierd.service -n 100 --no-pager
```

Restart it:

```sh
systemctl --user restart spotifierd.service
```

After any lifecycle change, confirm the cgroup contains one Python process and one `librespot` child. Never launch the daemon with `nohup` or a second shell process.

Foreground development is allowed only after stopping the user service:

```sh
systemctl --user stop spotifierd.service
python -m spotifierd
```

## Frontend conventions

Use Omarchy components and theme values:

```qml
import qs.Ui
import qs.Commons
```

Prefer `BarWidget`, `PopupCard`, `BorderSurface`, `Button`, `PanelSlider`, `Style`, and `Color`.

The popup owner is the bar widget. `PopupCard` handles outside clicks; Escape is handled explicitly by `BarWidget.qml`.

QML arrays are exposed to `ListView` through integer models:

```qml
property var items: service.items
model: items.length
```

Delegates resolve data through `ListView.view.items[index]`. Preserve this pattern.

For bodyless requests, call `xhr.send()` with no argument. `xhr.send(undefined)` is serialized as an invalid body by this QuickShell runtime and breaks transport controls.

Panel shortcuts use `Qt.ApplicationShortcut` and are enabled only while the popup is open. Letter, number, arrow, and Space shortcuts must remain disabled while `searchInput` has focus; Escape and `Ctrl+F` remain active.

## Current API

```text
GET  /api/health
GET  /api/status
GET  /api/playlists
GET  /api/playlist_tracks?uri=spotify:playlist:...
GET  /api/playlist_tracks?cached=1&uri=spotify:playlist:...
GET  /api/search?q=...
GET  /api/lyrics?track=...&artist=...&album=...&duration=...
GET  /api/devices
POST /api/play       {"uri":"spotify:...","context_uri":"spotify:playlist:..."}
POST /api/playpause
POST /api/pause
POST /api/stop
POST /api/previous
POST /api/next
POST /api/seek       {"position":42.5}
POST /api/volume     {"volume":0.5}
POST /api/shuffle    {"enabled":true}
POST /api/repeat     {"mode":"None|Playlist|Track"}
GET  /auth/login
GET  /auth/callback
```

Errors use:

```json
{"error":{"code":"stable_code","message":"Readable explanation"}}
```

## Validation

Backend changes:

```sh
python -m compileall spotifierd
python -m unittest discover -s tests
systemctl --user restart spotifierd.service
curl -sS http://127.0.0.1:8765/api/health
curl -sS http://127.0.0.1:8765/api/status
```

Frontend changes:

```sh
omarchy restart shell
pid=$(pgrep -f 'quickshell -n -p /usr/share/omarchy/shell' | head -1)
quickshell ipc --pid "$pid" call spotifier state
```

Also inspect the current QuickShell log for `BarWidget.qml`, `Service.qml`, `TypeError`, and `ReferenceError`.

## Required behavioral checks

For playback changes:

1. Start a real track through `POST /api/play`.
2. Confirm `/api/status` says `Playing`.
3. Trigger the panel play/pause control or click the widget track information.
4. Confirm `/api/status` changes between `Playing` and `Paused`.
5. Restart `spotifierd.service` and confirm exactly one `librespot` child remains.

For library changes:

- confirm playlist count;
- load a playlist with hundreds of tracks;
- verify cached artwork refresh;
- confirm no internal fields reach JSON.

## Known host warning

Omarchy currently logs:

```text
TypeError: Cannot assign to read-only property "moduleName"
```

This comes from the packaged bar host. The Spotifier widget loads correctly. Never edit `/usr/share/omarchy` to suppress it.
