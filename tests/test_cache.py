import tempfile
import unittest
from unittest.mock import Mock, patch
from pathlib import Path

from spotifierd.cache import TTLCache
from spotifierd.config import Config
from spotifierd.library import Library
from spotifierd.lyrics import Lyrics
from spotifierd.spotify import SpotifyAPI


class TTLCacheTests(unittest.TestCase):
    @patch("spotifierd.cache.time.monotonic", side_effect=[0.0, 1.0, 6.0])
    def test_entry_expires_at_its_ttl(self, _monotonic) -> None:
        cache: TTLCache[str, str] = TTLCache(2)
        cache.set("key", "value", 5.0)

        hit = cache.get("key")
        self.assertIsNotNone(hit)
        assert hit is not None
        self.assertEqual(hit.value, "value")
        self.assertIsNone(cache.get("key"))

    def test_oldest_entry_is_evicted_at_capacity(self) -> None:
        cache: TTLCache[str, int] = TTLCache(2)
        cache.set("first", 1, 60)
        cache.set("second", 2, 60)
        cache.set("third", 3, 60)

        self.assertIsNone(cache.get("first"))
        second = cache.get("second")
        third = cache.get("third")
        self.assertIsNotNone(second)
        self.assertIsNotNone(third)
        assert second is not None and third is not None
        self.assertEqual(second.value, 2)
        self.assertEqual(third.value, 3)


class SpotifyCacheTests(unittest.TestCase):
    def test_playback_cache_is_reused_then_invalidated_by_mutation(self) -> None:
        api = SpotifyAPI(Config(), Mock())
        playback = {
            "is_playing": True,
            "progress_ms": 1000,
            "item": {"duration_ms": 10000},
        }
        api.request = Mock(return_value=playback)

        first = api.playback()
        second = api.playback()
        self.assertIsNotNone(first)
        self.assertIsNotNone(second)
        assert first is not None and second is not None
        self.assertEqual(first["progress_ms"], 1000)
        self.assertGreaterEqual(second["progress_ms"], 1000)
        self.assertEqual(api.request.call_count, 1)

        api.local_device_id = Mock(return_value="device")
        api.pause()
        api.playback()
        api.playback()

        self.assertEqual(api.request.call_count, 4)

    def test_device_lookup_reuses_cached_device_list(self) -> None:
        api = SpotifyAPI(Config(device_name="Spotifier"), Mock())
        api.request = Mock(return_value={"devices": [{"id": "device", "name": "Spotifier"}]})
        api._discover_local_device_id = Mock(side_effect=OSError)

        self.assertEqual(api.local_device_id(), "device")
        self.assertEqual(api.local_device_id(), "device")
        api.request.assert_called_once_with("GET", "/me/player/devices")


class LibraryCacheTests(unittest.TestCase):
    def test_search_cache_normalizes_queries_and_invalidates(self) -> None:
        spotify = Mock()
        spotify.search.return_value = {"tracks": {"items": []}}
        library = Library(spotify)
        self.addCleanup(library.close)

        library.search("Daft Punk")
        library.search("  daft punk  ")
        self.assertEqual(spotify.search.call_count, 1)

        library.invalidate()
        library.search("Daft Punk")
        self.assertEqual(spotify.search.call_count, 2)

    def test_search_track_preserves_album_playback_context(self) -> None:
        spotify = Mock()
        spotify.search.return_value = {
            "tracks": {
                "items": [{
                    "name": "Track",
                    "uri": "spotify:track:track",
                    "artists": [{"name": "Artist"}],
                    "album": {"uri": "spotify:album:album", "images": []},
                }]
            }
        }
        library = Library(spotify)
        self.addCleanup(library.close)

        result = library.search("Track")

        self.assertEqual(result[0]["context_uri"], "spotify:album:album")


class LyricsCacheTests(unittest.TestCase):
    def test_lyrics_cache_reuses_result_and_invalidates(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            lyrics = Lyrics(Path(directory) / "lyrics.sqlite3")
            result = {"found": True, "instrumental": False, "plain": "text", "lines": []}
            lyrics._fetch = Mock(return_value=result)

            self.assertEqual(lyrics.get("Track", "Artist", "Album", 180), {**result, "source": ""})
            self.assertEqual(lyrics.get("track", "artist", "album", 180), {**result, "source": ""})
            self.assertEqual(lyrics._fetch.call_count, 1)

            lyrics.invalidate()
            lyrics.get("Track", "Artist", "Album", 180)
            self.assertEqual(lyrics._fetch.call_count, 2)


if __name__ == "__main__":
    unittest.main()
