import unittest

from qobuz_cli.formatters import (
    compact_album_detail,
    compact_album_suggestions,
    compact_artist_detail,
    compact_new_releases,
    compact_search,
)


class FormatterTests(unittest.TestCase):
    def test_album_description_is_plain_text_and_can_be_omitted(self) -> None:
        payload = {
            "id": "a",
            "title": "Album",
            "description": "<p>A&nbsp;review.</p><p>Second paragraph.</p>",
            "description_language": "en",
            "tracks": {"items": []},
        }
        result = compact_album_detail(payload)
        self.assertEqual(result["description"], "A review. Second paragraph.")
        self.assertEqual(result["description_language"], "en")
        self.assertNotIn(
            "description", compact_album_detail(payload, include_description=False)
        )

    def test_album_suggestions_support_their_distinct_schema(self) -> None:
        payload = {
            "albums": {
                "items": [
                    {
                        "id": "suggested",
                        "title": "Suggestion",
                        "artists": [{"id": 1, "name": "Artist"}],
                        "dates": {"original": "2026-01-02"},
                        "track_count": 9,
                        "audio_info": {
                            "maximum_bit_depth": 24,
                            "maximum_sampling_rate": 96,
                        },
                    }
                ]
            }
        }
        self.assertEqual(
            compact_album_suggestions(payload),
            [
                {
                    "id": "suggested",
                    "title": "Suggestion",
                    "artist": "Artist",
                    "date": "2026-01-02",
                    "tracks": 9,
                    "bit_depth": 24,
                    "sample_rate": 96,
                }
            ],
        )

    def test_new_releases_uses_compact_album_schema(self) -> None:
        payload = {
            "has_more": True,
            "items": [
                {
                    "id": "new",
                    "title": "New Album",
                    "artists": [{"id": 1, "name": "Artist"}],
                    "dates": {"original": "2026-08-21"},
                    "track_count": 10,
                }
            ],
        }
        self.assertEqual(
            compact_new_releases(payload, 50, 20),
            {
                "has_more": True,
                "offset": 50,
                "limit": 20,
                "items": [
                    {
                        "id": "new",
                        "title": "New Album",
                        "artist": "Artist",
                        "date": "2026-08-21",
                        "tracks": 10,
                    }
                ],
            },
        )

    def test_search_selects_requested_collection(self) -> None:
        payload = {
            "albums": {
                "total": 1,
                "offset": 0,
                "items": [{"id": "a", "title": "Album", "artist": {"name": "Artist"}}],
            },
            "artists": {"total": 99, "items": []},
        }
        result = compact_search(payload, "albums")
        self.assertEqual(list(result), ["albums"])
        self.assertEqual(result["albums"]["items"][0]["artist"], "Artist")

    def test_artist_output_is_bounded_and_bio_is_opt_in(self) -> None:
        payload = {
            "id": 1,
            "name": {"display": "Artist"},
            "biography": {"content": "long biography"},
            "top_tracks": [{"id": n, "title": str(n)} for n in range(5)],
            "releases": [
                {
                    "type": "album",
                    "items": [{"id": str(n), "title": str(n)} for n in range(5)],
                },
                {"type": "awardedRelease", "items": [{"id": "duplicate"}]},
            ],
        }
        result = compact_artist_detail(payload, top_limit=2, release_limit=2)
        self.assertNotIn("biography", result)
        self.assertEqual(len(result["top_tracks"]), 2)
        self.assertEqual(len(result["releases"]["album"]), 2)
        self.assertNotIn("awardedRelease", result["releases"])

        with_bio = compact_artist_detail(payload, include_biography=True)
        self.assertEqual(with_bio["biography"], "long biography")


if __name__ == "__main__":
    unittest.main()
