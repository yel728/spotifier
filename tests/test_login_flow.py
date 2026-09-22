import tempfile
import unittest
from unittest.mock import Mock
from pathlib import Path
from spotifierd.config import Config
from spotifierd.server import Application, Handler


class LoginFlowTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.app = Application(Config(player_cache=self.directory.name))
        self.app.oauth = Mock(logged_in=False)
        self.app.librespot = Mock(running=True, player_ready=False, login_url='https://accounts.spotify.com/authorize?playback')
        self.app.librespot.ready = False

    def tearDown(self):
        self.app.library.close()
        self.directory.cleanup()

    def test_both_permissions_required_for_completion(self):
        self.assertEqual(self.app.auth_status()['stage'], 'playback')
        self.app.oauth.logged_in = True
        self.assertEqual(self.app.auth_status()['stage'], 'playback')
        self.app.librespot.player_ready = True
        self.app.librespot.ready = True
        self.assertEqual(self.app.auth_status()['stage'], 'complete')

    def test_playback_then_library(self):
        self.app.librespot.player_ready = True
        self.app.librespot.ready = True
        self.assertEqual(self.app.auth_status()['stage'], 'library')
        self.app.oauth.logged_in = True
        self.assertEqual(self.app.auth_status()['stage'], 'complete')

    def test_reconnecting_is_not_reported_as_complete(self):
        self.app.oauth.logged_in = True
        self.app.librespot.login_url = ''
        self.assertEqual(self.app.auth_status()['stage'], 'connecting')

    def test_stopped_player_is_not_connected(self):
        self.app.librespot.running = False
        self.app.librespot.player_ready = True
        self.app.librespot.ready = False
        self.assertFalse(self.app.auth_status()['playback'])

    def handler(self, path):
        handler = object.__new__(Handler)
        handler.app = self.app
        handler.path = path
        handler.send_response = Mock()
        handler.send_header = Mock()
        handler.end_headers = Mock()
        return handler

    def test_login_page_does_not_start_or_reset_authorization(self):
        response = self.handler('/auth/login')._route_get()
        self.assertEqual(response[0], 200)
        self.assertIn('text/html', response[2])
        self.app.oauth.login_url.assert_not_called()

    def test_authorize_uses_current_step(self):
        handler = self.handler('/auth/authorize')
        handler._route_get()
        handler.send_header.assert_called_with('Location', self.app.librespot.login_url)
        self.app.oauth.login_url.assert_not_called()
        self.app.librespot.player_ready = True
        self.app.librespot.ready = True
        self.app.oauth.login_url.return_value = 'https://accounts.spotify.com/authorize?library'
        handler._route_get()
        handler.send_header.assert_called_with('Location', self.app.oauth.login_url.return_value)

    def test_authorize_after_completion_returns_to_setup(self):
        self.app.librespot.player_ready = True
        self.app.librespot.ready = True
        self.app.oauth.logged_in = True
        handler = self.handler('/auth/authorize')
        handler._route_get()
        handler.send_header.assert_called_with('Location', '/auth/login')
        self.app.oauth.login_url.assert_not_called()
