"""Static public IP (#102): an alert only when you said you have a fixed IP and it isn't the one."""

import tempfile
import unittest
from pathlib import Path

from isitmyisp import alerts, settings
from isitmyisp.publicip import EVERY, Checker
from isitmyisp.store import Store

MINE, OTHER = "203.0.113.10", "198.51.100.20"


class StaticIP(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(Path(self.tmp.name) / "p.db")
        self.addCleanup(self.store.close)
        self.answers: list = []
        self.asked = 0
        self.c = Checker(self.store, lookup=self.lookup, background=False)
        self.t = 1_800_000_000.0

    def lookup(self):
        self.asked += 1
        return self.answers.pop(0) if self.answers else None

    def ticks(self, expected, *answers):
        self.answers = list(answers)
        out = []
        for _ in answers:
            out.append(self.c.tick(expected, now=self.t))
            self.t += EVERY
        return out

    def open_(self):
        return [i for i in self.store.active_incidents() if i.scope == "public_ip"]

    def test_off_asks_nothing(self):
        self.assertEqual(self.ticks("", OTHER, OTHER, OTHER), [None, None, None])
        self.assertEqual(self.asked, 0)
        self.assertEqual(self.open_(), [])

    def test_the_same_ip_says_nothing(self):
        self.assertEqual(self.ticks(MINE, MINE, MINE), [None, None])
        self.assertEqual(self.open_(), [])

    def test_another_ip_twice_opens_and_yours_back_closes(self):
        self.assertEqual(self.ticks(MINE, OTHER, OTHER), [None, "opened"])
        (inc,) = self.open_()
        self.assertEqual(inc.details, {"expected": MINE, "seen": OTHER})
        title, body = alerts.describe(inc, "opened", "es")
        self.assertIn("IP pública", title)
        self.assertIn(f"{MINE} → {OTHER}", body)
        self.assertEqual(self.ticks(MINE, MINE), ["closed"])
        self.assertEqual(self.open_(), [])

    def test_one_odd_answer_is_not_enough(self):
        self.assertEqual(self.ticks(MINE, OTHER, MINE, OTHER, MINE), [None] * 4)
        self.assertEqual(self.open_(), [])

    def test_a_failed_lookup_changes_nothing(self):
        self.ticks(MINE, OTHER, OTHER)
        self.assertEqual(self.ticks(MINE, None, None), [None, None])
        self.assertEqual(len(self.open_()), 1)

    def test_asks_once_every_ten_minutes(self):
        self.answers = [MINE] * 10
        for k in range(20):
            self.c.tick(MINE, now=self.t + 30 * k)
        self.assertEqual(self.asked, 1)

    def test_turning_it_off_closes_what_was_open(self):
        self.ticks(MINE, OTHER, OTHER)
        self.c.tick("", now=self.t)
        self.assertEqual(self.open_(), [])

    def test_survives_a_restart(self):
        self.ticks(MINE, OTHER, OTHER)
        self.store.close_dangling()
        self.assertEqual(len(self.open_()), 1)


class Validation(unittest.TestCase):
    def test_public_ipv4_only(self):
        self.assertEqual(settings.validate({"static_ip": " 181.15.20.30 "})["static_ip"], "181.15.20.30")
        self.assertEqual(settings.validate({"static_ip": ""})["static_ip"], "")
        for bad in ("192.168.1.10", "2001:db8::1", "not an ip", "100.64.0.1", MINE):
            with self.subTest(bad=bad), self.assertRaises(settings.SettingsError):
                settings.validate({"static_ip": bad})


if __name__ == "__main__":
    unittest.main()
