import unittest
from unittest.mock import MagicMock, Mock, patch

from spotifierd.config import Config
from spotifierd.spotify import SpotifyAPI


class SpotifyApiTests(unittest.TestCase):
    @patch("spotifierd.spotify.urllib.request.urlopen")
    def test_whitespace_only_success_response_is_empty(self, urlopen) -> None:
        response = MagicMock()
        response.read.return_value = b"\n"
        urlopen.return_value.__enter__.return_value = response
        oauth = Mock()
        oauth.token.return_value = {"access_token": "token"}
        api = SpotifyAPI(Config(client_id="client"), oauth)

        self.assertIsNone(api.request("PUT", "/me/player/pause"))

    def test_playlist_track_playback_preserves_context_for_navigation(self) -> None:
        api = SpotifyAPI(Config(client_id="client"), Mock())
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

    def test_player_playlist_downloads_and_flattens_all_pages(self) -> None:
        player_oauth = Mock()
        api = SpotifyAPI(Config(client_id="client"), Mock(), player_oauth)
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
