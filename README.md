# Spotifier

Personal Spotify desktop client for Omarchy. Spotifier provides a compact bar widget, a full library/search/lyrics panel, and one locally supervised Spotify Connect device.

## Architecture

```text
Omarchy QuickShell plugin
        │ localhost HTTP/JSON + NDJSON event stream
        ▼
spotifierd user service
  ├── Spotify Web API: search and playlists
  ├── spotifier-player: local playback and timed Spotify lyrics
  ├── spotify_player: ncspot OAuth bootstrap
  ├── LRCLIB: LRCGET-compatible synchronized lyrics fallback
  └── SQLite: permanent synchronized lyrics cache
```

Track loading and every transport command use the local `spotifier-player` control socket. Play, pause, previous, next, seek, volume, shuffle, and repeat therefore bypass Spotify's rate-limited Web API. Slow lyric metadata requests run independently from ordered playback commands, and track selections arriving within 200 milliseconds coalesce to the latest selection rather than queueing stale loads. When a track is unavailable, librespot skips it without disconnecting the active device or corrupting subsequent controls. Playback events return over a local Unix datagram socket; QuickShell keeps one streaming connection to `spotifierd` and never polls Spotify for status.

## Cache freshness

The daemon uses bounded in-memory TTL caches plus persistent collection snapshots to reduce Spotify, `spotify_player`, and LRCLIB traffic without hiding state changes:

| Data | Policy |
| --- | --- |
| Spotify devices | 30 seconds |
| Playlist index | 5 minutes |
| Playlist and album tracks | Persistent snapshot; background refresh on open |
| Search results | 2 minutes |
| Synchronized lyrics | 24 hours |
| Plain or missing lyrics | 15 minutes |

Playlist and album snapshots are returned immediately, refreshed asynchronously, and rewritten only when normalized track data changes. Authentication invalidates every account-derived cache. Device-command failures invalidate the device cache. Bounded LRU eviction prevents searches, collections, or lyrics from growing memory without limit.

Opening the Lyrics tab asks the authenticated local `spotifier-player` session for Spotify's native lyric metadata first, preserving its line timestamps without a Web API or CLI request. When Spotify has no lyrics or only unsynchronized lyrics, the daemon tries LRCLIB's duration-sensitive exact lookup, then falls back to a title search. LRCLIB candidates must have synchronized lyrics, an exact normalized title, a duration within four seconds, and either a matching artist or an exact album. Artist, album, full artist credit, and nearest duration rank safe matches. The panel identifies the selected source above the lyrics. Every synchronized result is stored permanently in `~/.local/share/spotifier/lyrics.sqlite3`; later requests read it without contacting either provider.

## Panel keyboard shortcuts

Shortcuts are active only while the Spotifier popup is open. Typing shortcuts are disabled while the search field has focus.

| Key | Action |
| --- | --- |
| `Space` | Play or pause |
| `Left` / `Right` | Seek backward or forward 5 seconds |
| `Up` / `Down` | Move and reveal the active list's keyboard cursor; scroll lyrics |
| `Enter` | Open the selected playlist or play the selected track |
| `Backspace` | Return from a track list to the playlist list |
| `+` / `-` | Raise or lower volume by 5% |
| `N` / `P` | Next or previous track |
| `S` | Toggle shuffle |
| `R` | Cycle repeat off, playlist, and track |
| `1` / `2` / `3` | Open Library, Search, or Lyrics |
| `Ctrl+F` | Open and focus Search |
| `Escape` | Close the popup |

## Requirements

- Python 3.11+
- Omarchy/QuickShell
- Rust 1.85+ with Cargo
- `spotify_player`
- Spotify Premium
- `python-dbus`, `python-gobject`, and `bluez-utils` for desktop/headset controls

Spotifier exposes `org.mpris.MediaPlayer2.spotifier` on the user D-Bus session.
Desktop media keys and the Bluetooth `mpris-proxy.service` forward play/pause,
next, and previous to the same local player used by the widget. The installer
enables the Bluetooth proxy and keeps Omarchy's media-control service loaded.
Playback status and track metadata come from the daemon's local event state.

## Spotify authorization

No Spotify Developer Dashboard application is required. Open the panel and select the Spotify icon; Spotifier uses `spotify_player` to obtain an ncspot OAuth token for playback, search, and library API requests.

Spotify labels this authorization as **ncspot**. The token is stored locally in `~/.cache/spotify-player/user_client_token.json` and removed by the panel logout control.

## Install

```sh
./scripts/install-omarchy-plugin.sh
```

This single command:

- installs and enables `spotifierd.service` as a user service;
- symlinks the Omarchy plugin into `~/.config/omarchy/plugins`;
- places the widget in the bar;
- restarts the Omarchy shell.

Open `http://127.0.0.1:8765/auth/login` once to authorize Spotify.

## Service management

```sh
systemctl --user status spotifierd.service
systemctl --user restart spotifierd.service
journalctl --user -u spotifierd.service -n 100 --no-pager
```

The service uses `KillMode=control-group`, ensuring daemon restarts cannot leave orphaned player processes.

## API

```text
GET  /api/health
GET  /api/status
GET  /api/events
GET  /api/playlists
GET  /api/playlist_tracks?uri=spotify:{playlist|album}:...
GET  /api/search?q=QUERY
GET  /api/lyrics?track=TITLE&artist=ARTIST&album=ALBUM&duration=SECONDS
GET  /api/devices
POST /api/play       {"uri":"spotify:track:...","context_uri":"spotify:playlist:..."}
POST /api/playpause
POST /api/stop
POST /api/previous
POST /api/next
POST /api/seek       {"position":42.5}
POST /api/volume     {"volume":0.5}
POST /api/shuffle    {"enabled":true}
POST /api/repeat     {"mode":"None|Playlist|Track"}
```

## Development checks

```sh
python -m compileall spotifierd
python -m unittest discover -s tests
curl -sS http://127.0.0.1:8765/api/health
```

Machine-local configuration, tokens, generated systemd units, and caches are not stored in Git.
