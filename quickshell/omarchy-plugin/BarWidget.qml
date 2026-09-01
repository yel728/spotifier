import QtQuick
import Quickshell
import Quickshell.Io
import qs.Ui
import qs.Commons

BarWidget {
  id: root

  readonly property var spotifier: bar?.shell?.serviceFor("yel728.spotifier")
  readonly property bool online: spotifier && spotifier.online
  readonly property bool hasTrack: spotifier && spotifier.hasTrack
  readonly property bool isPlaying: spotifier && spotifier.isPlaying
  readonly property string trackLine: spotifier ? spotifier.title + (spotifier.artist ? "  ·  " + spotifier.artist : "") : ""
  readonly property var tabLabels: ["LIBRARY", "SEARCH", "LYRICS"]
  readonly property var tabIcons: ["󰲸", "󰍉", "󰊤"]
  readonly property real openPanelIndicatorWidth: barContent.implicitWidth
  readonly property real openPanelIndicatorHeight: musicTrigger.height
  readonly property var shortcutHelp: [
    { keys: "SPACE", action: "Play / pause" },
    { keys: "←  →", action: "Seek 5 seconds" },
    { keys: "↑  ↓", action: "Scroll current list" },
    { keys: "+  −", action: "Volume ±5%" },
    { keys: "N  P", action: "Next / previous" },
    { keys: "S", action: "Toggle shuffle" },
    { keys: "R", action: "Cycle repeat" },
    { keys: "1  2  3", action: "Switch sections" },
    { keys: "CTRL F", action: "Focus search" },
    { keys: "ESC", action: "Close panel" }
  ]

  property bool popupOpen: false
  property int tab: 0
  property string query: ""
  property bool showShortcuts: false

  function close() { popupOpen = false; showShortcuts = false }
  function togglePopup() { popupOpen = !popupOpen }
  function toggleTrackPlayback() {
    if (hasTrack && spotifier) spotifier.playPause()
  }
  function toggleShortcutHelp() { showShortcuts = !showShortcuts }
  function selectTab(index) {
    showShortcuts = false
    tab = index
    if (index === 0 && spotifier) spotifier.refreshPlaylists()
    if (index === 1) Qt.callLater(function() { searchInput.forceActiveFocus() })
  }
  function activeList() {
    if (showShortcuts) return null
    if (tab === 0) return spotifier && spotifier.selectedPlaylist ? playlistTracksView : playlistsView
    if (tab === 1) return searchResultsView
    if (tab === 2 && lyricsView.visible) return lyricsView
    return null
  }
  function scrollActiveList(direction) {
    var view = activeList()
    if (!view) return
    var maximum = Math.max(0, view.contentHeight - view.height)
    view.contentY = Math.max(0, Math.min(maximum, view.contentY + direction * Style.space(42)))
  }
  function selectedFill(selected) { return selected ? Style.selectedFillFor(root.bar.foreground, Color.accent) : "transparent" }
  function mutedColor() { return Qt.darker(root.bar.foreground, 1.42) }
  function formatTime(seconds) {
    var value = Math.max(0, Math.floor(Number(seconds) || 0))
    var minutes = Math.floor(value / 60)
    var remainder = value % 60
    return minutes + ":" + (remainder < 10 ? "0" : "") + remainder
  }

  component FlatButton: Item {
    id: control

    property string iconText: ""
    property color foreground: Color.foreground
    signal clicked()

    implicitWidth: Style.space(28)
    implicitHeight: Style.space(28)
    opacity: enabled ? (pointer.pressed ? 0.62 : 1) : 0.35

    Behavior on opacity { NumberAnimation { duration: 90 } }

    Text {
      anchors.centerIn: parent
      text: control.iconText
      color: control.foreground
      font.family: Style.font.family
      font.pixelSize: Style.font.icon
    }

    MouseArea {
      id: pointer
      anchors.fill: parent
      enabled: control.enabled
      hoverEnabled: true
      cursorShape: Qt.PointingHandCursor
      onClicked: control.clicked()
    }
  }

  focus: popupOpen
  Keys.onEscapePressed: popupOpen = false

  Shortcut {
    sequence: "Escape"
    context: Qt.ApplicationShortcut
    enabled: root.popupOpen
    onActivated: root.popupOpen = false
  }

  Shortcut {
    sequence: "Space"
    context: Qt.ApplicationShortcut
    enabled: root.popupOpen && root.hasTrack && !searchInput.activeFocus
    onActivated: if (root.spotifier) root.spotifier.playPause()
  }

  Shortcut {
    sequence: "Left"
    context: Qt.ApplicationShortcut
    enabled: root.popupOpen && root.hasTrack && !searchInput.activeFocus
    onActivated: if (root.spotifier) root.spotifier.seekBy(-5)
  }

  Shortcut {
    sequence: "Right"
    context: Qt.ApplicationShortcut
    enabled: root.popupOpen && root.hasTrack && !searchInput.activeFocus
    onActivated: if (root.spotifier) root.spotifier.seekBy(5)
  }

  Shortcut {
    sequence: "Up"
    context: Qt.ApplicationShortcut
    autoRepeat: false
    enabled: root.popupOpen && !root.showShortcuts
    onActivated: root.scrollActiveList(-1)
  }

  Shortcut {
    sequence: "Down"
    context: Qt.ApplicationShortcut
    enabled: root.popupOpen && !root.showShortcuts
    autoRepeat: false
    onActivated: root.scrollActiveList(1)
  }

  Shortcut {
    sequence: "+"
    context: Qt.ApplicationShortcut
    enabled: root.popupOpen && root.hasTrack && !searchInput.activeFocus
    onActivated: if (root.spotifier) root.spotifier.adjustVolume(0.05)
  }

  Shortcut {
    sequence: "Shift+="
    context: Qt.ApplicationShortcut
    enabled: root.popupOpen && root.hasTrack && !searchInput.activeFocus
    onActivated: if (root.spotifier) root.spotifier.adjustVolume(0.05)
  }

  Shortcut {
    sequence: "-"
    context: Qt.ApplicationShortcut
    enabled: root.popupOpen && root.hasTrack && !searchInput.activeFocus
    onActivated: if (root.spotifier) root.spotifier.adjustVolume(-0.05)
  }

  Shortcut {
    sequence: "N"
    context: Qt.ApplicationShortcut
    enabled: root.popupOpen && root.hasTrack && !searchInput.activeFocus
    onActivated: if (root.spotifier) root.spotifier.next()
  }

  Shortcut {
    sequence: "P"
    context: Qt.ApplicationShortcut
    enabled: root.popupOpen && root.hasTrack && !searchInput.activeFocus
    onActivated: if (root.spotifier) root.spotifier.previous()
  }

  Shortcut {
    sequence: "S"
    context: Qt.ApplicationShortcut
    enabled: root.popupOpen && root.hasTrack && !searchInput.activeFocus
    onActivated: if (root.spotifier) root.spotifier.toggleShuffle()
  }

  Shortcut {
    sequence: "R"
    context: Qt.ApplicationShortcut
    enabled: root.popupOpen && root.hasTrack && !searchInput.activeFocus
    onActivated: if (root.spotifier) root.spotifier.cycleRepeat()
  }

  Shortcut {
    sequence: "1"
    context: Qt.ApplicationShortcut
    enabled: root.popupOpen && !searchInput.activeFocus
    onActivated: root.selectTab(0)
  }

  Shortcut {
    sequence: "2"
    context: Qt.ApplicationShortcut
    enabled: root.popupOpen && !searchInput.activeFocus
    onActivated: root.selectTab(1)
  }

  Shortcut {
    sequence: "3"
    context: Qt.ApplicationShortcut
    enabled: root.popupOpen && !searchInput.activeFocus
    onActivated: root.selectTab(2)
  }

  Shortcut {
    sequence: "Ctrl+F"
    context: Qt.ApplicationShortcut
    enabled: root.popupOpen
    onActivated: root.selectTab(1)
  }
  visible: true
  implicitHeight: barSize
  implicitWidth: root.bar && root.bar.vertical ? Style.space(28) : Math.max(Style.space(28), barContent.implicitWidth)

  Row {
    id: barContent
    anchors.centerIn: parent
    spacing: Style.space(6)

    Item {
      id: musicTrigger
      width: Style.space(26)
      height: Style.space(26)
      anchors.verticalCenter: parent.verticalCenter

      Text {
        anchors.centerIn: parent
        text: "󰎆"
        color: root.popupOpen || root.isPlaying ? Color.accent : (root.online ? root.bar.barForeground : Qt.darker(root.bar.barForeground, 1.55))
        font.family: root.bar.fontFamily
        font.pixelSize: Style.font.heading

        Behavior on color { ColorAnimation { duration: 140 } }
      }

      MouseArea {
        anchors.fill: parent
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor
        onClicked: root.togglePopup()
      }
    }

    Item {
      id: trackTrigger
      visible: root.hasTrack && !(root.bar && root.bar.vertical)
      width: visible ? Math.min(Style.space(210), trackText.implicitWidth) : 0
      height: Style.space(26)
      clip: true
      anchors.verticalCenter: parent.verticalCenter

      Text {
        id: trackText
        anchors.verticalCenter: parent.verticalCenter
        text: root.trackLine
        color: root.bar.barForeground
        font.family: "Noto Sans CJK SC"
        font.pixelSize: Style.font.bodySmall
        font.bold: true

        property bool needsScroll: implicitWidth > trackTrigger.width

        SequentialAnimation {
          id: trackMarquee
          running: trackText.needsScroll && !root.popupOpen
          loops: Animation.Infinite
          onRunningChanged: if (!running) trackText.x = 0

          PauseAnimation { duration: 1200 }
          NumberAnimation {
            target: trackText
            property: "x"
            from: 0
            to: -(trackText.implicitWidth - trackTrigger.width)
            duration: Math.max(2200, (trackText.implicitWidth - trackTrigger.width) * 30)
            easing.type: Easing.InOutCubic
          }
          PauseAnimation { duration: 900 }
          NumberAnimation {
            target: trackText
            property: "x"
            from: -(trackText.implicitWidth - trackTrigger.width)
            to: 0
            duration: 500
            easing.type: Easing.OutCubic
          }
        }
      }

      MouseArea {
        anchors.fill: parent
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor
        onClicked: root.toggleTrackPlayback()
      }
    }
  }

  PopupCard {
    id: popup
    anchorItem: root
    bar: root.bar
    owner: root
    open: root.popupOpen
    onOpenChanged: {
      if (open) root.forceActiveFocus()
      else root.showShortcuts = false
    }
    contentWidth: popup.fittedContentWidth(Style.space(430))
    contentHeight: popup.fittedContentHeight(panel.implicitHeight)

    Column {
      id: panel
      anchors.fill: parent
      spacing: Style.space(7)


      BorderSurface {
        width: parent.width
        height: Style.space(132)
        radius: Style.space(6)
        color: Style.normalFillFor(root.bar.foreground, Color.accent)
        borderSpec: Border.controlSpec("normal", root.bar.foreground, Color.accent)
        clip: true

        Row {
          anchors.fill: parent
          anchors.margins: Style.space(11)
          anchors.topMargin: Style.space(16)
          spacing: Style.space(8)

          BorderSurface {
            width: Style.space(78)
            height: Style.space(78)
            anchors.verticalCenter: parent.verticalCenter
            radius: Style.space(4)
            color: root.selectedFill(true)
            borderSpec: Border.controlSpec("selected", root.bar.foreground, Color.accent)
            clip: true

            Image {
              anchors.fill: parent
              source: root.spotifier ? root.spotifier.artUrl : ""
              fillMode: Image.PreserveAspectCrop
              asynchronous: true
              visible: source !== ""
            }

            Text {
              anchors.centerIn: parent
              visible: !(root.spotifier && root.spotifier.artUrl)
              text: "󰎆"
              color: Color.accent
              font.family: root.bar.fontFamily
              font.pixelSize: Style.font.display
            }
          }

          Column {
            width: parent.width - Style.space(86)
            anchors.verticalCenter: parent.verticalCenter
            spacing: Style.space(2)

            Row {
              width: parent.width
              height: Style.space(17)

              Text {
                width: parent.width - connectionState.width
                text: root.hasTrack ? (root.isPlaying ? "NOW PLAYING" : "PLAYBACK PAUSED") : "SPOTIFIER // READY"
                color: Color.accent
                font.family: root.bar.fontFamily
                font.pixelSize: Style.font.caption
                font.bold: true
                font.letterSpacing: 1.2
              }

              Text {
                id: connectionState
                text: root.online ? "● ONLINE" : "○ OFFLINE"
                color: root.online ? Color.accent : root.mutedColor()
                font.family: root.bar.fontFamily
                font.pixelSize: Style.font.caption
                font.bold: true
              }
            }

            Text {
              width: parent.width
              text: root.hasTrack ? root.spotifier.title : "No active signal"
              color: root.bar.foreground
              font.family: "Noto Sans CJK SC"
              font.pixelSize: Style.font.heading
              font.bold: true
              elide: Text.ElideRight
            }

            Text {
              width: parent.width
              text: root.hasTrack ? root.spotifier.artist + (root.spotifier.album ? "  /  " + root.spotifier.album : "") : "Select a track from the library or search"
              color: root.mutedColor()
              font.family: "Noto Sans CJK SC"
              font.pixelSize: Style.font.caption
              elide: Text.ElideRight
            }

            PanelSlider {
              id: progressSlider
              bar: root.bar
              width: parent.width
              enabled: root.hasTrack
              opacity: root.hasTrack ? 1 : 0.35
              value: root.spotifier && root.spotifier.lengthSeconds > 0 ? root.spotifier.positionSeconds / root.spotifier.lengthSeconds : 0
              onReleased: function(value) { if (root.spotifier) root.spotifier.seek(value) }
            }

            Item {
              width: parent.width
              height: Style.space(13)
              Text { anchors.left: parent.left; text: root.formatTime(root.spotifier ? root.spotifier.positionSeconds : 0); color: root.mutedColor(); font.family: root.bar.fontFamily; font.pixelSize: Style.font.caption }
              Text { anchors.right: parent.right; text: root.formatTime(root.spotifier ? root.spotifier.lengthSeconds : 0); color: root.mutedColor(); font.family: root.bar.fontFamily; font.pixelSize: Style.font.caption }
            }

            Row {
              width: parent.width
              height: Style.space(30)
              spacing: Style.space(3)

              FlatButton { enabled: root.hasTrack; iconText: "󰒟"; foreground: root.spotifier && root.spotifier.shuffleEnabled ? Color.accent : root.bar.foreground; onClicked: if (root.spotifier) root.spotifier.toggleShuffle() }
              FlatButton { enabled: root.hasTrack; iconText: "󰒮"; foreground: root.bar.foreground; onClicked: if (root.spotifier) root.spotifier.previous() }
              FlatButton { enabled: root.hasTrack; iconText: root.isPlaying ? "󰏤" : "󰐊"; foreground: Color.accent; onClicked: if (root.spotifier) root.spotifier.playPause() }
              FlatButton { enabled: root.hasTrack; iconText: "󰒭"; foreground: root.bar.foreground; onClicked: if (root.spotifier) root.spotifier.next() }
              FlatButton { enabled: root.hasTrack; iconText: root.spotifier && root.spotifier.repeatMode === "Track" ? "󰑘" : "󰑖"; foreground: root.spotifier && root.spotifier.repeatMode !== "None" ? Color.accent : root.bar.foreground; onClicked: if (root.spotifier) root.spotifier.cycleRepeat() }

              Text { anchors.verticalCenter: parent.verticalCenter; text: "󰕾"; color: root.mutedColor(); font.family: root.bar.fontFamily; font.pixelSize: Style.font.body }
              PanelSlider {
                id: volumeSlider
                bar: root.bar
                width: Style.space(58)
                anchors.verticalCenter: parent.verticalCenter
                enabled: root.hasTrack
                value: root.spotifier ? root.spotifier.volume : 0
                onReleased: function(value) { if (root.spotifier) root.spotifier.setVolume(value) }
              }
              Text { width: Style.space(28); anchors.verticalCenter: parent.verticalCenter; text: Math.round((volumeSlider.dragging ? volumeSlider.liveValue : (root.spotifier ? root.spotifier.volume : 0)) * 100); color: root.mutedColor(); font.family: root.bar.fontFamily; font.pixelSize: Style.font.caption; horizontalAlignment: Text.AlignRight }
            }
          }
        }
      }

      Item {
        width: parent.width
        height: Style.space(23)

        Row {
          anchors.left: parent.left
          anchors.verticalCenter: parent.verticalCenter
          spacing: Style.space(3)

          Repeater {
            model: root.tabLabels.length

            Item {
              required property int index
              width: Style.space(28)
              height: Style.space(22)

              Text {
                anchors.centerIn: parent
                text: root.tabIcons[index]
                color: root.tab === index ? Color.accent : root.mutedColor()
                font.family: root.bar.fontFamily
                font.pixelSize: Style.font.bodySmall
              }

              Rectangle {
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.bottom: parent.bottom
                height: Style.space(1)
                color: Color.accent
                visible: root.tab === index
              }

              MouseArea {
                anchors.fill: parent
                cursorShape: Qt.PointingHandCursor
                onClicked: root.selectTab(index)
              }
            }
          }
        }

        Row {
          anchors.right: parent.right
          anchors.verticalCenter: parent.verticalCenter
          spacing: Style.space(3)

          Item {
            width: Style.space(24)
            height: Style.space(22)

            Text {
              anchors.centerIn: parent
              text: "󰌌"
              color: root.showShortcuts ? Color.accent : root.mutedColor()
              font.family: root.bar.fontFamily
              font.pixelSize: Style.font.bodySmall
            }

            Rectangle {
              anchors.left: parent.left
              anchors.right: parent.right
              anchors.bottom: parent.bottom
              height: Style.space(1)
              color: Color.accent
              visible: root.showShortcuts
            }

            MouseArea {
              anchors.fill: parent
              cursorShape: Qt.PointingHandCursor
              onClicked: root.toggleShortcutHelp()
            }
          }

          Item {
            width: visible ? Style.space(24) : 0
            height: Style.space(22)
            visible: !root.spotifier || !root.spotifier.loggedIn || !root.spotifier.libraryLoggedIn

            Text {
              anchors.centerIn: parent
              text: "󰓇"
              color: root.bar.foreground
              font.family: root.bar.fontFamily
              font.pixelSize: Style.font.bodySmall
            }

            MouseArea {
              anchors.fill: parent
              cursorShape: Qt.PointingHandCursor
              onClicked: if (root.spotifier) root.spotifier.login()
            }
          }

          Item {
            width: visible ? Style.space(24) : 0
            height: Style.space(22)
            visible: !!(root.spotifier && (root.spotifier.loggedIn || root.spotifier.libraryLoggedIn))

            Text {
              anchors.centerIn: parent
              text: "󰍃"
              color: root.bar.foreground
              font.family: root.bar.fontFamily
              font.pixelSize: Style.font.bodySmall
            }

            MouseArea {
              anchors.fill: parent
              cursorShape: Qt.PointingHandCursor
              onClicked: if (root.spotifier) root.spotifier.logout()
            }
          }
        }
      }

      Text {
        width: parent.width
        visible: root.spotifier && root.spotifier.actionError !== ""
        text: root.spotifier ? "ERR // " + root.spotifier.actionError : ""
        color: Color.accent
        font.family: root.bar.fontFamily
        font.pixelSize: Style.font.caption
        horizontalAlignment: Text.AlignHCenter
        wrapMode: Text.WordWrap
      }

      Item {
        width: parent.width
        height: Style.space(260)

        Column {
          anchors.fill: parent
          spacing: Style.space(5)
          visible: root.tab === 0

          Row {
            width: parent.width
            height: Style.space(29)
            spacing: Style.space(5)

            FlatButton {
              visible: root.spotifier && root.spotifier.selectedPlaylist
              iconText: "󰁍"
              foreground: root.bar.foreground
              onClicked: if (root.spotifier) root.spotifier.closePlaylist()
            }

            Text {
              width: parent.width - libraryPlay.width - (root.spotifier && root.spotifier.selectedPlaylist ? Style.space(38) : 0)
              anchors.verticalCenter: parent.verticalCenter
              text: root.spotifier && root.spotifier.selectedPlaylist ? root.spotifier.selectedPlaylist.name + "  //  " + root.spotifier.playlistTracks.length + " TRACKS" : "PLAYLIST INDEX  //  " + (root.spotifier ? root.spotifier.playlists.length : 0)
              color: root.bar.foreground
              font.family: "Noto Sans CJK SC"
              font.pixelSize: Style.font.caption
              font.bold: true
              font.letterSpacing: 0.7
              elide: Text.ElideRight
            }

            FlatButton {
              id: libraryPlay
              visible: root.spotifier && root.spotifier.selectedPlaylist
              iconText: "󰐊"
              foreground: Color.accent
              onClicked: if (root.spotifier && root.spotifier.selectedPlaylist) root.spotifier.playUri(root.spotifier.selectedPlaylist.uri)
            }
          }

          Text {
            width: parent.width
            visible: root.spotifier && ((root.spotifier.selectedPlaylist && (root.spotifier.playlistLoading || root.spotifier.playlistError !== "")) || (!root.spotifier.selectedPlaylist && (root.spotifier.playlistsLoading || root.spotifier.playlistsError !== "")))
            text: root.spotifier ? (root.spotifier.selectedPlaylist ? (root.spotifier.playlistLoading ? "SYNCING TRACK INDEX…" : root.spotifier.playlistError) : (root.spotifier.playlistsLoading ? "SYNCING LIBRARY…" : root.spotifier.playlistsError)) : ""
            color: root.mutedColor()
            font.family: root.bar.fontFamily
            font.pixelSize: Style.font.caption
            horizontalAlignment: Text.AlignHCenter
          }

          ListView {
            id: playlistsView
            property var items: root.spotifier ? root.spotifier.playlists : []
            width: parent.width
            height: parent.height - Style.space(34)
            visible: !(root.spotifier && root.spotifier.selectedPlaylist)
            clip: true
            spacing: 0
            model: items.length
            delegate: playlistRow
          }

          ListView {
            id: playlistTracksView
            property var items: root.spotifier ? root.spotifier.playlistTracks : []
            property string contextUri: root.spotifier && root.spotifier.selectedPlaylist ? root.spotifier.selectedPlaylist.uri : ""
            width: parent.width
            height: parent.height - Style.space(34)
            visible: root.spotifier && root.spotifier.selectedPlaylist
            clip: true
            spacing: 0
            model: items.length
            delegate: trackRow
          }
        }

        Column {
          anchors.fill: parent
          spacing: Style.space(5)
          visible: root.tab === 1

          Row {
            width: parent.width
            height: Style.space(34)
            spacing: Style.space(5)

            BorderSurface {
              width: parent.width - searchButton.width - Style.space(5)
              height: parent.height
              radius: Style.space(5)
              color: Style.normalFillFor(root.bar.foreground, Color.accent)
              borderSpec: Border.controlSpec("normal", root.bar.foreground, Color.accent)

              Text {
                anchors.left: parent.left
                anchors.leftMargin: Style.space(9)
                anchors.verticalCenter: parent.verticalCenter
                visible: searchInput.text === ""
                text: "QUERY // TRACK  ARTIST  ALBUM  PLAYLIST"
                color: root.mutedColor()
                font.family: root.bar.fontFamily
                font.pixelSize: Style.font.caption
                font.letterSpacing: 0.6
              }

              TextInput {
                id: searchInput
                anchors.fill: parent
                anchors.leftMargin: Style.space(9)
                anchors.rightMargin: Style.space(9)
                verticalAlignment: TextInput.AlignVCenter
                color: root.bar.foreground
                selectionColor: Color.accent
                font.family: "Noto Sans CJK SC"
                font.pixelSize: Style.font.bodySmall
                text: root.query
                onTextChanged: root.query = text
                onAccepted: if (root.spotifier) root.spotifier.search(text)
              }
            }

            FlatButton { id: searchButton; iconText: "󰍉"; foreground: Color.accent; onClicked: if (root.spotifier) root.spotifier.search(root.query) }
          }

          Text {
            width: parent.width
            visible: root.spotifier && (root.spotifier.searchLoading || root.spotifier.searchError !== "")
            text: root.spotifier ? (root.spotifier.searchLoading ? "SCANNING SPOTIFY…" : root.spotifier.searchError) : ""
            color: root.mutedColor()
            font.family: root.bar.fontFamily
            font.pixelSize: Style.font.caption
            horizontalAlignment: Text.AlignHCenter
          }

          ListView {
            id: searchResultsView
            property var items: root.spotifier ? root.spotifier.searchResults : []
            property string contextUri: ""
            width: parent.width
            height: parent.height - Style.space(39)
            clip: true
            spacing: 0
            model: items.length
            delegate: trackRow
          }
        }

        Item {
          anchors.fill: parent
          visible: root.tab === 2
          clip: true

          Text {
            anchors.centerIn: parent
            width: parent.width - Style.space(24)
            visible: !root.spotifier || root.spotifier.lyricsLoading || root.spotifier.lyricsError !== "" || (!root.hasTrack && root.spotifier.lyricsLines.length === 0 && root.spotifier.plainLyrics === "")
            text: !root.hasTrack ? "NO ACTIVE AUDIO SIGNAL" : (root.spotifier && root.spotifier.lyricsLoading ? "SYNCING LYRIC DATA…" : (root.spotifier ? root.spotifier.lyricsError : "SERVICE UNAVAILABLE"))
            color: root.mutedColor()
            font.family: root.bar.fontFamily
            font.pixelSize: Style.font.caption
            font.letterSpacing: 1
            horizontalAlignment: Text.AlignHCenter
            wrapMode: Text.WordWrap
          }

          ListView {
            id: lyricsView
            property var items: root.spotifier ? root.spotifier.lyricsLines : []
            anchors.fill: parent
            anchors.margins: Style.space(7)
            visible: items.length > 0
            clip: true
            spacing: 0
            model: items.length
            currentIndex: root.spotifier ? root.spotifier.currentLyricIndex : -1
            highlight: Item {}
            highlightFollowsCurrentItem: true
            highlightMoveVelocity: -1
            highlightMoveDuration: 650
            highlightResizeVelocity: -1
            highlightResizeDuration: 650
            preferredHighlightBegin: height * 0.45
            preferredHighlightEnd: height * 0.55
            highlightRangeMode: ListView.ApplyRange


            delegate: Item {
              required property int index
              readonly property var lineData: ListView.view && ListView.view.items[index] ? ListView.view.items[index] : ({})
              readonly property bool active: index === lyricsView.currentIndex
              readonly property real activeScale: active ? 1.65 : 1
              width: ListView.view ? ListView.view.width : Style.space(410)
              height: lyricLine.implicitHeight * activeScale + Style.space(14)
              Behavior on height { NumberAnimation { duration: 650; easing.type: Easing.InOutCubic } }
              Rectangle {
                anchors.left: parent.left
                anchors.verticalCenter: parent.verticalCenter
                width: Style.space(2)
                height: parent.height - Style.space(6)
                color: Color.accent
                opacity: active ? 1 : 0
                Behavior on opacity { NumberAnimation { duration: 520; easing.type: Easing.InOutCubic } }
              }
              Text {
                id: lyricLine
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
                anchors.leftMargin: Style.space(8)
                anchors.rightMargin: Style.space(8)
                text: lineData.text || "♪"
                color: active ? Color.accent : root.bar.foreground
                font.family: "Noto Sans CJK SC"
                font.pixelSize: Style.font.body
                font.weight: Font.Medium
                scale: parent.activeScale
                transformOrigin: Item.Center
                Behavior on color { ColorAnimation { duration: 560; easing.type: Easing.InOutCubic } }
                Behavior on scale { NumberAnimation { duration: 650; easing.type: Easing.InOutCubic } }
                horizontalAlignment: Text.AlignHCenter
                wrapMode: Text.WordWrap
                lineHeight: 1.25
                lineHeightMode: Text.ProportionalHeight
              }
            }
          }

          Flickable {
            id: plainLyricsView
            anchors.fill: parent
            anchors.margins: Style.space(10)
            visible: root.spotifier && root.spotifier.lyricsLines.length === 0 && root.spotifier.plainLyrics !== ""
            clip: true
            contentWidth: width
            contentHeight: plainLyricsText.implicitHeight

            Text {
              id: plainLyricsText
              width: plainLyricsView.width
              text: root.spotifier ? root.spotifier.plainLyrics : ""
              color: root.bar.foreground
              font.family: "Noto Sans CJK SC"
              font.pixelSize: Style.font.body
              horizontalAlignment: Text.AlignHCenter
              wrapMode: Text.WordWrap
              lineHeight: 1.4
              lineHeightMode: Text.ProportionalHeight
            }
        }
      }

        Rectangle {
          anchors.fill: parent
          z: 10
          visible: root.showShortcuts
          color: root.bar.background

          Column {
            anchors.fill: parent
            anchors.margins: Style.space(3)
            spacing: Style.space(5)

            Row {
              width: parent.width
              height: Style.space(24)

              Text {
                anchors.verticalCenter: parent.verticalCenter
                text: "KEYBOARD SHORTCUTS"
                color: Color.accent
                font.family: root.bar.fontFamily
                font.pixelSize: Style.font.caption
                font.bold: true
                font.letterSpacing: 1
              }
            }

            Grid {
              id: shortcutGrid
              width: parent.width
              columns: 2
              columnSpacing: Style.space(7)
              rowSpacing: 0

              Repeater {
                model: root.shortcutHelp.length

                Item {
                  required property int index
                  readonly property var shortcut: root.shortcutHelp[index]
                  width: (shortcutGrid.width - shortcutGrid.columnSpacing) / 2
                  height: Style.space(42)

                  Rectangle {
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.bottom: parent.bottom
                    height: 1
                    color: root.bar.foreground
                    opacity: 0.1
                  }

                  Row {
                    anchors.fill: parent
                    spacing: Style.space(7)

                    Rectangle {
                      width: Style.space(55)
                      height: Style.space(22)
                      anchors.verticalCenter: parent.verticalCenter
                      radius: Style.space(3)
                      color: root.selectedFill(true)

                      Text {
                        anchors.centerIn: parent
                        text: shortcut.keys
                        color: Color.accent
                        font.family: root.bar.fontFamily
                        font.pixelSize: Style.font.caption
                        font.bold: true
                      }
                    }

                    Text {
                      width: parent.width - Style.space(62)
                      anchors.verticalCenter: parent.verticalCenter
                      text: shortcut.action
                      color: root.bar.foreground
                      font.family: root.bar.fontFamily
                      font.pixelSize: Style.font.caption
                      elide: Text.ElideRight
                    }
                  }
                }
              }
            }
          }
        }
    }
  }
  }

  IpcHandler {
    target: "spotifierPanel"
    function open(): string { root.popupOpen = true; return "ok" }
    function close(): string { root.close(); return "ok" }
    function toggleTrackPlayback(): string { root.toggleTrackPlayback(); return "ok" }
    function toggleShortcuts(): string { root.toggleShortcutHelp(); return "ok" }
    function showTab(index: string): string {
      var value = Number(index)
      if (value >= 0 && value < root.tabLabels.length) root.selectTab(value)
      root.popupOpen = true
      return String(root.tab)
    }
    function state(): string {
      return JSON.stringify({
        open: root.popupOpen,
        tab: root.tab,
        shortcuts: root.showShortcuts,
        hasTrack: root.hasTrack,
        trackOverflow: trackText.needsScroll,
        listOffset: root.activeList() ? Math.round(root.activeList().contentY) : -1,
        trackOffset: Math.round(trackText.x)
      })
    }
  }

  Component {
    id: playlistRow

    Item {
      required property int index
      readonly property var modelData: ListView.view && ListView.view.items[index] ? ListView.view.items[index] : ({})
      width: ListView.view ? ListView.view.width : Style.space(410)
      height: Style.space(42)


      Rectangle {
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        height: 1
        color: root.bar.foreground
        opacity: 0.1
      }

      Row {
        anchors.fill: parent
        anchors.leftMargin: Style.space(3)
        anchors.rightMargin: Style.space(3)
        spacing: Style.space(7)

        Item {
          width: Style.space(32)
          height: Style.space(32)
          anchors.verticalCenter: parent.verticalCenter
          clip: true
          Image { anchors.fill: parent; source: modelData.image || ""; fillMode: Image.PreserveAspectCrop; asynchronous: true; visible: source !== "" }
          Text { anchors.centerIn: parent; visible: !(modelData.image); text: "󰲸"; color: Color.accent; font.family: root.bar.fontFamily; font.pixelSize: Style.font.bodySmall }
        }

        Column {
          width: parent.width - Style.space(39)
          anchors.verticalCenter: parent.verticalCenter
          spacing: 0
          Text { width: parent.width; text: modelData.name || "Untitled playlist"; color: root.bar.foreground; font.family: "Noto Sans CJK SC"; font.pixelSize: Style.font.bodySmall; font.bold: true; elide: Text.ElideRight }
          Text { width: parent.width; text: modelData.subtitle || "Playlist"; color: root.mutedColor(); font.family: root.bar.fontFamily; font.pixelSize: Style.font.caption; elide: Text.ElideRight }
        }
      }

      MouseArea {
        id: rowHover
        anchors.fill: parent
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor
        onClicked: if (root.spotifier) root.spotifier.loadPlaylist(modelData)
      }
    }
  }

  Component {
    id: trackRow

    Item {
      required property int index
      readonly property var modelData: ListView.view && ListView.view.items[index] ? ListView.view.items[index] : ({})
      readonly property string contextUri: ListView.view && ListView.view.contextUri ? String(ListView.view.contextUri) : ""
      readonly property string playbackContext: contextUri || String(modelData.context_uri || "")
      readonly property bool isCurrent: !!(root.spotifier && modelData.uri && modelData.uri === root.spotifier.trackUri)
      width: ListView.view ? ListView.view.width : Style.space(410)
      height: Style.space(42)


      Rectangle {
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        height: 1
        color: root.bar.foreground
        opacity: 0.1
      }

      Rectangle {
        anchors.left: parent.left
        anchors.verticalCenter: parent.verticalCenter
        width: Style.space(2)
        height: Style.space(26)
        color: Color.accent
        visible: isCurrent
      }

      Row {
        anchors.fill: parent
        anchors.leftMargin: isCurrent ? Style.space(7) : Style.space(3)
        anchors.rightMargin: Style.space(3)
        spacing: Style.space(7)

        Item {
          width: Style.space(32)
          height: Style.space(32)
          anchors.verticalCenter: parent.verticalCenter
          clip: true
          Image { anchors.fill: parent; source: modelData.image || ""; fillMode: Image.PreserveAspectCrop; asynchronous: true; visible: source !== "" }
          Text { anchors.centerIn: parent; visible: !(modelData.image); text: modelData.type === "track" ? "󰎆" : "󰝚"; color: Color.accent; font.family: root.bar.fontFamily; font.pixelSize: Style.font.bodySmall }
        }

        Column {
          width: parent.width - Style.space(39)
          anchors.verticalCenter: parent.verticalCenter
          spacing: 0
          Text { width: parent.width; text: modelData.name || ""; color: isCurrent ? Color.accent : root.bar.foreground; font.family: "Noto Sans CJK SC"; font.pixelSize: Style.font.bodySmall; font.bold: true; elide: Text.ElideRight }
          Text { width: parent.width; text: (modelData.type ? modelData.type.charAt(0).toUpperCase() + modelData.type.slice(1) + " · " : "") + (modelData.subtitle || ""); color: root.mutedColor(); font.family: "Noto Sans CJK SC"; font.pixelSize: Style.font.caption; elide: Text.ElideRight }
        }
      }

      MouseArea {
        id: rowHover
        anchors.fill: parent
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor
        onClicked: if (root.spotifier && modelData.uri) root.spotifier.playUri(modelData.uri, playbackContext)
      }
    }
  }
}
