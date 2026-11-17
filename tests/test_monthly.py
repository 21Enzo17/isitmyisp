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

    def test_overlapping_incidents_count_once(self):
        a = self.store.open_incident("isp", ["x"], ts=ts("2026-10-14 12:00"))
        b = self.store.open_incident("local", ["y"], ts=ts("2026-10-14 12:30"))
        self.store.close_incident(a, ts=ts("2026-10-14 13:00"))
        self.store.close_incident(b, ts=ts("2026-10-14 13:15"))
        body = monthly.summary(self.store, *monthly.previous_month(ts("2026-11-01 08:00"))[:2], "en")[1]
        self.assertIn("3 incidents, 1 h 45 min in total", body)    # 10:00-10:30 and 12:00-13:15, not 2 h 15 min
        self.assertIn("Worst day: 2026-10-14, 1 h 45 min", body)

    def test_clear_errors_without_an_email_server(self):
        alerts.save(self.store, {**alerts.load(self.store), "email": {**alerts.load(self.store)["email"], "host": ""}})
        with self.assertRaises(monthly.MonthlyError) as e:
            monthly.send(self.store, monthly.load(self.store), "en")
        self.assertIn("email server", str(e.exception))


class Availability(unittest.TestCase):
    """A destination failing on its own (Quad9 down, the others fine) isn't your internet down (#62)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name) / "a.db")
        t0 = ts("2026-10-14 00:00")
        for k, code in enumerate(["ok"] * 46 + ["remote"] * 2):
            self.store.add_window_verdict(code, 1800, ts=t0 + 1800 * (k + 1))

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def test_only_some_destinations_failing_keeps_the_month_at_100(self):
        body = monthly.summary(self.store, ts("2026-10-01 00:00"), ts("2026-11-01 00:00"), "en")[1]
        self.assertIn("healthy 100.0% of the time", body)


class RemoteSummary(unittest.TestCase):
    def test_names_who_failed_and_says_the_connection_worked(self):
        from isitmyisp.texts import remote_summary
        ev = ["9.9.9.9: 100.0% loss (15/15)", "1.1.1.1: OK", "8.8.8.8: OK"]
        self.assertEqual(remote_summary(ev, "es"), "Quad9 (9.9.9.9) tuvo problemas. Cloudflare (1.1.1.1) y "
                                                   "Google (8.8.8.8) respondieron bien: tu conexión funcionó.")
        self.assertIn("your connection worked", remote_summary(ev, "en"))
        self.assertEqual(remote_summary(["9.9.9.9: 100.0% loss (15/15)"], "es"), "")   # nobody said OK


class Daily(unittest.TestCase):
    """Availability day by day (#63): over measured time only, the first day partial, gaps in grey."""

    def setUp(self):
        self.tz = os.environ.get("TZ")
        os.environ["TZ"] = "America/Argentina/Jujuy"
        time.tzset()
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name) / "d.db")
        # measuring starts on the 10th at noon; the 11th has an hour of ISP trouble and one of Quad9 alone;
        # the 12th wasn't measured; the 13th is fine
        def day(at, codes):
            for k, code in enumerate(codes):
                self.store.add_window_verdict(code, 1800, ts=ts(at) + 1800 * (k + 1))
        day("2026-10-10 12:00", ["ok"] * 24)
        day("2026-10-11 00:00", ["ok"] * 44 + ["isp"] * 2 + ["remote"] * 2)
        day("2026-10-13 00:00", ["ok"] * 48)

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()
        if self.tz is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = self.tz
        time.tzset()

    def test_each_day_on_its_own(self):
        from isitmyisp.report import daily
        days = daily(self.store, ts("2026-10-09 00:00"), ts("2026-10-14 00:00"))
        self.assertEqual([time.localtime(d.start).tm_mday for d in days], [9, 10, 11, 12, 13])
        before, first, bad, gap, fine = days
        self.assertTrue(before.before)
        self.assertIsNone(before.internet)
        self.assertTrue(first.partial)
        self.assertEqual(first.internet, 100)
        self.assertFalse(bad.partial)
        self.assertAlmostEqual(bad.internet, 100 * 46 / 48)       # Quad9 alone isn't your internet down
        self.assertAlmostEqual(bad.isp, 100 * 46 / 48)
        self.assertEqual((bad.down, bad.culprit), (3600, "isp"))
        self.assertFalse(gap.before)
        self.assertIsNone(gap.internet)                            # a gap, after measuring began
        self.assertEqual((fine.internet, fine.partial, fine.culprit), (100, False, None))

    def test_a_first_window_ending_past_midnight_belongs_to_the_day_before(self):
        from isitmyisp.report import daily
        store = Store(Path(self.tmp.name) / "edge.db")
        try:
            store.add_window_verdict("ok", 1800, ts=ts("2026-10-20 00:10"))   # its middle is 23:55 on the 19th
            store.add_window_verdict("ok", 1800, ts=ts("2026-10-20 00:40"))
            eve, day = daily(store, ts("2026-10-19 00:00"), ts("2026-10-20 01:00"))
            self.assertFalse(eve.before)                    # it has data: not "before monitoring"
            self.assertEqual((eve.measured, eve.partial), (1800, True))
            self.assertFalse(day.before)
        finally:
            store.close()

    def test_today_counts_only_what_has_gone(self):
        from isitmyisp.report import daily
        today = daily(self.store, ts("2026-10-13 00:00"), ts("2026-10-13 06:00"))
        self.assertEqual(len(today), 1)
        self.assertEqual(today[0].measured, 6 * 3600)
        self.assertFalse(today[0].partial)
