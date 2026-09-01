import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from spotifierd.config import Config
from spotifierd.oauth import OAuth, SpotifyPlayerOAuth


class SpotifyPlayerOAuthTests(unittest.TestCase):
    def test_login_url_starts_authenticator_and_reuses_pending_flow(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            credentials = Path(directory) / "credentials.json"
            process = Mock()
            process.poll.return_value = None
            process.stdout.readline.return_value = "Browse to: https://accounts.spotify.com/authorize?state=test\n"

            with patch("spotifierd.oauth.subprocess.Popen", return_value=process) as popen:
                oauth = SpotifyPlayerOAuth(credentials)
                first = oauth.login_url()
                second = oauth.login_url()

            self.assertEqual(first, "https://accounts.spotify.com/authorize?state=test")
            self.assertEqual(second, first)
            popen.assert_called_once()

    def test_existing_credentials_skip_authenticator(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            credentials = Path(directory) / "credentials.json"
            credentials.write_text("{}")
            oauth = SpotifyPlayerOAuth(credentials)

            with patch("spotifierd.oauth.subprocess.Popen") as popen:
                self.assertTrue(oauth.logged_in)
                self.assertEqual(oauth.login_url(), "")

            popen.assert_not_called()

    def test_logout_removes_both_oauth_tokens(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            primary_token = root / "token.json"
            playlist_token = root / "user_client_token.json"
            primary_token.write_text("{}")
            playlist_token.write_text("{}")

            with patch("spotifierd.oauth.TOKEN_PATH", primary_token):
                OAuth(Config()).logout()
            SpotifyPlayerOAuth(playlist_token).logout()

            self.assertFalse(primary_token.exists())
            self.assertFalse(playlist_token.exists())


if __name__ == "__main__":
    unittest.main()
