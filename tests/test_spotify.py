import io
import unittest
import urllib.error
from threading import Event, Thread
from unittest.mock import MagicMock, Mock, patch

from spotifierd.config import Config
from spotifierd.library import Library
from spotifierd.spotify import SpotifyAPI


class SpotifyApiTests(unittest.TestCase):
    @patch("spotifierd.spotify.urllib.request.urlopen")
    def test_whitespace_only_success_response_is_empty(self, urlopen) -> None:
        response = MagicMock()
        response.read.return_value = b"\n"
        urlopen.return_value.__enter__.return_value = response
        oauth = Mock()
        oauth.token.return_value = {"access_token": "token"}
        api = SpotifyAPI(Config(), oauth)

        self.assertIsNone(api.request("PUT", "/me/player/pause"))

    @patch("spotifierd.spotify.time.sleep")
    @patch("spotifierd.spotify.urllib.request.urlopen")
    def test_request_retries_rate_limit_once(self, urlopen, sleep) -> None:
        limited = urllib.error.HTTPError(
            "https://api.spotify.com/v1/search",
            429,
            "rate limited",
            {"Retry-After": "0"},
            io.BytesIO(b"limited"),
        )
        success = MagicMock()
        success.__enter__.return_value.read.return_value = b'{"tracks": {}}'
        urlopen.side_effect = [limited, success]
        oauth = Mock()
        oauth.token.return_value = {"access_token": "token"}

        result = SpotifyAPI(Config(), oauth).request("GET", "/search?q=test")

        self.assertEqual(result, {"tracks": {}})
        self.assertEqual(urlopen.call_count, 2)
        sleep.assert_called_once_with(0.1)

    @patch("spotifierd.spotify.time.sleep")
    @patch("spotifierd.spotify.urllib.request.urlopen")
    def test_playback_poll_does_not_amplify_rate_limit(self, urlopen, sleep) -> None:
        urlopen.side_effect = urllib.error.HTTPError(
            "https://api.spotify.com/v1/me/player",
            429,
            "rate limited",
            {"Retry-After": "5"},
            io.BytesIO(b"limited"),
        )
        oauth = Mock()
        oauth.token.return_value = {"access_token": "token"}

        with self.assertRaisesRegex(RuntimeError, "Spotify rate limit: retry in 5 seconds"):
            SpotifyAPI(Config(), oauth).playback(force=True)

        self.assertEqual(urlopen.call_count, 1)
        sleep.assert_not_called()

    @patch("spotifierd.spotify.time.sleep")
    @patch("spotifierd.spotify.urllib.request.urlopen")
    def test_playback_mutation_reports_rate_limit_without_sleeping(self, urlopen, sleep) -> None:
        limited = urllib.error.HTTPError(
            "https://api.spotify.com/v1/me/player/play",
            429,
            "rate limited",
            {"Retry-After": "2"},
            io.BytesIO(b"limited"),
        )
        urlopen.side_effect = limited
        oauth = Mock()
        oauth.token.return_value = {"access_token": "token"}

        with self.assertRaisesRegex(RuntimeError, "Spotify rate limit: retry in 2 seconds"):
            SpotifyAPI(Config(), oauth).request(
                "PUT", "/me/player/play?device_id=device", {}
            )

        self.assertEqual(urlopen.call_count, 1)
        self.assertEqual(urlopen.call_args.kwargs["timeout"], 3)
        sleep.assert_not_called()

    def test_local_device_identity_is_reused(self) -> None:
        api = SpotifyAPI(Config(device_name="Spotifier"), Mock())
        api._discover_local_device_id = Mock(return_value="device-id")
        api.devices = Mock()

        self.assertEqual(api.local_device_id(), "device-id")
        self.assertEqual(api.local_device_id(), "device-id")

        api._discover_local_device_id.assert_called_once_with()
        api.devices.assert_not_called()

    @patch("spotifierd.spotify.urllib.request.urlopen")
    def test_local_device_identity_comes_from_librespot(self, urlopen) -> None:
        response = MagicMock()
        response.__enter__.return_value.read.return_value = (
            b'{"remoteName":"Spotifier","deviceID":"local-device"}'
        )
        urlopen.return_value = response

        device_id = SpotifyAPI(Config(librespot_zeroconf_port=9876), Mock())._discover_local_device_id()

        self.assertEqual(device_id, "local-device")
        urlopen.assert_called_once_with("http://127.0.0.1:9876/?action=getInfo", timeout=2)

    @patch("spotifierd.spotify.time.sleep")
    @patch("spotifierd.spotify.urllib.request.urlopen")
    def test_player_request_retries_rate_limit_once(self, urlopen, sleep) -> None:
        limited = urllib.error.HTTPError(
            "https://api.spotify.com/v1/me/playlists",
            429,
            "rate limited",
            {"Retry-After": "1"},
            io.BytesIO(b"limited"),
        )
        success = MagicMock()
        success.__enter__.return_value.read.return_value = b'{"items": []}'
        urlopen.side_effect = [limited, success]
        oauth = Mock()
        oauth.token.return_value = {"access_token": "token"}

        result = SpotifyAPI(Config(), oauth).player_request("https://api.spotify.com/v1/me/playlists")

        self.assertEqual(result, {"items": []})
        self.assertEqual(urlopen.call_count, 2)
        sleep.assert_called_once_with(1.0)

    def test_playlist_track_playback_preserves_context_for_navigation(self) -> None:
        api = SpotifyAPI(Config(), Mock())
        api.local_device_id = Mock(return_value="device")
        api.request = Mock()

        api.play_uri("spotify:track:track-id", "spotify:playlist:playlist-id")

        api.request.assert_called_once_with(
            "PUT",
            "/me/player/play?device_id=device",
            {
                "context_uri": "spotify:playlist:playlist-id",
                "offset": {"uri": "spotify:track:track-id"},
            },
        )

    def test_mutation_does_not_wait_for_inflight_playback_poll(self) -> None:
        poll_started = Event()
        release_poll = Event()
        mutation_sent = Event()
        api = SpotifyAPI(Config(), Mock())
        api.local_device_id = Mock(return_value="device")

        def request(method, path, body=None):
            if path == "/me/player":
                poll_started.set()
                release_poll.wait(1)
                return None
            mutation_sent.set()
            return None

        api.request = Mock(side_effect=request)
        poll = Thread(target=api.playback)
        mutation = Thread(target=api.pause)
        poll.start()
        self.assertTrue(poll_started.wait(0.2))
        try:
            mutation.start()
            self.assertTrue(mutation_sent.wait(0.2))
        finally:
            release_poll.set()
            poll.join(1)
            mutation.join(1)

    def test_player_album_downloads_all_tracks_with_album_metadata(self) -> None:
        api = SpotifyAPI(Config(), Mock())
        api.player_request = Mock(side_effect=[
            {
                "id": "album-id",
                "name": "Album",
                "uri": "spotify:album:album-id",
                "images": [{"url": "cover"}],
                "tracks": {
                    "items": [{"id": "one", "name": "One"}],
                    "next": "https://api.spotify.com/v1/next-page",
                },
            },
            {"items": [{"id": "two", "name": "Two"}], "next": None},
        ])

        result = api.player_album("album-id")

        self.assertEqual([track["id"] for track in result["tracks"]], ["one", "two"])
        self.assertTrue(all(track["album"]["name"] == "Album" for track in result["tracks"]))

    def test_library_loads_album_tracks_as_playable_results(self) -> None:
        spotify = Mock()
        spotify.player_album.return_value = {
            "tracks": [{
                "id": "track-id",
                "uri": "spotify:track:track-id",
                "name": "Track",
                "artists": [{"name": "Artist"}],
                "album": {"id": "album-id", "images": [{"url": "cover"}]},
            }],
        }
        library = Library(spotify)
        try:
            tracks, pending, refreshing, version = library.tracks("spotify:album:album-id")
        finally:
            library.close()

        spotify.player_album.assert_called_once_with("album-id")
        spotify.player_playlist.assert_not_called()
        self.assertFalse(pending)
        self.assertFalse(refreshing)
        self.assertTrue(version)
        self.assertEqual(tracks, [{
            "type": "track",
            "name": "Track",
            "subtitle": "Artist",
            "uri": "spotify:track:track-id",
            "image": "cover",
        }])

    def test_player_playlist_downloads_and_flattens_all_pages(self) -> None:
        player_oauth = Mock()
        api = SpotifyAPI(Config(), player_oauth)
        api.player_request = Mock(side_effect=[
            {
                "items": [{"track": {"id": "one"}}],
                "next": "https://api.spotify.com/v1/next-page",
            },
            {
                "items": [{"track": {"id": "two"}}],
                "next": None,
            },
        ])

        self.assertEqual(api.player_playlist("playlist-id"), {
            "tracks": [{"id": "one"}, {"id": "two"}],
        })
        self.assertEqual(api.player_request.call_count, 2)


if __name__ == "__main__":
    unittest.main()
