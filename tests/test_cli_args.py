"""Every command reads only arguments its own parser declares (a missing one is an AttributeError
the first time someone runs it, as `isitmyisp status` did)."""

import re
import unittest
from pathlib import Path

from isitmyisp import cli

SRC = (Path(cli.__file__)).read_text(encoding="utf-8")
MINIMAL = {"mtr": ["8.8.8.8"], "admin": ["auth-mode", "local"]}


def _used(fn: str, seen: set | None = None) -> set[str]:
    """`args.x` read by a command, including the helpers it passes `args` to (minus what it assigns)."""
    seen = seen if seen is not None else set()
    m = re.search(r"\ndef " + fn + r"\(.*?(?=\ndef |\Z)", SRC, re.DOTALL)
    if not m or fn in seen:
        return set()
    seen.add(fn)
    body = m.group(0)
    used = set(re.findall(r"args\.(\w+)", body)) - set(re.findall(r"args\.(\w+)\s*=[^=]", body))
    for helper in re.findall(r"\b(_\w+)\(args", body):
        used |= _used(helper, seen)
    return used


class EveryCommandHasItsArguments(unittest.TestCase):
    def test_no_command_reads_an_undeclared_argument(self):
        parser = cli.build_parser()
        names = [a for a in parser._subparsers._group_actions[0].choices]
        self.assertIn("status", names)
        for name in names:
            with self.subTest(command=name):
                ns = parser.parse_args([name] + MINIMAL.get(name, []))
                assigned = set(re.findall(r"args\.(\w+)\s*=[^=]", SRC))
                missing = sorted(a for a in _used("cmd_" + name.replace("-", "_")) - assigned if not hasattr(ns, a))
                self.assertEqual(missing, [])


if __name__ == "__main__":
    unittest.main()
