import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from spotifierd.library import Library


class CollectionRetentionTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / 'collections.json'
        patcher = patch('spotifierd.library.COLLECTION_CACHE_PATH', self.path)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.spotify = Mock()
        self.library = Library(self.spotify)
        self.addCleanup(self.library.close)

    def store(self, key='playlist:one'):
        self.library._store_tracks(key, [{'uri': 'spotify:track:one', 'name': 'Saved'}], {})

    def test_more_than_24_collections_remain_on_disk_and_reload_without_network(self):
        for index in range(30):
            self.store(f'playlist:{index}')
        self.assertEqual(len(self.library.playlist_cache), 24)
        self.assertEqual(len(json.loads(self.path.read_text())), 30)
        self.assertEqual(self.library.cached_tracks('spotify:playlist:0')[0][0]['name'], 'Saved')
        self.spotify.player_playlist.assert_not_called()
        self.library.close()
        restarted = Library(self.spotify)
        self.addCleanup(restarted.close)
        self.assertEqual(restarted.cached_tracks('spotify:playlist:0')[0][0]['name'], 'Saved')
        restarted._store_tracks('album:new', [], {})
        self.assertEqual(len(json.loads(self.path.read_text())), 31)

    def test_age_and_normal_invalidation_keep_snapshot(self):
        self.store()
        before = self.path.read_bytes()
        with patch('spotifierd.cache.time.monotonic', return_value=10**15):
            self.assertIsNotNone(self.library.playlist_cache.get('playlist:one'))
            self.library.invalidate()
            with patch.object(self.library, '_schedule_collection_refresh') as refresh:
                tracks = self.library.tracks('spotify:playlist:one')[0]
            refresh.assert_called_once()
        self.assertEqual(tracks[0]['name'], 'Saved')
        self.assertEqual(self.path.read_bytes(), before)

    def test_failed_or_malformed_refresh_keeps_existing_data(self):
        self.store()
        before = self.path.read_bytes()
        self.spotify.player_playlist.side_effect = RuntimeError('offline')
        self.library._refresh_tracks('spotify:playlist:one', 'playlist:one', 0)
        self.spotify.player_playlist.side_effect = None
        self.spotify.player_playlist.return_value = {'error': 'unavailable'}
        self.library._refresh_tracks('spotify:playlist:one', 'playlist:one', 0)
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(self.library.cached_tracks('spotify:playlist:one')[0][0]['name'], 'Saved')

    def test_confirmed_empty_collection_replaces_old_tracks(self):
        self.store()
        self.spotify.player_playlist.return_value = {'tracks': []}
        self.library._refresh_tracks('spotify:playlist:one', 'playlist:one', 0)
        self.assertEqual(self.library.cached_tracks('spotify:playlist:one')[0], [])
        self.assertEqual(json.loads(self.path.read_text())['playlist:one'], [])

    def test_explicit_logout_clears_snapshots_and_rejects_old_refresh(self):
        self.store()
        self.library.invalidate(clear_collections=True)
        self.spotify.player_playlist.return_value = {'tracks': []}
        self.library._refresh_tracks('spotify:playlist:one', 'playlist:one', 0)
        self.assertFalse(self.path.exists())
        self.assertEqual(len(self.library.playlist_cache), 0)
