import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from spotifierd.oauth import SpotifyPlayerOAuth


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

    def test_valid_token_is_available_for_all_api_requests(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            token = Path(directory) / "user_client_token.json"
            token.write_text(
                '{"access_token":"token","refresh_token":"refresh",'
                '"expires_at":"2099-01-01T00:00:00Z"}'
            )

            self.assertEqual(SpotifyPlayerOAuth(token).token()["access_token"], "token")

    def test_logout_removes_oauth_token(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            token = Path(directory) / "user_client_token.json"
            token.write_text("{}")

            SpotifyPlayerOAuth(token).logout()

            self.assertFalse(token.exists())


if __name__ == "__main__":
    unittest.main()
