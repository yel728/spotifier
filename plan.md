# Spotifier Project Plan

## Vision

Spotifier is a personal, portable Spotify desktop client for Omarchy. It consists of one user-level backend service and one Omarchy shell plugin. The system must remain understandable, deterministic, and safe to restart.

## Product behavior

### Bar widget

- When there is no active track, show only a music icon.
- When Spotify has an active track, show artwork, title, artist, and playback state.
- Left click opens the panel.
- Right click toggles play/pause.
- Middle click and wheel navigate tracks.

### Panel

- Use Omarchy theme tokens and UI components.
- Present artwork, track metadata, connection status, progress, and volume in one clear hero section.
- Provide previous, play/pause, explicit stop, next, seek, shuffle, repeat, and volume controls.
- Disable transport controls when no track exists.
- Display backend errors instead of silently ignoring actions.
- Close on outside click or Escape.

### Library

- List all playlists with artwork and owner.
- Open complete playlists with hundreds of tracks.
- Play a playlist or individual track.
- Load cached artwork immediately and enrich missing artwork asynchronously.
- Never return internal cache fields to the frontend.

### Search

- Search tracks, albums, artists, and playlists.
- Show artwork and metadata.
- Play any compatible result on the local Spotifier device.

### Lyrics

- Use LRCLIB.
- Prefer synchronized lyrics and fall back to plain text.
- Follow playback position and center the current line.
- Show explicit loading, not-found, instrumental, and error states.

## Authoritative architecture

```text
Omarchy QuickShell plugin
  ├── BarWidget.qml
  └── Service.qml
          │ localhost HTTP/JSON
          ▼
spotifierd.service
  ├── server.py       HTTP routes and structured errors
  ├── playback.py     one supervised librespot child
  ├── spotify.py      Spotify Web API playback authority
  ├── library.py      read-only spotify_player browsing
  ├── lyrics.py       LRCLIB
  └── oauth.py        OAuth PKCE
```

### Playback invariants

1. systemd owns one `spotifierd` process.
2. `spotifierd` owns one `librespot` child.
3. systemd uses `KillMode=control-group` so restarts remove the whole process tree.
4. Spotify Web API is the only playback-state source.
5. Spotify Web API is the only transport-control path.
6. Every playback mutation targets the exact device named `Spotifier`.
7. `spotify_player` never starts, pauses, or otherwise controls playback.
8. Bodyless QuickShell POSTs use `xhr.send()` with no argument.

These invariants replace the former mixed `spotify_player`/MPRIS/Web API control design. That design created duplicate sessions, orphaned `librespot` processes, and controls that reported success without stopping audible playback.

## Data sources

### Spotify Web API

Use for:

- OAuth PKCE;
- devices and exact device selection;
- playback state;
- play, pause/stop, previous, next, seek, volume, shuffle, and repeat;
- search;
- playlist artwork and supplemental metadata.

### spotify_player

Use read-only for:

```sh
spotify_player get key user-playlists
spotify_player get item playlist --id ID
```

The public Spotify playlist-items endpoint returns HTTP 403 for this account/app. Do not use it as a fallback for playlist contents.

`spotify_player` may fail if `Playlists_cache.json` is corrupt. Back up that cache file and let it regenerate. Preserve credentials and artwork caches.

### librespot

`librespot` is only the local audio device. It is not a second control authority. `LibrespotSupervisor` owns its PID, captures its OAuth URL, restarts it after crashes, and terminates it during daemon shutdown.

### LRCLIB

LRCLIB requests are cached in memory, identify the client through User-Agent, and use track duration when available.

## HTTP API

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

Errors have stable codes:

```json
{"error":{"code":"device_unavailable","message":"Readable explanation"}}
```

## Cache and invalidation policy

| Source data | TTL | Invalidation |
| --- | ---: | --- |
| Playing state | 1.8 seconds | Every playback mutation |
| Paused/idle state | 4 seconds | Every playback mutation |
| Spotify devices | 30 seconds | Command failure, missing configured device, OAuth |
| Playlist index | 5 minutes | TTL, OAuth |
| Playlist tracks | 10 minutes | TTL, OAuth |
| Search results | 2 minutes | TTL, OAuth |
| Found lyrics | 24 hours | TTL, OAuth |
| Missing lyrics | 15 minutes | TTL, OAuth |

Playback caching is bypassed for five seconds after a mutation. Spotify playback updates are eventually consistent; caching the first pre-change response would otherwise make a successful control look reverted. Cached playing position is advanced from monotonic elapsed time. Playlist, search, and lyrics caches use bounded LRU eviction.

## Installation

One command after cloning:

```sh
./scripts/install-omarchy-plugin.sh
```

It installs the user service, enables it for login, installs the plugin symlink, updates the bar layout, and restarts the shell.

## Reliability requirements

- Never run the daemon through `nohup` alongside the systemd service.
- Never leave an orphaned `librespot` process.
- Never control playback through more than one backend.
- Reject invalid JSON and invalid action values with structured errors.
- Serialize frontend actions while one mutation is pending.
- Ignore stale playlist, search, and lyric responses.
- Keep status polling bounded to one in-flight request.
- Keep large-playlist artwork enrichment off the initial response path.
- Surface every action error in the panel.

## Verification contract

A release is not complete until all of these pass:

1. Backend compilation and unit tests.
2. `spotifierd.service` is enabled and active.
3. The service cgroup has one Python process and one `librespot` child.
4. Starting a real track changes status to `Playing`.
5. Clicking play/pause changes status between `Playing` and `Paused`.
6. Restarting the service does not create a second `librespot` process.
7. Playlists load, including a playlist with hundreds of tracks.
8. Search returns mixed result types.
9. Lyrics load and synchronized lines follow position.
10. QuickShell logs contain no Spotifier QML errors.

## Remaining roadmap

1. Persist successful playlist track caches with snapshot-based invalidation.
2. Add liked tracks, saved albums, followed artists, and queue views.
3. Add logout/re-authentication controls.
4. Add API integration tests around structured errors and routing.
5. Reduce status polling when the panel is closed and playback is stopped.

## Known external warning

The packaged Omarchy bar host logs:

```text
TypeError: Cannot assign to read-only property "moduleName"
```

The Spotifier widget still loads. Do not modify `/usr/share/omarchy` to suppress this warning.
