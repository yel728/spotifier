import QtQuick
import Quickshell
import Quickshell.Io

Item {
  id: root

  property string api: "http://127.0.0.1:8765"
  property bool online: false
  property bool loggedIn: false
  property bool libraryLoggedIn: false
  property bool streamingReady: false
  property string streamingLoginUrl: ""
  property bool statusPending: false
  property int emptyPlaybackPolls: 0

  property bool hasTrack: false
  property string trackUri: ""
  property string title: ""
  property string artist: ""
  property string album: ""
  property string artUrl: ""
  property string playbackStatus: "Stopped"
  property real positionSeconds: 0
  property string playbackStatusTarget: ""
  property int playbackStatusTargetPolls: 0
  property real lengthSeconds: 0
  property real volume: 0
  property real volumeTarget: -1
  property int volumeTargetPolls: 0
  property bool shuffleEnabled: false
  property int shuffleTarget: -1
  property int shuffleTargetPolls: 0
  property string repeatMode: "None"
  property string repeatModeTarget: ""
  property int repeatModeTargetPolls: 0

  property var playlists: []
  property bool playlistsLoading: false
  property string playlistsError: ""
  property var selectedPlaylist: null
  property var playlistTracks: []
  property bool playlistLoading: false
  property bool playlistArtPending: false
  property string playlistError: ""
  property string playlistRequestUri: ""

  property string searchQuery: ""
  property var searchResults: []
  property bool searchLoading: false
  property string searchError: ""
  property string searchRequestKey: ""
  property var selectedSearchCollection: null
  property var searchCollectionTracks: []
  property bool searchCollectionLoading: false
  property bool searchCollectionArtPending: false
  property string searchCollectionError: ""
  property string searchCollectionRequestUri: ""

  property var lyricsLines: []
  property string plainLyrics: ""
  property bool lyricsLoading: false
  property string lyricsError: ""
  property string lyricsTrackKey: ""

  property int actionRequests: 0
  readonly property bool actionPending: actionRequests > 0
  property string actionError: ""

  readonly property bool isPlaying: playbackStatus === "Playing"
  readonly property int currentLyricIndex: {
    var current = -1
    for (var i = 0; i < lyricsLines.length; ++i) {
      if (Number(lyricsLines[i].time) <= positionSeconds + 0.15) current = i
      else break
    }
    return current
  }

  function errorMessage(data, fallback) {
    if (!data || !data.error) return fallback || ""
    if (typeof data.error === "string") return data.error
    return data.error.message || data.error.code || fallback || "Request failed"
  }

  function request(method, path, body, callback) {
    var xhr = new XMLHttpRequest()
    xhr.open(method, api + path)
    xhr.setRequestHeader("Content-Type", "application/json")
    xhr.onreadystatechange = function() {
      if (xhr.readyState !== XMLHttpRequest.DONE) return
      var data = ({})
      try { data = JSON.parse(xhr.responseText || "{}") }
      catch (error) { data = { error: { code: "invalid_response", message: xhr.responseText || String(error) } } }
      if (xhr.status < 200 || xhr.status >= 300) {
        if (!data.error) data.error = { code: "http_error", message: "HTTP " + xhr.status }
      }
      if (callback) callback(data)
    }
    xhr.onerror = function() {
      if (callback) callback({ error: { code: "offline", message: "Spotifier daemon is offline" } })
    }
    if (body === undefined || body === null) xhr.send()
    else xhr.send(JSON.stringify(body))
  }

  function refresh() {
    if (statusPending) return
    statusPending = true
    request("GET", "/api/status", null, function(state) {
      root.statusPending = false
      if (state.error) {
        root.online = false
        root.actionError = root.errorMessage(state, "Spotifier daemon is offline")
        return
      }
      root.online = true
      if (root.actionError === "Spotifier daemon is offline") root.actionError = ""
      root.loggedIn = !!state.logged_in
      root.libraryLoggedIn = !!state.library_logged_in
      if (!root.loggedIn || !root.libraryLoggedIn) {
        root.playlists = []
        root.closePlaylist()
      }
      root.streamingReady = !!state.streaming_ready
      root.streamingLoginUrl = state.streaming_login_url || ""
      var preservePlayback = !!state.playback_error
      if (!preservePlayback && !state.has_track && root.hasTrack) {
        root.emptyPlaybackPolls += 1
        preservePlayback = root.emptyPlaybackPolls < 3
      } else if (state.has_track) {
        root.emptyPlaybackPolls = 0
      }
      if (!preservePlayback) {
        root.hasTrack = !!state.has_track
        root.trackUri = state.uri || ""
        root.title = state.title || ""
        root.artist = state.artist || ""
        root.album = state.album || ""
        root.artUrl = state.art_url || ""
        var reportedStatus = state.status || "Stopped"
        if (root.playbackStatusTarget !== "") {
          if (reportedStatus === root.playbackStatusTarget || root.actionError !== "" || root.playbackStatusTargetPolls >= 5) {
            root.playbackStatus = reportedStatus
            root.playbackStatusTarget = ""
            root.playbackStatusTargetPolls = 0
          } else {
            root.playbackStatus = root.playbackStatusTarget
            root.playbackStatusTargetPolls += 1
          }
        } else {
          root.playbackStatus = reportedStatus
        }
        root.positionSeconds = Number(state.position_s || 0)
        root.lengthSeconds = Number(state.length_s || 0)
        var reportedVolume = Math.max(0, Math.min(1, Number(state.volume || 0)))
        if (root.volumeTarget >= 0) {
          var volumeSettled = Math.abs(reportedVolume - root.volumeTarget) <= 0.011
          var volumeFailed = root.actionError !== ""
          if (volumeSettled || volumeFailed || root.volumeTargetPolls >= 4) {
            root.volume = reportedVolume
            root.volumeTarget = -1
            root.volumeTargetPolls = 0
          } else {
            root.volume = root.volumeTarget
            if (!root.actionPending) root.volumeTargetPolls += 1
          }
        } else {
          root.volume = reportedVolume
        }
        var reportedShuffle = state.shuffle ? 1 : 0
        if (root.shuffleTarget >= 0) {
          if (reportedShuffle === root.shuffleTarget || root.actionError !== "" || root.shuffleTargetPolls >= 5) {
            root.shuffleEnabled = reportedShuffle === 1
            root.shuffleTarget = -1
            root.shuffleTargetPolls = 0
          } else {
            root.shuffleEnabled = root.shuffleTarget === 1
            root.shuffleTargetPolls += 1
          }
        } else {
          root.shuffleEnabled = reportedShuffle === 1
        }
        var reportedRepeat = state.repeat_mode || "None"
        if (root.repeatModeTarget !== "") {
          if (reportedRepeat === root.repeatModeTarget || root.actionError !== "" || root.repeatModeTargetPolls >= 5) {
            root.repeatMode = reportedRepeat
            root.repeatModeTarget = ""
            root.repeatModeTargetPolls = 0
          } else {
            root.repeatMode = root.repeatModeTarget
            root.repeatModeTargetPolls += 1
          }
        } else {
          root.repeatMode = reportedRepeat
        }
        root.refreshLyrics()
      }
      if (root.loggedIn && root.libraryLoggedIn && root.playlists.length === 0 && !root.playlistsLoading) root.refreshPlaylists()
    })
  }

  function clearPlayback() {
    emptyPlaybackPolls = 0
    playbackStatusTarget = ""
    playbackStatusTargetPolls = 0
    shuffleTarget = -1
    shuffleTargetPolls = 0
    repeatModeTarget = ""
    repeatModeTargetPolls = 0
    hasTrack = false
    trackUri = ""
    title = ""
    artist = ""
    album = ""
    artUrl = ""
    playbackStatus = "Stopped"
    positionSeconds = 0
    lengthSeconds = 0
    refreshLyrics()
  }

  function refreshPlaylists() {
    if (!loggedIn || !libraryLoggedIn) {
      playlistsError = "Complete Spotify login to load your library"
      return
    }
    playlistsLoading = true
    playlistsError = ""
    request("GET", "/api/playlists", null, function(data) {
      root.playlistsLoading = false
      root.playlistsError = root.errorMessage(data)
      if (!data.error) root.playlists = data.items || []
    })
  }

  function loadPlaylist(playlist) {
    selectedPlaylist = playlist
    playlistTracks = []
    playlistError = ""
    playlistLoading = true
    playlistArtPending = false
    playlistRequestUri = playlist && playlist.uri ? String(playlist.uri) : ""
    var uri = playlistRequestUri
    if (!uri) {
      playlistLoading = false
      playlistError = "Collection unavailable"
      return
    }
    request("GET", "/api/playlist_tracks?uri=" + encodeURIComponent(uri), null, function(data) {
      if (root.playlistRequestUri !== uri) return
      root.playlistLoading = false
      root.playlistError = root.errorMessage(data)
      if (!data.error) {
        root.playlistTracks = data.items || []
        root.playlistArtPending = !!data.art_pending
        if (root.playlistTracks.length === 0) root.playlistError = "No tracks found"
      }
    })
  }

  function refreshPlaylistArt() {
    var uri = playlistRequestUri
    if (!playlistArtPending || !uri) return
    request("GET", "/api/playlist_tracks?cached=1&uri=" + encodeURIComponent(uri), null, function(data) {
      if (root.playlistRequestUri !== uri || data.error) return
      root.playlistTracks = data.items || root.playlistTracks
      root.playlistArtPending = !!data.art_pending
    })
  }

  function closePlaylist() {
    selectedPlaylist = null
    playlistTracks = []
    playlistError = ""
    playlistLoading = false
    playlistArtPending = false
    playlistRequestUri = ""
  }

  function loadSearchCollection(collection) {
    selectedSearchCollection = collection
    searchCollectionTracks = []
    searchCollectionError = ""
    searchCollectionLoading = true
    searchCollectionArtPending = false
    searchCollectionRequestUri = collection && collection.uri ? String(collection.uri) : ""
    var uri = searchCollectionRequestUri
    if (!uri) {
      searchCollectionLoading = false
      searchCollectionError = "Collection unavailable"
      return
    }
    request("GET", "/api/playlist_tracks?uri=" + encodeURIComponent(uri), null, function(data) {
      if (root.searchCollectionRequestUri !== uri) return
      root.searchCollectionLoading = false
      root.searchCollectionError = root.errorMessage(data)
      if (!data.error) {
        root.searchCollectionTracks = data.items || []
        root.searchCollectionArtPending = !!data.art_pending
        if (root.searchCollectionTracks.length === 0) root.searchCollectionError = "No tracks found"
      }
    })
  }

  function refreshSearchCollectionArt() {
    var uri = searchCollectionRequestUri
    if (!searchCollectionArtPending || !uri) return
    request("GET", "/api/playlist_tracks?cached=1&uri=" + encodeURIComponent(uri), null, function(data) {
      if (root.searchCollectionRequestUri !== uri || data.error) return
      root.searchCollectionTracks = data.items || root.searchCollectionTracks
      root.searchCollectionArtPending = !!data.art_pending
    })
  }

  function closeSearchCollection() {
    selectedSearchCollection = null
    searchCollectionTracks = []
    searchCollectionError = ""
    searchCollectionLoading = false
    searchCollectionArtPending = false
    searchCollectionRequestUri = ""
  }

  function search(query) {
    searchQuery = String(query || "").trim()
    searchRequestKey = searchQuery
    searchResults = []
    searchError = ""
    if (!searchQuery) {
      searchError = "Enter an artist, album, track, or playlist"
      return
    }
    searchLoading = true
    var key = searchRequestKey
    request("GET", "/api/search?q=" + encodeURIComponent(key), null, function(data) {
      if (root.searchRequestKey !== key) return
      root.searchLoading = false
      root.searchError = root.errorMessage(data)
      if (!data.error) {
        root.searchResults = data.items || []
        if (root.searchResults.length === 0) root.searchError = "No results"
      }
    })
  }

  function refreshLyrics() {
    var key = hasTrack ? title + "\n" + artist + "\n" + album + "\n" + Math.round(lengthSeconds) : ""
    if (key === lyricsTrackKey) return
    lyricsTrackKey = key
    lyricsLines = []
    plainLyrics = ""
    lyricsError = ""
    lyricsLoading = key !== ""
    if (!key) return
    var path = "/api/lyrics?track=" + encodeURIComponent(title)
      + "&artist=" + encodeURIComponent(artist)
      + "&album=" + encodeURIComponent(album)
      + "&duration=" + encodeURIComponent(lengthSeconds)
    request("GET", path, null, function(data) {
      if (root.lyricsTrackKey !== key) return
      root.lyricsLoading = false
      root.lyricsError = root.errorMessage(data)
      if (data.error) return
      if (!data.found) root.lyricsError = "Lyrics not found"
      else if (data.instrumental) root.lyricsError = "Instrumental track"
      else {
        root.lyricsLines = data.lines || []
        root.plainLyrics = data.plain || ""
        if (root.lyricsLines.length === 0 && !root.plainLyrics) root.lyricsError = "Lyrics unavailable"
      }
    })
  }

  function perform(path, body) {
    actionRequests += 1
    actionError = ""
    request("POST", path, body, function(data) {
      root.actionRequests = Math.max(0, root.actionRequests - 1)
      if (data.error) root.actionError = root.errorMessage(data)
      actionRefresh.start()
    })
  }

  function playUri(uri, contextUri) {
    var body = { uri: uri }
    if (contextUri) body.context_uri = contextUri
    perform("/api/play", body)
  }
  function playPause() {
    playbackStatusTarget = isPlaying ? "Paused" : "Playing"
    playbackStatusTargetPolls = 0
    playbackStatus = playbackStatusTarget
    perform(playbackStatusTarget === "Paused" ? "/api/pause" : "/api/resume", null)
  }
  function stop() {
    playbackStatusTarget = "Paused"
    playbackStatusTargetPolls = 0
    playbackStatus = playbackStatusTarget
    perform("/api/stop", null)
  }
  function next() { perform("/api/next", null) }
  function previous() { perform("/api/previous", null) }
  function seek(fraction) {
    if (lengthSeconds > 0) perform("/api/seek", { position: Math.max(0, Math.min(1, fraction)) * lengthSeconds })
  }
  function seekBy(seconds) {
    if (lengthSeconds <= 0) return
    var position = Math.max(0, Math.min(lengthSeconds, positionSeconds + seconds))
    positionSeconds = position
    perform("/api/seek", { position: position })
  }
  function setVolume(value) {
    if (actionPending) return
    var next = Math.max(0, Math.min(1, value))
    volumeTarget = next
    volumeTargetPolls = 0
    volume = next
    perform("/api/volume", { volume: next })
  }
  function adjustVolume(delta) { setVolume(volume + delta) }
  function toggleShuffle() {
    shuffleTarget = shuffleEnabled ? 0 : 1
    shuffleTargetPolls = 0
    shuffleEnabled = shuffleTarget === 1
    perform("/api/shuffle", { enabled: shuffleEnabled })
  }
  function cycleRepeat() {
    repeatModeTarget = repeatMode === "None" ? "Playlist" : (repeatMode === "Playlist" ? "Track" : "None")
    repeatModeTargetPolls = 0
    repeatMode = repeatModeTarget
    perform("/api/repeat", { mode: repeatMode })
  }
  function login() { Quickshell.execDetached(["xdg-open", api + "/auth/login"]) }
  function logout() {
    if (actionPending) return
    actionRequests += 1
    actionError = ""
    request("POST", "/auth/logout", null, function(data) {
      root.actionRequests = Math.max(0, root.actionRequests - 1)
      root.actionError = root.errorMessage(data)
      if (!data.error) {
        root.loggedIn = false
        root.libraryLoggedIn = false
        root.playlists = []
        root.searchResults = []
        root.closePlaylist()
        root.closeSearchCollection()
        root.clearPlayback()
      }
      root.refresh()
    })
  }
  Timer {
    id: actionRefresh
    interval: 100
    repeat: true
    onTriggered: {
      if (root.statusPending) return
      stop()
      root.refresh()
    }
  }

  Timer { interval: 1000; running: true; repeat: true; triggeredOnStart: true; onTriggered: root.refresh() }
  Timer { interval: 2000; running: root.playlistArtPending; repeat: true; onTriggered: root.refreshPlaylistArt() }
  Timer { interval: 2000; running: root.searchCollectionArtPending; repeat: true; onTriggered: root.refreshSearchCollectionArt() }

  IpcHandler {
    target: "spotifier"
    function state(): string {
      return JSON.stringify({
        online: root.online,
        loggedIn: root.loggedIn,
        libraryLoggedIn: root.libraryLoggedIn,
        streamingReady: root.streamingReady,
        title: root.title,
        status: root.playbackStatus,
        volume: root.volume,
        position: root.positionSeconds,
        shuffle: root.shuffleEnabled,
        repeatMode: root.repeatMode,
        playlists: root.playlists.length,
        selected: root.selectedPlaylist ? root.selectedPlaylist.name : "",
        tracks: root.playlistTracks.length,
        playlistError: root.playlistError,
        searchResults: root.searchResults.length,
        searchCollection: root.selectedSearchCollection ? root.selectedSearchCollection.name : "",
        searchCollectionTracks: root.searchCollectionTracks.length,
        searchError: root.searchError,
        lyrics: root.lyricsLines.length,
        lyricsError: root.lyricsError,
        actionError: root.actionError
      })
    }
    function loadIndex(index: string): string {
      var value = Number(index)
      if (value >= 0 && value < root.playlists.length) root.loadPlaylist(root.playlists[value])
      return "ok"
    }
    function searchFor(query: string): string { root.search(query); return "ok" }
    function stopNow(): string { root.stop(); return "ok" }
    function setVolumeTo(value: string): string { root.setVolume(Number(value)); return "ok" }
  }
}
