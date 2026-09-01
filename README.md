# Spotifier

Personal Spotify desktop client for Omarchy. Spotifier provides a compact bar widget, a full library/search/lyrics panel, and one locally supervised Spotify Connect device.

## Architecture

```text
Omarchy QuickShell plugin
        │ localhost HTTP/JSON
        ▼
spotifierd user service
  ├── Spotify Web API: playback, search, playlists, and transport commands
  ├── spotify_player: playlist OAuth bootstrap only
  ├── librespot: the single local audio device
  └── LRCLIB: synchronized and plain lyrics
```

Playback has one authority: Spotify Web API commands targeted to the exact `Spotifier` device ID. `spotify_player` only obtains the playlist-scoped OAuth token; it never starts playback or downloads library data.

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
| `Up` / `Down` | Scroll the active playlist, track, search, or lyric list |
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

## Spotify app setup

Create an app in the Spotify Developer Dashboard with this exact redirect URI:

```text
http://127.0.0.1:8765/auth/callback
```

Create local configuration:

```sh
mkdir -p ~/.config/spotifier
cp config.example.json ~/.config/spotifier/config.json
$EDITOR ~/.config/spotifier/config.json
```

Set `client_id`. Do not configure a client secret; Spotifier uses OAuth PKCE.

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
GET  /api/playlist_tracks?uri=spotify:playlist:...
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
