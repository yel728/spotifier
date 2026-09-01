import unittest
from unittest.mock import Mock, patch

from spotifierd.config import Config
from spotifierd.playback import normalize_playback
from spotifierd.spotify import SpotifyAPI


class PlaybackTests(unittest.TestCase):
    def test_normalizes_web_api_playback(self) -> None:
        state = normalize_playback({
            "device": {"volume_percent": 49},
            "repeat_state": "context",
            "shuffle_state": True,
            "progress_ms": 12500,
            "is_playing": True,
            "item": {
                "uri": "spotify:track:one-more-time",
                "name": "One More Time",
                "artists": [{"name": "Daft Punk"}],
                "duration_ms": 320000,
                "album": {"name": "Discovery", "images": [{"url": "cover"}]},
            },
        })
        self.assertEqual(state["title"], "One More Time")
        self.assertEqual(state["uri"], "spotify:track:one-more-time")
        self.assertEqual(state["status"], "Playing")
        self.assertEqual(state["position_s"], 12.5)
        self.assertEqual(state["repeat_mode"], "Playlist")
        self.assertTrue(state["shuffle"])

    def test_empty_playback_is_stopped(self) -> None:
        state = normalize_playback(None)
        self.assertFalse(state["has_track"])
        self.assertEqual(state["uri"], "")
        self.assertEqual(state["status"], "Stopped")

    def test_pause_targets_only_configured_device(self) -> None:
        api = SpotifyAPI(Config(device_name="Spotifier"), Mock())
        with patch.object(api, "devices", return_value=[{"id": "device-1", "name": "Spotifier"}]), patch.object(api, "request") as request:
            api.pause()
        request.assert_called_once_with("PUT", "/me/player/pause?device_id=device-1")


if __name__ == "__main__":
    unittest.main()
