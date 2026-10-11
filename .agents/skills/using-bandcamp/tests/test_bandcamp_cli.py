import contextlib
import io
import json
import os
import tempfile
import unittest
import urllib.request
from pathlib import Path
from unittest.mock import patch

from bandcamp_cli import auth
from bandcamp_cli.cli import main
from bandcamp_cli.client import (
    BandcampClient,
    BandcampError,
    compact_item,
    decode_cursor,
    encode_cursor,
    normalize_mobile_token,
    WishlistPage,
)


class ClientTests(unittest.TestCase):
    def test_cursor_round_trip(self):
        cursor = encode_cursor(123, "1700000000::abc")
        self.assertEqual(decode_cursor(cursor), (123, "1700000000::abc"))

    def test_invalid_cursor_has_clear_error(self):
        with self.assertRaisesRegex(BandcampError, "invalid wishlist cursor"):
            decode_cursor("not-a-cursor")

    def test_mobile_item_token_becomes_exclusive_api_cursor(self):
        self.assertEqual(
            normalize_mobile_token("1788161754:-:a4021466828:0:0"),
            "1788161754:4021466828:a::",
        )

    def test_compact_item_omits_large_and_null_fields(self):
        item = {
            "tralbum_id": 42,
            "tralbum_type": "a",
            "band_name": "An Artist",
            "item_title": "An Album",
            "item_url": "https://artist.bandcamp.com/album/an-album",
            "item_art_url": None,
            "featured_track_encodings": {"mp3-128": "large signed URL"},
        }
        self.assertEqual(compact_item(item), {
            "id": 42,
            "type": "album",
            "artist": "An Artist",
            "title": "An Album",
            "url": "https://artist.bandcamp.com/album/an-album",
        })

    def test_resolves_exact_fan_username_with_json_search(self):
        client = BandcampClient()
        response = {"results": [
            {"type": "b", "id": 9, "name": "Tester"},
            {"type": "f", "id": 123, "username": "tester"},
        ]}
        with patch.object(client, "_get_json", return_value=response) as get:
            fan_id = client.resolve_fan_id("Tester")

        self.assertEqual(fan_id, 123)
        get.assert_called_once_with(
            "https://bandcamp.com/api/fuzzysearch/2/app_autocomplete",
            {"q": "Tester", "param_with_locations": "true"},
        )

    def test_first_page_comes_from_mobile_json_api(self):
        items = [{"tralbum_id": number, "token": f"token-{number}"}
                 for number in range(10)]
        client = BandcampClient()
        with patch.object(client, "_get_json", return_value={"items": items}) as get:
            page = client.first_wishlist_page(123)

        get.assert_called_once_with(
            "https://bandcamp.com/api/mobile/26/fan_wishlist", {"fan_id": 123}
        )
        self.assertEqual(page.items, items)
        self.assertEqual(decode_cursor(page.as_json()["next_cursor"]), (123, "token-9"))

    def test_short_mobile_page_has_no_cursor(self):
        client = BandcampClient()
        with patch.object(client, "_get_json", return_value={
                "items": [{"tralbum_id": 42, "token": "last-item-token"}]}):
            page = client.first_wishlist_page(123)
        self.assertIsNone(page.next_token)

    def test_next_page_follows_bandcamp_token(self):
        client = BandcampClient()
        response = {
            "items": [{"tralbum_id": 41}],
            "more_available": True,
            "last_token": "third-page",
        }
        with patch.object(client, "_post", return_value=response) as post:
            page = client.next_wishlist_page(encode_cursor(123, "second-page"))

        post.assert_called_once_with(
            "https://bandcamp.com/api/fancollection/1/wishlist_items",
            {"fan_id": 123, "older_than_token": "second-page", "count": 20},
        )
        self.assertEqual(page.items, [{"tralbum_id": 41}])
        self.assertEqual(decode_cursor(page.as_json()["next_cursor"]), (123, "third-page"))


