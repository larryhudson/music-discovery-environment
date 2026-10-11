"""Offline wrapper tests: no credentials, API calls, or dependencies needed."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

SOURCE = Path(__file__).resolve().parents[1]


class WrapperTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        base = Path(self.temp.name)
        self.root = base / "checkout with spaces"
        config = self.root / ".agents-in-the-cloud"
        shutil.copytree(SOURCE / "bin", config / "bin")
        shutil.copy2(SOURCE / "install-cli.sh", config / "install-cli.sh")
        self.bin = base / "commands with spaces"
        self.cwd = base / "caller"
        self.cwd.mkdir()
        self.env = dict(os.environ, SKILL_BIN_DIR=str(self.bin))
        # Replace interpreters with probes to test exact argv, cwd, and exit code.
        probe = '#!/usr/bin/env python3\nimport json, os, sys\nprint(json.dumps({"argv": sys.argv[1:], "cwd": os.getcwd()}))\nsys.exit(int(os.environ.get("PROBE_EXIT", "0")))\n'
        python = self.root / ".venv/bin/python"
        python.parent.mkdir(parents=True)
        python.write_text(probe)
        python.chmod(0o755)
        self.bin.mkdir()
        node = self.bin / "node"
        node.write_text(probe)
        node.chmod(0o755)
        self.env["PATH"] = str(self.bin) + os.pathsep + self.env["PATH"]
        self.installer = config / "install-cli.sh"
        self.install()

    def install(self):
        subprocess.run(["sh", str(self.installer)], env=self.env,
                       cwd=self.cwd, check=True, capture_output=True)

    def test_commands(self):
        scripts = {
            "bandcamp": "using-bandcamp/scripts/bandcamp.py",
            "lastfm": "using-lastfm/scripts/lastfm.py",
            "qobuz": "using-qobuz/scripts/qobuz.py",
            "exa-search": "using-exa-search/scripts/exa-search.mjs",
            "read-page": "reading-webpages/scripts/read-page.mjs",
        }
        args = ["--example", "value with spaces", "", "literal;$HOME"]
        for name, script in scripts.items():
            with self.subTest(name=name):
                result = subprocess.run([name, *args], env=self.env,
                                        cwd=self.cwd, capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                data = json.loads(result.stdout)
                expected = [str(self.root / ".agents/skills" / script), *args]
                if name in ("exa-search", "read-page"):
                    expected.insert(0, "--use-env-proxy")
                self.assertEqual(data["argv"], expected)
                self.assertEqual(data["cwd"], str(self.cwd))

    def test_exit_status(self):
        for name in ("bandcamp", "lastfm", "qobuz", "exa-search", "read-page"):
            with self.subTest(name=name):
                result = subprocess.run([name], env=dict(self.env, PROBE_EXIT="7"),
                                        cwd=self.cwd, capture_output=True)
                self.assertEqual(result.returncode, 7)

    def test_repeat_install(self):
        self.install()
        self.install()
        for name in ("bandcamp", "lastfm", "qobuz", "exa-search", "read-page"):
            self.assertEqual((self.bin / name).resolve(),
                             self.root / ".agents-in-the-cloud/bin/skill-cli.sh")


if __name__ == "__main__":
    unittest.main()
