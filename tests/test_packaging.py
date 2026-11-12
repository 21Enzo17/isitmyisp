"""The installer and the release metadata: what users run must match what the docs promise."""

import os
import re
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class Release(unittest.TestCase):
    def test_one_version_everywhere_and_in_the_changelog(self):
        from isitmyisp import __version__
        pyproject = re.search(r'^version = "(.+)"', (ROOT / "pyproject.toml").read_text(), re.M).group(1)
        self.assertEqual(pyproject, __version__)
        self.assertIn(f"## [{__version__}]", (ROOT / "CHANGELOG.md").read_text())

    def test_the_static_site_serves_the_installer(self):
        self.assertIn("cp install.sh site/install.sh", (ROOT / "netlify.toml").read_text())


@unittest.skipUnless(shutil.which("sh") and os.uname().sysname == "Linux", "needs a POSIX shell on Linux")
class Installer(unittest.TestCase):
    def dry(self, *args, lang="en_US.UTF-8"):
        env = {**os.environ, "LANG": lang}
        r = subprocess.run(["sh", str(ROOT / "install.sh"), "--dry-run", "--name", "iim-dry", *args],
                           capture_output=True, text=True, env=env, timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout

    def run_line(self, out):
        return next(line for line in out.splitlines() if "docker run" in line)

    def test_syntax_in_plain_posix_shells(self):
        for shell in ("sh", "dash", "bash"):
            if shutil.which(shell):
                subprocess.run([shell, "-n", str(ROOT / "install.sh")], check=True)

    def test_runs_with_the_documented_flags_and_nothing_more(self):
        line = self.run_line(self.dry())
        for flag in ("--net=host", "--cap-add=NET_RAW", "--restart unless-stopped", "-v isitmyisp:/data",
                     "docker.io/21enzo03/isitmyisp:latest", "monitor --web 0.0.0.0:8080"):
            self.assertIn(flag, line)
        for never in ("--privileged", "--cap-add=ALL", "--pid=host", "/var/run/docker.sock"):
            self.assertNotIn(never, line)

    def test_options(self):
        line = self.run_line(self.dry("--local", "--port", "9090", "--lang", "es", "--tz", "America/Argentina/Jujuy",
                                      "--version", "0.1.0"))
        for part in ("--web 127.0.0.1:9090", "--lang es", "TZ=America/Argentina/Jujuy",
                     "ISITMYISP_HEALTH_URL=http://127.0.0.1:9090/healthz", "isitmyisp:0.1.0"):
            self.assertIn(part, line)
        built = self.dry("--build", "--version", "0.1.0")
        self.assertIn("docker build -t isitmyisp:local https://github.com/21Enzo17/isitmyisp.git#v0.1.0", built)

    def test_speaks_spanish_and_rejects_bad_input(self):
        self.assertIn("va a correr así", self.dry(lang="es_AR.UTF-8"))
        r = subprocess.run(["sh", str(ROOT / "install.sh"), "--dry-run", "--port", "80a"],
                           capture_output=True, text=True, timeout=30)
        self.assertNotEqual(r.returncode, 0)