class AuthTests(unittest.TestCase):
    def test_import_browser_state_keeps_only_bandcamp_cookies(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "state.json"
            destination = root / "cookies.txt"
            source.write_text(json.dumps({"cookies": [
                {
                    "domain": ".bandcamp.com", "path": "/", "secure": True,
                    "httpOnly": True, "expires": 123, "name": "identity",
                    "value": "secret",
                },
                {
                    "domain": ".example.com", "path": "/", "name": "ignored",
                    "value": "nope",
                },
            ]}))

            count = auth.import_browser_state(source, destination)

            self.assertEqual(count, 1)
            self.assertIn("#HttpOnly_.bandcamp.com", destination.read_text())
            self.assertNotIn("example.com", destination.read_text())
            self.assertEqual(destination.stat().st_mode & 0o777, 0o600)


class EnvironmentAuthTests(unittest.TestCase):
    def setUp(self):
        self.cookie = {"name": "identity", "value": "test-session", "domain": ".bandcamp.com",
                       "path": "/", "secure": True, "httpOnly": True, "expires": -1}
        self.state = {"username": "orb-user", "fan_id": 456, "cookies": [self.cookie]}

    def test_env_beats_local_config_and_cookie_overrides(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {
                "BANDCAMP_CONFIG_DIR": directory, "BANDCAMP_COOKIES": "/missing",
                "BANDCAMP_STATE_JSON": json.dumps(self.state)}), \
                patch.object(BandcampClient, "first_wishlist_page",
                             return_value=WishlistPage([], 456, None)) as first, \
                contextlib.redirect_stdout(io.StringIO()):
            Path(directory, "config.json").write_text('{"username":"local","fan_id":123}')
            self.assertEqual(main(["wishlist", "list", "--cookies", "/also-missing"]), 0)
            first.assert_called_once_with(456)
            self.assertEqual(auth.load_config(), {"username": "orb-user", "fan_id": 456})
            self.assertEqual([c.value for c in BandcampClient(Path("/missing")).cookie_jar],
                             ["test-session"])

    def test_invalid_env_never_falls_back_or_echoes_values(self):
        invalid = ["private-marker", "", "[]", "{}", '{"cookies":"private-marker"}',
                   json.dumps({**self.state, "fan_id": True}),
                   json.dumps({**self.state, "cookies": [{**self.cookie, "secure": "private-marker"}]}),
                   json.dumps({**self.state, "cookies": [{**self.cookie, "value": 9}]})]
        for bundle in invalid:
            with self.subTest(bundle=invalid.index(bundle)), \
                    patch.dict(os.environ, {"BANDCAMP_STATE_JSON": bundle}), \
                    patch.object(auth, "config_path", side_effect=AssertionError("local read")), \
                    patch.object(BandcampClient, "first_wishlist_page") as first, \
                    contextlib.redirect_stderr(io.StringIO()) as stderr:
                self.assertEqual(main(["wishlist", "list", "--fan-id", "123"]), 1)
                self.assertIn("invalid BANDCAMP_STATE_JSON", stderr.getvalue())
                self.assertNotIn("private-marker", stderr.getvalue())
                first.assert_not_called()
                with self.assertRaises(BandcampError):
                    BandcampClient()

    def test_cookie_headers_and_domain_filtering(self):
        cookies = [self.cookie] + [dict(self.cookie, domain=domain, name="ignored") for domain in
                                  ("evilbandcamp.com", "bandcamp.com.evil.test", ".example.com")]
        with patch.dict(os.environ, {"BANDCAMP_STATE_JSON": json.dumps({"cookies": cookies})}):
            client = BandcampClient()
        self.assertEqual(len(list(client.cookie_jar)), 1)
        processor = next(h for h in client.opener.handlers
                         if isinstance(h, urllib.request.HTTPCookieProcessor))
        for host in ("bandcamp.com", "artist.bandcamp.com"):
            request = processor.https_request(urllib.request.Request("https://" + host + "/"))
            self.assertEqual(request.get_header("Cookie"), "identity=test-session")
        for host in ("example.com", "evilbandcamp.com", "bandcamp.com.evil.test"):
            request = processor.https_request(urllib.request.Request("https://" + host + "/"))
            self.assertIsNone(request.get_header("Cookie"))

    def test_env_resolution_does_not_write_disk_and_login_is_disabled(self):
        state = dict(self.state)
        del state["fan_id"]
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {
                "BANDCAMP_CONFIG_DIR": directory, "BANDCAMP_STATE_JSON": json.dumps(state)}), \
                patch.object(BandcampClient, "resolve_fan_id", return_value=456), \
                patch.object(BandcampClient, "first_wishlist_page",
                             return_value=WishlistPage([], 456, None)), \
                contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(main(["wishlist", "list"]), 0)
            self.assertEqual(main(["auth", "login"]), 1)
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_export_local_shape_and_private_creation(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {
                "BANDCAMP_CONFIG_DIR": directory}), contextlib.redirect_stdout(io.StringIO()) as stdout:
            cookies = [dict(self.cookie, name=name) for name in
                       ("identity", "js_logged_in", "logout", "BACKENDID3", "tracking")]
            source = Path(directory, "browser.json")
            source.write_text(json.dumps({"cookies": cookies}))
            auth.import_browser_state(source, Path(directory, "cookies.txt"))
            auth.save_config({"username": "local", "fan_id": 123, "extra": "omit"})
            destination = Path(directory, "export.json")
            real_open = os.open
            modes = []

            def check_creation(path, flags, mode):
                fd = real_open(path, flags, mode)
                modes.append(os.fstat(fd).st_mode & 0o777)
                return fd

            with patch.object(auth.os, "open", side_effect=check_creation):
                self.assertEqual(main(["auth", "export-state", str(destination)]), 0)
            exported = json.loads(destination.read_text())
            self.assertEqual(set(exported), {"username", "fan_id", "cookies"})
            self.assertEqual(exported["cookies"], [dict(self.cookie, expires=0)])
            self.assertEqual(modes, [0o600])
            self.assertEqual(destination.stat().st_mode & 0o777, 0o600)
            self.assertEqual(stdout.getvalue(), "")
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(main(["auth", "export-state", str(destination)]), 1)
            self.assertEqual(json.loads(destination.read_text()), exported)


