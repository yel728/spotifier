"""Desktop media controls forwarded to the existing local playback authority."""
from __future__ import annotations

import hashlib
import threading

import dbus
import dbus.service
from dbus.mainloop.glib import DBusGMainLoop
from gi.repository import GLib

ROOT = "org.mpris.MediaPlayer2"
PLAYER = ROOT + ".Player"
PROPERTIES = "org.freedesktop.DBus.Properties"
PATH = "/org/mpris/MediaPlayer2"


def track_path(state):
    if not state["has_track"]:
        return dbus.ObjectPath(PATH + "/TrackList/NoTrack")
    return dbus.ObjectPath(PATH + "/track/" + hashlib.sha256(state["uri"].encode()).hexdigest())


class PlayerObject(dbus.service.Object):
    def __init__(self, bus, app):
        self.app = app
        self.name = dbus.service.BusName(ROOT + ".spotifier", bus, do_not_queue=True)
        super().__init__(bus, PATH)
        self.last = self.player_properties()

    def player_properties(self):
        state = self.app.playback.snapshot()
        metadata = dbus.Dictionary({}, signature="sv")
        if state["has_track"]:
            metadata.update({
                "mpris:trackid": track_path(state),
                "mpris:length": dbus.Int64(state["length_s"] * 1_000_000),
                "xesam:title": state["title"],
                "xesam:artist": dbus.Array([state["artist"]], signature="s"),
                "xesam:album": state["album"],
                "xesam:url": state["uri"],
                "mpris:artUrl": state["art_url"],
            })
        return {
            "PlaybackStatus": state["status"], "Metadata": metadata,
            "Position": dbus.Int64(state["position_s"] * 1_000_000),
            "Rate": dbus.Double(1), "MinimumRate": dbus.Double(1), "MaximumRate": dbus.Double(1),
            "Volume": dbus.Double(state["volume"]), "LoopStatus": state["repeat_mode"],
            "Shuffle": dbus.Boolean(state["shuffle"]), "CanControl": dbus.Boolean(True),
            **{key: dbus.Boolean(state["has_track"] and self.app.librespot.running)
               for key in ("CanPlay", "CanPause", "CanGoNext", "CanGoPrevious", "CanSeek")},
        }

    @dbus.service.method(PROPERTIES, in_signature="s", out_signature="a{sv}")
    def GetAll(self, interface):
        if interface == PLAYER:
            return self.player_properties()
        if interface == ROOT:
            return {"Identity": "Spotifier", "CanQuit": False, "CanRaise": False,
                    "HasTrackList": False, "SupportedUriSchemes": dbus.Array([], signature="s"),
                    "SupportedMimeTypes": dbus.Array([], signature="s")}
        raise dbus.exceptions.DBusException("Unknown interface", name=PROPERTIES + ".UnknownInterface")

    @dbus.service.method(PROPERTIES, in_signature="ss", out_signature="v")
    def Get(self, interface, name):
        properties = self.GetAll(interface)
        if name not in properties:
            raise dbus.exceptions.DBusException("Unknown property", name=PROPERTIES + ".UnknownProperty")
        return properties[name]

    @dbus.service.method(PROPERTIES, in_signature="ssv")
    def Set(self, interface, name, value):
        if interface == PLAYER:
            if name == "Volume":
                self.app.librespot.command(f"volume {round(max(0, min(1, float(value))) * 65535)}")
                return
            if name == "Shuffle":
                self.app.librespot.command(f"shuffle {str(bool(value)).lower()}")
                return
            if name == "LoopStatus" and value in ("None", "Track", "Playlist"):
                self.app.librespot.command(f"repeat_mode {value}")
                return
            if name == "Rate" and float(value) == 1:
                return
        raise dbus.exceptions.DBusException("Unsupported property value", name=PROPERTIES + ".InvalidArgs")

    @dbus.service.signal(PROPERTIES, signature="sa{sv}as")
    def PropertiesChanged(self, interface, changed, invalidated):
        pass

    def publish(self):
        current = self.player_properties()
        changed = {k: v for k, v in current.items() if k != "Position" and v != self.last.get(k)}
        self.last = current
        if changed:
            self.PropertiesChanged(PLAYER, changed, [])
        return GLib.SOURCE_CONTINUE

    def control(self, command):
        if self.app.playback.snapshot()["has_track"]:
            self.app.librespot.command(command)

    @dbus.service.method(ROOT)
    def Raise(self):
        pass

    @dbus.service.method(ROOT)
    def Quit(self):
        pass

    @dbus.service.signal(PLAYER, signature="x")
    def Seeked(self, position):
        pass

    @dbus.service.method(PLAYER)
    def PlayPause(self):
        self.control("play_pause")

    @dbus.service.method(PLAYER)
    def Play(self):
        self.control("play")

    @dbus.service.method(PLAYER)
    def Pause(self):
        self.control("pause")

    @dbus.service.method(PLAYER)
    def Stop(self):
        self.control("pause")
        self.control("seek 0")

    @dbus.service.method(PLAYER)
    def Next(self):
        self.control("next")

    @dbus.service.method(PLAYER)
    def Previous(self):
        self.control("previous")

    @dbus.service.method(PLAYER, in_signature="x")
    def Seek(self, offset):
        state = self.app.playback.snapshot()
        position = max(0, state["position_s"] + offset / 1_000_000)
        if position > state["length_s"]:
            self.Next()
        else:
            self.SetPosition(track_path(state), int(position * 1_000_000))

    @dbus.service.method(PLAYER, in_signature="ox")
    def SetPosition(self, track, position):
        state = self.app.playback.snapshot()
        if state["has_track"] and track == track_path(state) and 0 <= position <= state["length_s"] * 1_000_000:
            self.control(f"seek {round(position / 1000)}")
            self.Seeked(position)


class MprisService:
    def __init__(self, app):
        self.app = app
        self.ready = threading.Event()
        self.error = None
        self.loop = GLib.MainLoop()
        self.thread = threading.Thread(target=self._run, name="spotifier-mpris", daemon=True)

    def start(self):
        self.thread.start()
        if not self.ready.wait(5):
            raise RuntimeError("Desktop media controls did not start")
        if self.error:
            raise RuntimeError("Desktop media controls failed to start") from self.error

    def _run(self):
        bus = None
        timer = None
        player = None
        try:
            bus = dbus.SessionBus(private=True, mainloop=DBusGMainLoop())
            player = PlayerObject(bus, self.app)
            # Read only local event state; never poll Spotify for desktop controls.
            timer = GLib.timeout_add(250, player.publish)
            self.ready.set()
            self.loop.run()
        except Exception as error:
            self.error = error
            self.ready.set()
        finally:
            if timer is not None:
                GLib.source_remove(timer)
            if player is not None:
                player.remove_from_connection()
                player.name = None
            if bus is not None:
                bus.close()

    def stop(self):
        if self.thread.is_alive():
            GLib.idle_add(self.loop.quit)
            self.thread.join(timeout=3)
