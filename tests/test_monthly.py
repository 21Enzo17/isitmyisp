"""The monthly report by email: when it's due, that it's sent once, and what it says."""

import os
import tempfile
import time
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

from isitmyisp import alerts, monthly
from isitmyisp.store import Store


def ts(s: str) -> float:
    return datetime.strptime(s, "%Y-%m-%d %H:%M").timestamp()


class Monthly(unittest.TestCase):
    def setUp(self):
        self.tz = os.environ.get("TZ")
        os.environ["TZ"] = "America/Argentina/Jujuy"
        time.tzset()
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name) / "m.db")
        cfg = alerts.load(self.store)
        cfg["email"].update(host="smtp.example", sender="isitmyisp@example.com", to="owner@example.com")
        alerts.save(self.store, cfg)
        # October 2026: a day of windows with one 30-minute ISP incident on the 14th
        for k in range(48):
            self.store.add_window_verdict("ok", 1800, ts=ts("2026-10-14 00:00") + 1800 * (k + 1))
        iid = self.store.open_incident("isp", ["1.1.1.1: 40% loss"], ts=ts("2026-10-14 10:00"))
        self.store.close_incident(iid, ts=ts("2026-10-14 10:30"))
        self.sent = []

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()
        if self.tz is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = self.tz
        time.tzset()

    def fake_send(self, cfg, title, body, attachments=None):
        self.sent.append((cfg["to"], title, body, attachments))

    def test_previous_month_and_validation(self):
        self.assertEqual(monthly.previous_month(ts("2026-11-01 08:00"))[2], "2026-10")
        self.assertEqual(monthly.previous_month(ts("2026-01-15 08:00"))[2], "2025-12")
        for bad in ({"day": 31}, {"hour": 24}, {"to": "not an email"}, {"day": "x"}):
            with self.assertRaises(monthly.MonthlyError):
                monthly.validate(bad)
        self.assertEqual(monthly.validate({"to": " a@b.example ,c@d.example"})["to"], "a@b.example, c@d.example")

    def test_due_once_on_the_day_and_hour_and_survives_restarts(self):
        cfg = monthly.save(self.store, {"enabled": True, "day": 1, "hour": 8})
        self.assertIsNone(monthly.due(cfg, ts("2026-11-01 07:59"), self.store))
        self.assertEqual(monthly.due(cfg, ts("2026-11-01 08:00"), self.store), "2026-10")
        with mock.patch.object(alerts, "send_email", self.fake_send):
            monthly.Reporter(self.store, lambda: "es").tick(now=ts("2026-11-01 08:00"), background=False)
            # a new Reporter, as after a restart: the month was recorded in the database
            monthly.Reporter(self.store, lambda: "es").tick(now=ts("2026-11-03 09:00"), background=False)
        self.assertEqual(len(self.sent), 1)
        self.assertEqual(monthly.due(cfg, ts("2026-12-01 08:00"), self.store), "2026-11")
        self.assertIsNone(monthly.due(monthly.validate({"enabled": False}), ts("2026-12-01 08:00"), self.store))

    def test_a_failure_is_recorded_and_retried_later(self):
        cfg = monthly.save(self.store, {"enabled": True})
        boom = mock.Mock(side_effect=alerts.AlertError("email failed: SMTPAuthenticationError"))
        with mock.patch.object(alerts, "send_email", boom):
            monthly.Reporter(self.store, lambda: "en").tick(now=ts("2026-11-01 08:00"), background=False)
        self.assertIn("SMTPAuthenticationError", self.store.get_setting(monthly.ERROR)["error"])
        self.assertIsNone(monthly.due(cfg, ts("2026-11-01 08:05"), self.store))          # not every window
        self.assertEqual(monthly.due(cfg, ts("2026-11-01 08:20"), self.store), "2026-10")

    def test_the_message_says_how_the_month_went_and_attaches_the_report(self):
        cfg = monthly.save(self.store, {"enabled": True, "to": "boss@example.com"})
        with mock.patch.object(alerts, "send_email", self.fake_send):
            monthly.send(self.store, cfg, "es", now=ts("2026-11-01 08:00"))
        to, title, body, att = self.sent[0]
        self.assertEqual(to, "boss@example.com")
        self.assertIn("octubre 2026", title)
        self.assertIn("1 incidente, 30 min en total", body)
        self.assertIn("1 en la red de tu ISP", body)
        self.assertIn("Peor día: 2026-10-14, 30 min", body)
        from isitmyisp import hours
        hours.save(self.store, {"enabled": True, "days": {str(d): [["00:00", "24:00"]] for d in range(7)}})
        body = monthly.summary(self.store, *monthly.previous_month(ts("2026-11-01 08:00"))[:2], "es")[1]
        self.assertIn("de 1 d abierto", body)          # only the measured day, not the whole month
        name, maintype, subtype, data = att[0]
        self.assertTrue(name.startswith("isitmyisp-2026-10."))
        self.assertGreater(len(data), 1000)

    def test_clear_errors_without_an_email_server(self):
        alerts.save(self.store, {**alerts.load(self.store), "email": {**alerts.load(self.store)["email"], "host": ""}})
        with self.assertRaises(monthly.MonthlyError) as e:
            monthly.send(self.store, monthly.load(self.store), "en")
        self.assertIn("email server", str(e.exception))
