"""mtr's forked helper must not pile up as a zombie under PID 1 (#94).

A fake `mtr` leaves a child behind, like the real one does with mtr-packet. The check
runs in a separate process marked as child subreaper, so orphans land on it the same
way they land on isitmyisp when it is PID 1 in Docker.
"""

import json
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

REPORT = json.dumps({"report": {"hubs": [{"count": 1, "host": "1.1.1.1", "Loss%": 0.0, "Snt": 1,
                                          "Avg": 1.0, "Best": 1.0, "Wrst": 1.0, "StDev": 0.0}]}})

FAKE_MTR = f"""#!/bin/sh
(sleep 0.2; true) &
echo '{REPORT}'
"""

CHECK = textwrap.dedent("""
    import ctypes, os, sys, time
    ctypes.CDLL(None, use_errno=True).prctl(36, 1, 0, 0, 0)  # PR_SET_CHILD_SUBREAPER
    from isitmyisp.probes import mtr
    if sys.argv[1] == "off":
        mtr.reap_orphans = lambda grace=0.0: 0
    for _ in range(3):
        assert len(mtr.run_mtr("1.1.1.1", cycles=1)) == 1
    time.sleep(0.5)  # let any helper still alive exit
    print(sum(1 for pid, z in mtr._orphans().items() if z))
""")


@unittest.skipUnless(sys.platform.startswith("linux"), "needs /proc and prctl")
class ReapMtrOrphans(unittest.TestCase):
    def zombies_after_runs(self, mode: str) -> int:
        with tempfile.TemporaryDirectory() as d:
            fake = Path(d) / "mtr"
            fake.write_text(FAKE_MTR)
            fake.chmod(0o755)
            env = {**os.environ, "PATH": f"{d}:{os.environ.get('PATH', '')}",
                   "PYTHONPATH": str(Path(__file__).resolve().parents[1])}
            out = subprocess.run([sys.executable, "-c", CHECK, mode], env=env, capture_output=True,
                                 text=True, timeout=30, check=False)
        self.assertEqual(out.returncode, 0, out.stderr)
        return int(out.stdout.strip())

    def test_no_zombies_left_after_several_runs(self):
        self.assertEqual(self.zombies_after_runs("on"), 0)

    def test_without_reaping_they_pile_up(self):
        # Guards the test itself: the fake mtr really does leave zombies behind.
        self.assertEqual(self.zombies_after_runs("off"), 3)


if __name__ == "__main__":
    unittest.main()