class CliTests(unittest.TestCase):
    def test_wishlist_list_resolves_and_saves_fan_id(self):
        page = WishlistPage([{
            "tralbum_id": 42, "tralbum_type": "a",
            "band_name": "Artist", "item_title": "Album",
        }], 123, None)
        stdout = io.StringIO()
        with tempfile.TemporaryDirectory() as directory, \
                patch.dict(os.environ, {"BANDCAMP_CONFIG_DIR": directory}), \
                patch.object(BandcampClient, "resolve_fan_id", return_value=123), \
                patch.object(BandcampClient, "first_wishlist_page", return_value=page), \
                contextlib.redirect_stdout(stdout):
            result = main(["wishlist", "list", "--username", "tester"])
            saved = json.loads((Path(directory) / "config.json").read_text())

        self.assertEqual(result, 0)
        self.assertEqual(saved, {"username": "tester", "fan_id": 123})
        self.assertEqual(json.loads(stdout.getvalue()), {
            "items": [{"id": 42, "type": "album", "artist": "Artist", "title": "Album"}],
            "next_cursor": None,
        })
        self.assertEqual(len(stdout.getvalue().splitlines()), 1)

    def test_configured_fan_id_skips_username_resolution(self):
        stdout = io.StringIO()
        with tempfile.TemporaryDirectory() as directory, \
                patch.dict(os.environ, {"BANDCAMP_CONFIG_DIR": directory}), \
                patch.object(BandcampClient, "resolve_fan_id") as resolve, \
                patch.object(
                    BandcampClient, "first_wishlist_page",
                    return_value=WishlistPage([], 123, None),
                ) as first, contextlib.redirect_stdout(stdout):
            Path(directory, "config.json").write_text(
                json.dumps({"username": "tester", "fan_id": 123})
            )
            result = main(["wishlist", "list"])

        self.assertEqual(result, 0)
        resolve.assert_not_called()
        first.assert_called_once_with(123)

    def test_missing_identity_is_an_expected_error(self):
        stderr = io.StringIO()
        with tempfile.TemporaryDirectory() as directory, \
                patch.dict(os.environ, {"BANDCAMP_CONFIG_DIR": directory}), \
                contextlib.redirect_stderr(stderr):
            result = main(["wishlist", "list"])
        self.assertEqual(result, 1)
        self.assertIn("a fan ID or username is required", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
