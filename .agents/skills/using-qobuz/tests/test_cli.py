import io
import json
import os
import stat
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest.mock import patch

from qobuz_cli.api import ApiError
from qobuz_cli.cli import _resolve_genre_ids, main, parser, run
from qobuz_cli.config import Config


class AuthTests(unittest.TestCase):
    def test_json_auth_is_in_memory_and_status_checks_validity(self) -> None:
        state = {"app_id": "test-app", "user_auth_token": "test-token"}
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {
            "QOBUZ_STATE_JSON": json.dumps(state),
        }, clear=True), patch("qobuz_cli.cli.QobuzApi") as api, patch("qobuz_cli.cli.save_config") as save:
            path = Path(directory) / "absent.json"
            prefix = ["--config", str(path)]
            status = run(parser().parse_args(prefix + ["auth", "status"]))
            self.assertEqual(status, {"authenticated": True, "source": "QOBUZ_STATE_JSON"})
            api.assert_called_with(Config(**state))
            api.return_value.get.assert_called_once_with("favorite/getUserFavoriteIds")
            api.return_value.genres.return_value = {"genres": {"items": []}}
            self.assertEqual(run(parser().parse_args(prefix + ["genres"])), {"items": []})
            save.assert_not_called()
            self.assertFalse(path.exists())
            api.return_value.get.side_effect = ApiError("Unauthorized", 401)
            with self.assertRaises(ApiError):
                run(parser().parse_args(prefix + ["auth", "status"]))

    def test_invalid_env_cli_error_is_redacted_without_network_or_write(self) -> None:
        for state in ("secret-not-json", '{"app_id":"secret-marker"}'):
            with self.subTest(state=state), patch.dict(os.environ, {
                "QOBUZ_STATE_JSON": state, "QOBUZ_APP_ID": "fallback",
                "QOBUZ_USER_AUTH_TOKEN": "fallback-token",
            }, clear=True), patch("qobuz_cli.cli.QobuzApi") as api, patch("qobuz_cli.cli.save_config") as save:
                errors = io.StringIO()
                with redirect_stderr(errors), self.assertRaises(SystemExit) as exit_error:
                    main(["auth", "status"])
                self.assertEqual(exit_error.exception.code, 1)
                self.assertEqual(json.loads(errors.getvalue()), {
                    "error": "Invalid QOBUZ_STATE_JSON authentication bundle",
                })
                api.assert_not_called()
                save.assert_not_called()

    def test_export_state_is_minimal_private_and_offline(self) -> None:
        state = {"app_id": "test-app", "user_auth_token": "test-token", "extra": "ignored"}
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {
            "QOBUZ_STATE_JSON": json.dumps(state),
        }, clear=True), patch("qobuz_cli.cli.QobuzApi") as api:
            path = Path(directory) / "private" / "state.json"
            result = run(parser().parse_args(["auth", "export-state", str(path)]))
            self.assertEqual(result, {"ok": True, "path": str(path)})
            self.assertEqual(json.loads(path.read_text()), {
                key: state[key] for key in ("app_id", "user_auth_token")
            })
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            self.assertEqual(stat.S_IMODE(path.parent.stat().st_mode), 0o700)
            api.assert_not_called()

    def test_status_reports_legacy_sources(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text(json.dumps({"app_id": "local", "user_auth_token": "local-token"}))
            for env, source in (
                ({}, "config"),
                ({"QOBUZ_APP_ID": "env"}, "QOBUZ_APP_ID + config"),
                ({"QOBUZ_USER_AUTH_TOKEN": "env"}, "QOBUZ_USER_AUTH_TOKEN + config"),
                ({"QOBUZ_APP_ID": "env", "QOBUZ_USER_AUTH_TOKEN": "env-token"},
                 "QOBUZ_APP_ID + QOBUZ_USER_AUTH_TOKEN"),
            ):
                with self.subTest(source=source), patch.dict(os.environ, env, clear=True), patch("qobuz_cli.cli.QobuzApi") as api:
                    result = run(parser().parse_args(["--config", str(path), "auth", "status"]))
                    self.assertEqual(result["source"], source)
                    self.assertEqual("config" in result, "config" in source)
                    api.return_value.get.assert_called_once_with("favorite/getUserFavoriteIds")

    def test_help_contains_operational_guidance(self) -> None:
        help_text = parser().format_help()
        for text in ("QOBUZ_STATE_JSON", "personal Amp secret", "export-state", "Pagination",
                     "Global flags must precede", "explicit user authorization", "no dry-run"):
            self.assertIn(text, help_text)


class FakeApi:
    def genres(self):
        return {
            "genres": {
                "items": [
                    {"id": 80, "name": "Jazz", "slug": "jazz"},
                    {"id": 112, "name": "Pop/Rock", "slug": "pop-rock"},
                    {
                        "id": 2,
                        "name": "Blues/Country/Folk",
                        "slug": "blues-country-folk",
                    },
                ]
            }
        }


class GenreResolutionTests(unittest.TestCase):
    def test_resolves_ids_names_and_slugs(self) -> None:
        api = FakeApi()
        self.assertEqual(_resolve_genre_ids(api, ["Jazz", "pop-rock", "2"]), [80, 112, 2])

    def test_rejects_unknown_genre(self) -> None:
        with self.assertRaisesRegex(ValueError, "Unknown genre"):
            _resolve_genre_ids(FakeApi(), ["Polka"])


if __name__ == "__main__":
    unittest.main()
