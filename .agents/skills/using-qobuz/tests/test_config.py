import json
import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from qobuz_cli.config import Config, ConfigError, credentials_from_har, save_config


class ConfigTests(unittest.TestCase):
    def test_json_bundle_overrides_all_other_sources_without_reading_local(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text(json.dumps({"app_id": "local", "user_auth_token": "local-token"}))
            env = {
                "QOBUZ_CONFIG": str(path),
                "QOBUZ_APP_ID": "separate", "QOBUZ_USER_AUTH_TOKEN": "separate-token",
                "QOBUZ_STATE_JSON": json.dumps({"app_id": "bundle", "user_auth_token": "bundle-token"}),
            }
            with patch.dict(os.environ, env, clear=True):
                self.assertEqual(Config.load(), Config("bundle", "bundle-token"))
                self.assertEqual(Config.load(path), Config("bundle", "bundle-token"))
                path.write_text("invalid local JSON")
                self.assertEqual(Config.load(path), Config("bundle", "bundle-token"))

    def test_invalid_json_bundle_fails_closed(self) -> None:
        invalid = ["", "secret-not-json", "null", "[]", "42", '"secret"', "{}",
                   '{"app_id":"secret"}',
                   '{"app_id":1,"user_auth_token":"secret"}',
                   '{"app_id":"secret","user_auth_token":false}',
                   '{"app_id":"secret","user_auth_token":null}',
                   '{"app_id":"secret","user_auth_token":""}',
                   '{"app_id":"secret","user_auth_token":"valid","extra":NaN}',
                   '{"app_id":" ","user_auth_token":"secret"}']
        for state in invalid:
            with self.subTest(state=state), patch.dict(os.environ, {
                "QOBUZ_STATE_JSON": state, "QOBUZ_APP_ID": "fallback",
                "QOBUZ_USER_AUTH_TOKEN": "fallback-token",
            }, clear=True), patch.object(Path, "exists") as exists:
                with self.assertRaises(ConfigError) as error:
                    Config.load(Path("unused.json"))
                self.assertEqual(str(error.exception), "Invalid QOBUZ_STATE_JSON authentication bundle")
                exists.assert_not_called()

    def test_legacy_local_and_individual_env_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            save_config(Config("local", "local-token"), path)
            with patch.dict(os.environ, {"QOBUZ_CONFIG": str(path)}, clear=True):
                self.assertEqual(Config.load(), Config("local", "local-token"))
                self.assertEqual(Config.auth_source(), "config")
                with patch.dict(os.environ, {"QOBUZ_APP_ID": "override"}):
                    self.assertEqual(Config.load(), Config("override", "local-token"))
                    self.assertEqual(Config.auth_source(), "QOBUZ_APP_ID + config")

    def test_imports_credentials_without_cookie_dependency(self) -> None:
        har = {
            "log": {
                "entries": [
                    {
                        "request": {
                            "url": "https://www.qobuz.com/api.json/0.2/catalog/search?query=x",
                            "headers": [
                                {"name": "X-App-Id", "value": "app"},
                                {"name": "X-User-Auth-Token", "value": "token"},
                            ],
                        }
                    }
                ]
            }
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "capture.har"
            path.write_text(json.dumps(har))
            self.assertEqual(credentials_from_har(path), Config("app", "token"))

    def test_saved_config_is_private(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "nested" / "config.json"
            save_config(Config("app", "token"), path)
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            self.assertEqual(json.loads(path.read_text())["app_id"], "app")


if __name__ == "__main__":
    unittest.main()
