import unittest

from spotifierd.lyrics import parse_synced_lyrics


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


if __name__ == "__main__":
    unittest.main()
