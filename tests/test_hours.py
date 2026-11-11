"""Business hours: the arithmetic, the validation, and alerts held while closed."""

import os
import tempfile
import time
import unittest
from datetime import datetime
from pathlib import Path

from isitmyisp import alerts, hours
from isitmyisp.store import Store


def ts(s: str) -> float:
    return datetime.strptime(s, "%Y-%m-%d %H:%M").timestamp()


SHOP = {"enabled": True, "days": hours.SUGGESTED}      # Mon–Fri 8–13 and 17–21, Sat 9–13; 2026-11-11 is a Wednesday


class Arithmetic(unittest.TestCase):
    def setUp(self):
        self.tz = os.environ.get("TZ")
        os.environ["TZ"] = "America/Argentina/Jujuy"
        time.tzset()
        self.cfg = hours.validate(SHOP)

    def tearDown(self):
        if self.tz is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = self.tz
        time.tzset()

    def test_split_shift_and_weekend(self):
        c = self.cfg
        self.assertTrue(hours.is_open(c, ts("2026-11-11 10:00")))
        self.assertFalse(hours.is_open(c, ts("2026-11-11 14:00")))           # siesta
        self.assertTrue(hours.is_open(c, ts("2026-11-14 12:59")))            # Saturday morning
        self.assertFalse(hours.is_open(c, ts("2026-11-15 10:00")))           # Sunday
        self.assertEqual(hours.open_seconds(c, ts("2026-11-11 12:30"), ts("2026-11-11 17:30")), 3600)

    def test_opening_and_last_closing(self):
        c = self.cfg
        self.assertEqual(hours.current_open_start(c, ts("2026-11-11 18:00")), ts("2026-11-11 17:00"))
        self.assertEqual(hours.previous_close(c, ts("2026-11-11 17:00")), ts("2026-11-11 13:00"))
        self.assertEqual(hours.previous_close(c, ts("2026-11-16 08:00")), ts("2026-11-14 13:00"))   # Monday: Saturday
        self.assertIsNone(hours.current_open_start(c, ts("2026-11-11 14:00")))

    def test_past_midnight_is_one_stretch(self):
        night = hours.validate({"enabled": True, "days": {"4": [["20:00", "24:00"]], "5": [["00:00", "02:00"]]}})
        self.assertEqual(hours.intervals(night, ts("2026-11-13 00:00"), ts("2026-11-15 00:00")),
                         [(ts("2026-11-13 20:00"), ts("2026-11-14 02:00"))])

    def test_off_means_nothing_counts(self):
        off = hours.validate({"enabled": False, "days": hours.SUGGESTED})
        self.assertEqual(hours.open_seconds(off, ts("2026-11-11 00:00"), ts("2026-11-12 00:00")), 0)

    def test_validation(self):
        for bad in ({"days": {"0": [["09:00", "08:00"]]}}, {"days": {"0": [["08:00", "13:00"], ["12:00", "14:00"]]}},
                    {"enabled": True, "days": {}}, {"days": {"0": [["8", "9"]]}}, {"days": {"0": [["08:00", ""]]}},
                    {"days": {"0": [["24:30", "24:00"]]}}, {"days": {"0": [["01:00", "02:00"]] * 3}}):
            with self.assertRaises(hours.HoursError, msg=bad):
                hours.validate(bad)
        clean = hours.validate({"days": {"2": [["17:00", "21:00"], ["8:00", "13:00"], ["", ""]]}})
        self.assertEqual(clean["days"]["2"], [["08:00", "13:00"], ["17:00", "21:00"]])   # sorted, padded, blanks out


class QuietAlerts(Arithmetic):
    def setUp(self):
        super().setUp()
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name) / "a.db")
        cfg = alerts.load(self.store)
        cfg["telegram"].update(enabled=True, bot_token="1:x", chat_id="1")
        alerts.save(self.store, cfg)
        hours.save(self.store, {**SHOP, "quiet_alerts": True})
        self.sent = []
        self.alerter = alerts.Alerter(self.store, lambda: "es",
                                      sender=lambda cfg, title, body, extra: self.sent.append((title, body)) or {"telegram": "ok"})

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()
        super().tearDown()

    def tick(self, when):
        self.alerter.tick(now=ts(when), background=False)

    def test_held_while_closed_then_one_digest_at_opening(self):
        a = self.store.open_incident("isp", ["x"], ts=ts("2026-11-11 22:00"))
        self.tick("2026-11-11 22:10")
        self.assertEqual(self.sent, [])                                      # closed: nothing
        self.store.close_incident(a, ts=ts("2026-11-11 22:30"))
        b = self.store.open_incident("local", ["y"], ts=ts("2026-11-12 03:00"))
        self.store.close_incident(b, ts=ts("2026-11-12 03:00") + 30)         # too short: never mentioned
        self.tick("2026-11-12 04:00")
        self.assertEqual(self.sent, [])
        self.tick("2026-11-12 08:00")
        self.assertEqual(len(self.sent), 1)
        title, body = self.sent[0]
        self.assertIn("Con el local cerrado: 1 problema", title)
        self.assertIn("mié 22:00 (30 min)", body)
        self.tick("2026-11-12 08:01")
        self.assertEqual(len(self.sent), 1)                                  # once per opening

    def test_still_going_at_opening_is_alerted_as_usual(self):
        self.store.open_incident("isp", ["x"], ts=ts("2026-11-12 06:00"))
        self.tick("2026-11-12 07:00")
        self.assertEqual(self.sent, [])
        self.tick("2026-11-12 08:00")
        self.assertEqual(len(self.sent), 1)
        self.assertTrue(self.sent[0][0].startswith("🔴"))

    def test_without_quiet_hours_alerts_go_out_at_night(self):
        hours.save(self.store, {**SHOP, "quiet_alerts": False})
        self.store.open_incident("isp", ["x"], ts=ts("2026-11-11 22:00"))
        self.tick("2026-11-11 22:10")
        self.assertEqual(len(self.sent), 1)
