import io
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import Mock, patch

from spotifierd.lyrics import Lyrics, best_synced_candidate, parse_synced_lyrics


class SyncedLyricsTests(unittest.TestCase):
    def test_parses_sorts_and_preserves_blank_lines(self) -> None:
        lyrics = "\n".join([
            "[ar:Example Artist]",
            "[01:02.50] Later line",
            "[00:03.125][00:05.00] Repeated line",
            "[00:10.00] ",
            "untimed text",
        ])

        self.assertEqual(
            parse_synced_lyrics(lyrics),
            [
                {"time": 3.125, "text": "Repeated line"},
                {"time": 5.0, "text": "Repeated line"},
                {"time": 10.0, "text": ""},
                {"time": 62.5, "text": "Later line"},
            ],
        )

    def test_empty_or_plain_lyrics_have_no_synced_lines(self) -> None:
        self.assertEqual(parse_synced_lyrics(""), [])
        self.assertEqual(parse_synced_lyrics("First line\nSecond line"), [])


class LrclibCandidateTests(unittest.TestCase):
    def test_matches_one_spotify_artist_and_nearest_duration(self) -> None:
        candidates = [
            {
                "trackName": "扁舟情侶",
                "artistName": "Different Artist",
                "albumName": "天涯歌女",
                "duration": 204,
                "syncedLyrics": "[00:01.00]Wrong artist",
            },
            {
                "trackName": "扁舟情侶",
                "artistName": "陳松伶",
                "albumName": "天涯歌女",
                "duration": 204,
                "syncedLyrics": "[00:01.00]Matched",
            },
        ]

        result = best_synced_candidate(
            candidates, "扁舟情侶", "陳松伶, 溫兆倫", "天涯歌女", 204.149
        )

        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result["artistName"], "陳松伶")


    def test_accepts_exact_album_when_artist_metadata_differs(self) -> None:
        candidate = {
            "trackName": "龍華的桃花",
            "artistName": "陳松齡",
            "albumName": "天涯歌女",
            "duration": 180.61,
            "syncedLyrics": "[00:01.00]Matched",
        }

        result = best_synced_candidate(
            [candidate], "龍華的桃花", "陳松伶", "天涯歌女", 180.651
        )

        self.assertEqual(result, candidate)
    def test_rejects_wrong_title_artist_and_duration(self) -> None:
        candidates = [
            {
                "trackName": "Other Track",
                "artistName": "Artist",
                "duration": 180,
                "syncedLyrics": "[00:01.00]Wrong title",
            },
            {
                "trackName": "Track",
                "artistName": "Other Artist",
                "duration": 180,
                "syncedLyrics": "[00:01.00]Wrong artist",
            },
            {
                "trackName": "Track",
                "artistName": "Artist",
                "duration": 220,
                "syncedLyrics": "[00:01.00]Wrong duration",
            },
        ]

        self.assertIsNone(
            best_synced_candidate(candidates, "Track", "Artist", "Album", 180)
        )

    @patch("spotifierd.lyrics.time.sleep")
    @patch.object(Lyrics, "_lrclib_request")
    def test_exact_miss_falls_back_to_structured_search(self, request, sleep) -> None:
        missing = urllib.error.HTTPError(
            "https://lrclib.net/api/get", 404, "missing", {}, io.BytesIO()
        )
        request.side_effect = [
            missing,
            [{
                "trackName": "扁舟情侶",
                "artistName": "陳松伶",
                "albumName": "天涯歌女",
                "duration": 204,
                "plainLyrics": "Matched",
                "syncedLyrics": "[00:01.00]Matched",
            }],
        ]

        result = Lyrics._fetch_lrclib(
            "扁舟情侶", "陳松伶, 溫兆倫", "天涯歌女", 204.149
        )

        self.assertEqual(result["lines"], [{"time": 1.0, "text": "Matched"}])
        self.assertEqual(
            request.call_args_list[1].args[1],
            {"track_name": "扁舟情侶"},
        )
        sleep.assert_called_once_with(0.25)


    @patch("spotifierd.lyrics.time.sleep")
    @patch.object(Lyrics, "_lrclib_request")
    def test_exact_plain_result_still_searches_for_synced_version(self, request, sleep) -> None:
        request.side_effect = [
            {
                "trackName": "Track",
                "artistName": "Artist",
                "albumName": "Album",
                "duration": 180,
                "plainLyrics": "Plain",
                "syncedLyrics": None,
            },
            [{
                "trackName": "Track",
                "artistName": "Artist",
                "albumName": "Album",
                "duration": 180,
                "plainLyrics": "Synced",
                "syncedLyrics": "[00:02.00]Synced",
            }],
        ]

        result = Lyrics._fetch_lrclib("Track", "Artist", "Album", 180)

        self.assertEqual(result["lines"], [{"time": 2.0, "text": "Synced"}])
        self.assertEqual(request.call_count, 2)
        sleep.assert_called_once_with(0.25)


class LyricsLookupTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.database = Path(self.temporary.name) / "lyrics.sqlite3"

    def test_local_spotify_timed_lines_are_preserved(self) -> None:
        fetcher = Mock(return_value={
            "provider": "Musixmatch",
            "synced": True,
            "lines": [
                {"time_ms": 1250, "text": "First"},
                {"time_ms": 63500, "text": "Second"},
            ],
        })
        lyrics = Lyrics(self.database, spotify_fetcher=fetcher)

        result = lyrics._fetch_spotify("spotify:track:track-id")

        fetcher.assert_called_once_with("spotify:track:track-id")
        self.assertEqual(
            result["lines"],
            [
                {"time": 1.25, "text": "First"},
                {"time": 63.5, "text": "Second"},
            ],
        )
        self.assertEqual(
            result["synced"],
            "[00:01.250]First\n[01:03.500]Second",
        )
        self.assertEqual(result["source"], "spotify")

    def test_local_spotify_unsynced_lines_remain_plain(self) -> None:
        lyrics = Lyrics(
            self.database,
            spotify_fetcher=Mock(return_value={
                "provider": "Musixmatch",
                "synced": False,
                "lines": [
                    {"time_ms": 0, "text": "First"},
                    {"time_ms": 0, "text": "Second"},
                ],
            }),
        )

        result = lyrics._fetch_spotify("spotify:track:track-id")

        self.assertEqual(result["plain"], "First\nSecond")
        self.assertEqual(result["lines"], [])
        self.assertEqual(result["synced"], "")

    def test_lrclib_synced_lyrics_replace_spotify_plain_lyrics_and_persist(self) -> None:
        lyrics = Lyrics(self.database)
        lyrics._fetch_spotify = Mock(return_value={
            "found": True,
            "instrumental": False,
            "plain": "Spotify plain lyric",
            "lines": [],
            "synced": "",
            "source": "spotify",
        })
        lyrics._fetch_lrclib = Mock(return_value={
            "found": True,
            "instrumental": False,
            "plain": "Synced line",
            "lines": [{"time": 1.5, "text": "Synced line"}],
            "synced": "[00:01.50]Synced line",
            "source": "lrclib",
        })

        result = lyrics.get(
            "Track", "Artist", "Album", 180, "spotify:track:track-id"
        )

        self.assertEqual(result["source"], "lrclib")
        self.assertEqual(result["lines"], [{"time": 1.5, "text": "Synced line"}])
        lyrics.invalidate()
        lyrics._fetch = Mock(side_effect=AssertionError("network fetch repeated"))
        self.assertEqual(
            lyrics.get("Track", "Artist", "Album", 180, "spotify:track:track-id"),
            result,
        )

    def test_spotify_synced_lyrics_skip_lrclib_and_persist(self) -> None:
        lyrics = Lyrics(self.database)
        lyrics._fetch_spotify = Mock(return_value={
            "found": True,
            "instrumental": False,
            "plain": "Spotify synced",
            "lines": [{"time": 2.0, "text": "Spotify synced"}],
            "synced": "[00:02.00]Spotify synced",
            "source": "spotify",
        })
        lyrics._fetch_lrclib = Mock()

        result = lyrics.get(
            "Track", "Artist", "Album", 180, "spotify:track:track-id"
        )

        self.assertEqual(result["source"], "spotify")
        lyrics._fetch_lrclib.assert_not_called()
        self.assertEqual(
            Lyrics(self.database).get(
                "Track", "Artist", "Album", 180, "spotify:track:track-id"
            )["lines"],
            [{"time": 2.0, "text": "Spotify synced"}],
        )

    def test_spotify_plain_lyrics_win_when_lrclib_has_no_synced_version(self) -> None:
        lyrics = Lyrics(self.database)
        spotify = {
            "found": True,
            "instrumental": False,
            "plain": "Spotify plain lyric",
            "lines": [],
            "synced": "",
            "source": "spotify",
        }
        lyrics._fetch_spotify = Mock(return_value=spotify)
        lyrics._fetch_lrclib = Mock(return_value={
            "found": True,
            "instrumental": False,
            "plain": "LRCLIB plain lyric",
            "lines": [],
            "synced": "",
            "source": "lrclib",
        })

        result = lyrics.get(
            "Track", "Artist", "Album", 180, "spotify:track:track-id"
        )

        self.assertEqual(result["plain"], "Spotify plain lyric")
        lyrics._fetch_lrclib.assert_called_once_with("Track", "Artist", "Album", 180)


    def test_plain_lyrics_use_short_memory_cache_ttl(self) -> None:
        lyrics = Lyrics(self.database)
        lyrics._fetch = Mock(return_value={
            "found": True,
            "instrumental": False,
            "plain": "Plain lyric",
            "lines": [],
            "synced": "",
            "source": "spotify",
        })

        with patch.object(lyrics.cache, "set") as cache_set:
            lyrics.get("Track", "Artist", "Album", 180, "spotify:track:track-id")

        cache_set.assert_called_once()
        self.assertEqual(cache_set.call_args.args[2], 900.0)

if __name__ == "__main__":
    unittest.main()
