import json
import multiprocessing
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from qobuz_cli.api import ApiError
from qobuz_cli.cli import parser, run
from qobuz_cli.config import Config
from qobuz_cli.saves import default_saves_path, locked_saves, record_save


def write_concurrent(path, album_id):
    path = Path(path)
    with locked_saves(path) as data:
        record_save(path, data, album_id, "Album", "Artist", "A reason")


class SaveTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "notes" / "saves.json"
        self.config = patch("qobuz_cli.cli.Config.load", return_value=Config("app", "token"))
        self.config.start()
        self.addCleanup(self.config.stop)
        self.api_patch = patch("qobuz_cli.cli.QobuzApi")
        self.api = self.api_patch.start().return_value
        self.addCleanup(self.api_patch.stop)
        self.api.album.return_value = {"title": "Oas", "artist": {"name": "Dina Ögon"}}
        self.api.change_favorite.return_value = {"status": "success"}

    def add(self, *options, item_type="album", raw=False):
        prefix = ["--raw"] if raw else []
        return run(parser().parse_args(prefix + ["add", item_type, "123", "--saves-file", str(self.path), *options]))

    def test_success_records_required_fields_and_unicode(self):
        result = self.add("--reason", "  Warm soul and flutes  ")
        self.assertTrue(result["ok"])
        self.assertEqual(result["saves_file"], str(self.path))
        data = json.loads(self.path.read_text())
        self.assertEqual(data["version"], 1)
        entry = data["saves"][0]
        self.assertEqual(entry["album_name"], "Oas")
        self.assertEqual(entry["artist_name"], "Dina Ögon")
        self.assertEqual(entry["link"], "https://open.qobuz.com/album/123")
        self.assertEqual(entry["reason"], "Warm soul and flutes")
        self.assertIn("saved_at", entry)
        self.assertIn("updated_at", entry)
        self.assertNotIn("token", self.path.read_text())
        self.api.album.assert_called_once_with("123", 1, 0)
        self.api.change_favorite.assert_called_once_with("add", "album", "123")

    def test_release_alias_and_raw_still_record(self):
        self.assertEqual(self.add("--reason", "Why", item_type="release", raw=True), {"status": "success"})
        self.assertEqual(json.loads(self.path.read_text())["saves"][0]["reason"], "Why")

    def test_add_without_reason_records_null(self):
        self.add()
        self.assertIsNone(json.loads(self.path.read_text())["saves"][0]["reason"])

    def test_repeat_save_upserts_and_preserves_reason_when_omitted(self):
        self.add("--reason", "Original")
        first = json.loads(self.path.read_text())["saves"][0]
        self.add()
        self.assertEqual(json.loads(self.path.read_text())["saves"][0]["reason"], "Original")
        self.add("--reason", "Updated")
        entries = json.loads(self.path.read_text())["saves"]
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["reason"], "Updated")
        self.assertEqual(entries[0]["saved_at"], first["saved_at"])

    def test_api_failure_does_not_create_record(self):
        self.api.change_favorite.side_effect = ApiError("Unauthorized")
        with self.assertRaises(ApiError):
            self.add("--reason", "Why")
        self.assertFalse(self.path.exists())

    def test_unconfirmed_response_does_not_create_record(self):
        for payload in ({}, {"status": "error"}, {"status": False}):
            self.api.change_favorite.return_value = payload
            with self.assertRaises(ApiError):
                self.add()
            self.assertFalse(self.path.exists())

    def test_api_failure_preserves_existing_file(self):
        self.add("--reason", "Original")
        original = self.path.read_bytes()
        self.api.change_favorite.side_effect = ApiError("Failed")
        with self.assertRaises(ApiError):
            self.add("--reason", "New")
        self.assertEqual(self.path.read_bytes(), original)

    def test_invalid_file_blocks_remote_mutation(self):
        for text in ("not json", "[]", '{"version":2,"saves":[]}',
                     '{"version":1,"saves":[{}]}'):
            self.path.parent.mkdir(exist_ok=True)
            self.path.write_text(text)
            with self.assertRaises(ValueError):
                self.add()
            self.assertEqual(self.path.read_text(), text)
            self.api.change_favorite.assert_not_called()
            self.api.album.assert_not_called()

    def test_missing_metadata_blocks_remote_mutation(self):
        for payload in ({}, {"title": "Name"}, {"title": "", "artist": {"name": "Artist"}}):
            self.api.album.return_value = payload
            with self.assertRaisesRegex(ValueError, "incomplete album metadata"):
                self.add()
            self.api.change_favorite.assert_not_called()

    def test_empty_reason_and_non_album_options_rejected_before_network(self):
        with self.assertRaisesRegex(ValueError, "must not be empty"):
            self.add("--reason", "  ")
        with self.assertRaisesRegex(ValueError, "only supported"):
            self.add("--reason", "Why", item_type="artist")
        self.api.album.assert_not_called()
        self.api.change_favorite.assert_not_called()

    def test_notes_failure_explicitly_reports_partial_success(self):
        with patch("qobuz_cli.cli.record_save", side_effect=OSError("Disk full")):
            with self.assertRaisesRegex(ValueError, "was saved to Qobuz.*local save record failed"):
                self.add("--reason", "Why")
        self.api.change_favorite.assert_called_once()

    def test_non_album_add_and_remove_unchanged(self):
        for action, kind in (("add", "artist"), ("remove", "album")):
            result = run(parser().parse_args([action, kind, "123"]))
            self.assertEqual(result, {"ok": True, "action": action, "type": kind, "id": "123"})
        self.api.album.assert_not_called()
        self.assertFalse(self.path.exists())

    def test_environment_and_explicit_path_precedence(self):
        with patch.dict(os.environ, {"QOBUZ_SAVES_FILE": str(self.path)}):
            self.assertEqual(default_saves_path(), self.path)
            run(parser().parse_args(["add", "album", "123", "--reason", "Env"]))
            other = Path(self.directory.name) / "override.json"
            run(parser().parse_args(["add", "album", "123", "--saves-file", str(other)]))
            self.assertTrue(other.exists())
            self.assertEqual(json.loads(self.path.read_text())["saves"][0]["reason"], "Env")

    def test_default_is_repo_root_not_cwd(self):
        with patch.dict(os.environ, {}, clear=True):
            expected = Path(__file__).resolve().parents[4] / "qobuz-saves.json"
            self.assertEqual(default_saves_path(), expected)

    def test_atomic_replace_failure_preserves_original_and_cleans_temp(self):
        self.add("--reason", "Original")
        original = self.path.read_bytes()
        with locked_saves(self.path) as data, patch("qobuz_cli.saves.os.replace", side_effect=OSError("Failed")):
            with self.assertRaises(OSError):
                record_save(self.path, data, "456", "Album", "Artist", "Why")
        self.assertEqual(self.path.read_bytes(), original)
        self.assertEqual(list(self.path.parent.glob(".qobuz-saves-*")), [])

    def test_concurrent_processes_do_not_lose_saves(self):
        context = multiprocessing.get_context("spawn")
        processes = [context.Process(target=write_concurrent, args=(str(self.path), str(i))) for i in range(5)]
        for process in processes:
            process.start()
        for process in processes:
            process.join(timeout=10)
            self.assertEqual(process.exitcode, 0)
        self.assertEqual({entry["album_id"] for entry in json.loads(self.path.read_text())["saves"]},
                         {str(i) for i in range(5)})


if __name__ == "__main__":
    unittest.main()
