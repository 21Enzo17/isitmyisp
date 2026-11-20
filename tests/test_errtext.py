"""Every validation error the core can raise reads in Spanish on the Spanish web (QA group 1)."""

import ast
import unittest
from pathlib import Path

from tests._web import HAVE_WEB

if HAVE_WEB:
    from isitmyisp.webapp.errtext import known, localize

PKG = Path(__file__).resolve().parent.parent / "isitmyisp"
# the modules whose errors reach a settings form or the alerts test button
MODULES = ("settings", "config", "services", "devices", "hours", "alerts", "speedtest", "monthly", "snmp")


def _sample(node: ast.expr) -> str | None:
    """The message a raise builds, with each {value} as X; None when it isn't a literal."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        return "".join(v.value if isinstance(v, ast.Constant) else "X" for v in node.values)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        a, b = _sample(node.left), _sample(node.right)
        return a + b if a is not None and b is not None else None
    return None


# read only by the CLI (loading isitmyisp.toml) or shown with the speed test result, not by a form
NOT_FORMS = {"SpeedError"}
CLI_ONLY = {"config file not found: X", "config files need Python 3.11+"}


def raised_messages(module: str) -> list[tuple[int, str]]:
    tree = ast.parse((PKG / f"{module}.py").read_text(encoding="utf-8"))
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Raise) and isinstance(node.exc, ast.Call) and node.exc.args:
            if getattr(node.exc.func, "id", None) in NOT_FORMS:
                continue
            msg = _sample(node.exc.args[0])
            if msg is not None and msg not in CLI_ONLY:
                out.append((node.lineno, msg))
    return out


@unittest.skipUnless(HAVE_WEB, "needs the [web] extra")
class EveryErrorIsTranslated(unittest.TestCase):
    def test_found_the_messages(self):
        self.assertGreater(sum(len(raised_messages(m)) for m in MODULES), 60)

    def test_each_one_has_spanish(self):
        missing = [f"{m}.py:{line}: {msg}" for m in MODULES for line, msg in raised_messages(m)
                   if not known(msg)]
        self.assertEqual(missing, [], "add these to isitmyisp/webapp/errtext.py")

    def test_delivery_errors(self):
        for msg in ("Telegram answered 401: check the bot token and chat id", "Telegram answered 500",
                    "Telegram unreachable: URLError", "email failed: SMTPAuthenticationError: (535, b'no')",
                    "webhook answered 404", "webhook unreachable: TimeoutError"):
            with self.subTest(msg=msg):
                self.assertTrue(known(msg))


@unittest.skipUnless(HAVE_WEB, "needs the [web] extra")
class Localize(unittest.TestCase):
    def test_values_are_kept(self):
        self.assertEqual(localize("tunnel 'oficina': underlay must be an IP address, got 'abc'", "es"),
                         "Túnel «oficina»: la IP pública del otro extremo tiene que ser una dirección IP "
                         "(pusiste «abc»).")
        self.assertEqual(localize("at most 20 services", "es"), "Como máximo 20 servicios.")

    def test_english_and_unknown_pass_through(self):
        self.assertEqual(localize("interval must be a number", "en"), "interval must be a number")
        self.assertEqual(localize("Ya está en español", "es"), "Ya está en español")
        self.assertIsNone(localize(None, "es"))


if __name__ == "__main__":
    unittest.main()
