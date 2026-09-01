# Spotifier

Personal Spotify desktop client for Omarchy. Spotifier provides a compact bar widget, a full library/search/lyrics panel, and one locally supervised Spotify Connect device.

## Architecture

```text
Omarchy QuickShell plugin
        │ localhost HTTP/JSON
        ▼
spotifierd user service
  ├── Spotify Web API: playback, search, playlists, and transport commands
  ├── spotify_player: ncspot OAuth bootstrap for every Web API request
  ├── librespot: the single local audio device
  └── LRCLIB: synchronized and plain lyrics
```

Playback has one authority: Spotify Web API commands targeted to the exact `Spotifier` device ID. `spotify_player` obtains the ncspot OAuth token but never starts playback or downloads library data itself.

## Cache freshness

The daemon uses bounded in-memory TTL caches to reduce Spotify, `spotify_player`, and LRCLIB traffic without hiding state changes:

| Data | TTL |
| --- | ---: |
| Playing state | 1.8 seconds |
| Paused/idle state | 4 seconds |
| Spotify devices | 30 seconds |
| Playlist index | 5 minutes |
| Playlist tracks | 10 minutes |
| Search results | 2 minutes |
| Found lyrics | 24 hours |
| Missing lyrics | 15 minutes |

Playback mutations invalidate playback state immediately and bypass caching for five seconds while Spotify converges. Authentication invalidates every account-derived cache. Device-command failures invalidate the device cache. Bounded LRU eviction prevents searches, playlists, or lyrics from growing memory without limit.

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
- `librespot`
- `spotify_player`
- Spotify Premium

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

The service uses `KillMode=control-group`, ensuring daemon restarts cannot leave orphaned `librespot` audio processes.

## API

```text
GET  /api/health
GET  /api/status
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
