import contextlib
import io
import json
import os
import unittest
from unittest.mock import patch

import httpx

from lastfm_cli.cli import main
from test_client import START, recent_track, page


class CliTests(unittest.TestCase):
    def run_cli(self, args):
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = main(args)
        return code, stdout.getvalue(), stderr.getvalue()

    def test_status_hides_key(self):
        with patch.dict(os.environ, {"LASTFM_USERNAME": "listener", "LASTFM_API_KEY": "secret"}, clear=True):
            code, out, err = self.run_cli(["auth", "status", "--env-file", "/nonexistent"])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out), {"username": "listener", "api_key_configured": True, "validated": False})
        self.assertNotIn("secret", out + err)

    def test_missing_key(self):
        with patch.dict(os.environ, {}, clear=True):
            code, out, err = self.run_cli(["scrobbles", "list", "--username", "listener", "--env-file", "/nonexistent", "--start", "2026-08-01T00:00:00Z", "--end", "2026-08-02T00:00:00Z"])
        self.assertEqual(code, 1)
        self.assertEqual(out, "")
        self.assertIn("LASTFM_API_KEY", err)

    def test_list_json_and_username_override(self):
        calls = []
        def respond(request):
            calls.append(request)
            return httpx.Response(200, json=page([recent_track(uts=int(START.timestamp()))]))
        http = httpx.Client(transport=httpx.MockTransport(respond))
        with patch.dict(os.environ, {"LASTFM_API_KEY": "secret", "LASTFM_USERNAME": "default"}, clear=True), patch("httpx.Client", return_value=http):
            code, out, err = self.run_cli(["scrobbles", "list", "--username", "override", "--start", "2026-08-01T02:00:00+02:00", "--end", "2026-08-02T00:00:00Z", "--pretty"])
        self.assertEqual(code, 0, err)
        result = json.loads(out)
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["items"][0]["track_name"], "Test Track")
        self.assertEqual(calls[0].url.params["user"], "override")
        self.assertNotIn("secret", out + err)

    def test_bad_boundaries_and_page_size_are_usage_errors(self):
        for extra in (["--start", "2026-08-01"], ["--start", "2026-08-01T00:00:00.1Z"], ["--page-size", "201"]):
            with self.subTest(extra=extra), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as caught:
                    main(["scrobbles", "list", "--start", "2026-08-01T00:00:00Z", "--end", "2026-08-02T00:00:00Z"] + extra)
                self.assertEqual(caught.exception.code, 2)

    def test_reversed_window(self):
        code, out, err = self.run_cli(["scrobbles", "list", "--start", "2026-08-02T00:00:00Z", "--end", "2026-08-01T00:00:00Z"])
        self.assertEqual(code, 1)
        self.assertEqual(out, "")
        self.assertIn("later", err)
