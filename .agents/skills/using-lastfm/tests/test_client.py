from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone

UTC = timezone.utc
from pathlib import Path
from typing import Any

import httpx

from lastfm_cli.client import (
    LASTFM_ENDPOINT,
    LastfmApiError,
    LastfmClient,
    LastfmProtocolError,
)

START = datetime(2026, 8, 1, tzinfo=UTC)
END = datetime(2026, 8, 2, tzinfo=UTC)


def recent_track(*, uts: int, **overrides: Any) -> dict[str, Any]:
    track: dict[str, Any] = {
        "artist": {"#text": "Test Artist", "mbid": "artist-mbid"},
        "album": {"#text": "Test Album", "mbid": "album-mbid"},
        "name": "Test Track",
        "mbid": "track-mbid",
        "url": "https://www.last.fm/music/Test+Artist/_/Test+Track",
        "date": {"uts": str(uts), "#text": "1 Aug 2026, 12:00"},
        "image": [{"#text": "ignored", "size": "small"}],
    }
    track.update(overrides)
    return track


def page(
    tracks: list[dict[str, Any]] | dict[str, Any],
    *,
    number: int = 1,
    total_pages: int = 1,
) -> dict[str, Any]:
    return {
        "recenttracks": {
            "track": tracks,
            "@attr": {
                "user": "listener",
                "page": str(number),
                "perPage": "200",
                "totalPages": str(total_pages),
                "total": "2",
            },
        }
    }


class QueuedApi:
    def __init__(self, responses: list[dict[str, Any] | httpx.Response]) -> None:
        self.responses = list(responses)
        self.calls: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        if not self.responses:
            raise AssertionError("Unexpected Last.fm request")
        response = self.responses.pop(0)
        if isinstance(response, httpx.Response):
            return response
        return httpx.Response(200, json=response)


class LastfmClientTests(unittest.TestCase):
    def test_fetches_exact_window_and_follows_total_pages(self) -> None:
        now_playing = recent_track(
            uts=int(START.timestamp()),
            date=None,
            **{"@attr": {"nowplaying": "true"}},
        )
        first = recent_track(uts=int(START.timestamp()) + 60)
        second = recent_track(
            uts=int(START.timestamp()) + 30,
            name="Earlier Track",
            mbid="",
            album={"#text": "", "mbid": ""},
            artist={"#text": "Test Artist", "mbid": ""},
        )
        api = QueuedApi(
            [
                page([now_playing, first], number=1, total_pages=2),
                page([second], number=2, total_pages=2),
            ]
        )

        with httpx.Client(transport=httpx.MockTransport(api)) as http:
            client = LastfmClient("listener", "secret-key", http)
            scrobbles = client.fetch_scrobbles(start=START, end=END)

        self.assertEqual([item.track_name for item in scrobbles], ["Test Track", "Earlier Track"])
        self.assertEqual(scrobbles[0].played_at, START.replace(minute=1))
        self.assertIsNone(scrobbles[1].album_name)
        self.assertIsNone(scrobbles[1].artist_mbid)
        self.assertIsNone(scrobbles[1].track_mbid)
        self.assertEqual(len(api.calls), 2)
        self.assertTrue(all(str(call.url).startswith(LASTFM_ENDPOINT) for call in api.calls))

        first_params = api.calls[0].url.params
        self.assertEqual(first_params["method"], "user.getrecenttracks")
        self.assertEqual(first_params["user"], "listener")
        self.assertEqual(first_params["api_key"], "secret-key")
        self.assertEqual(first_params["from"], str(int(START.timestamp())))
        self.assertEqual(first_params["to"], str(int(END.timestamp()) - 1))
        self.assertEqual(first_params["limit"], "200")
        self.assertEqual(first_params["page"], "1")
        self.assertEqual(api.calls[1].url.params["page"], "2")

    def test_accepts_single_track_object(self) -> None:
        api = QueuedApi([page(recent_track(uts=int(START.timestamp())))])
        with httpx.Client(transport=httpx.MockTransport(api)) as http:
            scrobbles = LastfmClient("listener", "key", http).fetch_scrobbles(start=START, end=END)

        self.assertEqual(len(scrobbles), 1)

    def test_api_error_is_structured_without_exposing_key(self) -> None:
        api = QueuedApi([{"error": 6, "message": "User not found"}])
        with httpx.Client(transport=httpx.MockTransport(api)) as http:
            client = LastfmClient("listener", "secret-key", http)
            with self.assertRaises(LastfmApiError) as raised:
                client.fetch_scrobbles(start=START, end=END)

        self.assertIn("6: User not found", str(raised.exception))
        self.assertNotIn("secret-key", str(raised.exception))

    def test_http_error_does_not_chain_request_containing_key(self) -> None:
        api = QueuedApi([httpx.Response(500, text="failure")])
        with httpx.Client(transport=httpx.MockTransport(api)) as http:
            client = LastfmClient("listener", "secret-key", http)
            with self.assertRaises(LastfmApiError) as raised:
                client.fetch_scrobbles(start=START, end=END)

        self.assertIsNone(raised.exception.__cause__)
        self.assertNotIn("secret-key", str(raised.exception))

    def test_completed_track_without_date_is_rejected(self) -> None:
        malformed = recent_track(uts=int(START.timestamp()), date=None)
        api = QueuedApi([page([malformed])])
        with httpx.Client(transport=httpx.MockTransport(api)) as http:
            client = LastfmClient("listener", "key", http)
            with self.assertRaisesRegex(LastfmProtocolError, "no timestamp"):
                client.fetch_scrobbles(start=START, end=END)

    def test_track_outside_requested_window_is_rejected(self) -> None:
        api = QueuedApi([page([recent_track(uts=int(END.timestamp()))])])
        with httpx.Client(transport=httpx.MockTransport(api)) as http:
            client = LastfmClient("listener", "key", http)
            with self.assertRaisesRegex(LastfmProtocolError, "outside"):
                client.fetch_scrobbles(start=START, end=END)

    def test_naive_or_subsecond_boundaries_are_rejected(self) -> None:
        with httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200))) as http:
            client = LastfmClient("listener", "key", http)
            with self.assertRaisesRegex(ValueError, "timezone"):
                client.fetch_scrobbles(start=START.replace(tzinfo=None), end=END)
            with self.assertRaisesRegex(ValueError, "whole second"):
                client.fetch_scrobbles(start=START.replace(microsecond=1), end=END)
            with self.assertRaisesRegex(ValueError, "later"):
                client.fetch_scrobbles(start=END, end=START)

    def test_from_env_reads_local_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            env_file = Path(directory) / ".env"
            env_file.write_text("LASTFM_API_KEY='file-secret'\n", encoding="utf-8")
            client = LastfmClient.from_env("listener", env_file=env_file)
            try:
                self.assertEqual(client._api_key.get_secret_value(), "file-secret")
                self.assertNotIn("file-secret", repr(client._api_key))
            finally:
                client.close()


if __name__ == "__main__":
    unittest.main()
