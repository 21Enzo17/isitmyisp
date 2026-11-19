"""Unstable tunnels (#99): drops too short or too spread out to be an outage each, but many of them."""

import tempfile
import time
import unittest
from pathlib import Path

from isitmyisp import alerts
from isitmyisp import settings as settings_mod
from isitmyisp.monitor import Monitor
from isitmyisp.report import build_report
from isitmyisp.store import Store
from isitmyisp.tunnels import find_drops, hourly, instability
from tests.test_tunnels_web import WIN, T, healthy_internet, w
from tests.test_webapp import WebAppBase

T0 = 1_794_000_000.0


def fill(store, start, windows, bad_over, bad_under=(), silent=False, verdict="ok"):
    """`windows` samples 30 s apart from `start`; the indices in `bad_over`/`bad_under` lose everything."""
    for i in range(windows):
        ts = start + (i + 1) * WIN
        store.add_window(f"tunnel_over:{T.name}", w(T.overlay, 15, 0 if i in bad_over else 15), ts=ts)
        store.add_window(f"tunnel_under:{T.name}", w(T.underlay, 15, 0 if silent or i in bad_under else 15), ts=ts)
        store.add_window_verdict(verdict, WIN, ts=ts)
    store.commit()
    return start + windows * WIN


class Analysis(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name) / "t.db")

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def test_runs_of_bad_windows_are_drops(self):
        end = fill(self.store, T0, 60, bad_over={5, 6, 7, 20, 40}, bad_under={20})
        drops = find_drops(self.store, T.name, T0, end)
        self.assertEqual([d.windows for d in drops], [3, 1, 1])
        self.assertEqual([d.outside for d in drops], ["clean", "bad", "clean"])
        self.assertEqual(drops[0].start, T0 + 5 * WIN)     # the first bad window covers the 30 s before it

    def test_drops_on_a_timer_with_a_clean_path_are_rekey(self):
        # one window lost every hour (± a few seconds) for five hours: lifetimes or rekey
        per_hour = int(3600 / WIN)
        end = fill(self.store, T0, 5 * per_hour + 20, bad_over={k * per_hour + 10 for k in range(5)})
        ins = instability(self.store, T.name, end)
        self.assertTrue(ins.unstable)
        self.assertEqual(ins.cause, "rekey")
        self.assertAlmostEqual(ins.every, 3600, delta=1)
        self.assertEqual((len(ins.stretch), ins.micro), (5, 5))
        self.assertEqual(sum(hourly(ins.drops, end)), 5)

    def test_a_timer_shows_through_short_drops_in_between(self):
        # 2.5 min down every 2 h (the outages), plus one-window blips at random in between
        per = int(7200 / WIN)
        bad = {k * per + 10 + j for k in range(4) for j in range(5)} | {130, 300, 410, 700}
        end = fill(self.store, T0, 4 * per, bad_over=bad)
        ins = instability(self.store, T.name, end)
        self.assertEqual(ins.cause, "rekey")
        self.assertAlmostEqual(ins.every, 7200, delta=1)

    def test_irregular_drops_with_a_clean_path_are_configuration(self):
        end = fill(self.store, T0, 200, bad_over={10, 25, 70, 77, 150})
        ins = instability(self.store, T.name, end)
        self.assertTrue(ins.unstable)
        self.assertEqual((ins.cause, ins.every), ("config", None))

    def test_path_losing_too_is_the_far_site_when_your_internet_is_fine(self):
        bad = {10, 25, 70, 77, 150}
        end = fill(self.store, T0, 200, bad_over=bad, bad_under=bad)
        self.assertEqual(instability(self.store, T.name, end).cause, "path_remote")

    def test_path_losing_too_is_your_connection_when_your_internet_is_bad(self):
        bad = {10, 25, 70, 77, 150}
        end = fill(self.store, T0, 200, bad_over=bad, bad_under=bad, verdict="isp")
        self.assertEqual(instability(self.store, T.name, end).cause, "path_local")

    def test_far_end_that_never_answers_ping_cannot_tell(self):
        end = fill(self.store, T0, 200, bad_over={10, 25, 70, 77, 150}, silent=True)
        self.assertEqual(instability(self.store, T.name, end).cause, "unknown")

    def test_two_drops_are_not_unstable_and_a_quiet_hour_ends_it(self):
        end = fill(self.store, T0, 100, bad_over={10, 50})
        self.assertFalse(instability(self.store, T.name, end).unstable)
        end = fill(self.store, T0, 400, bad_over={10, 30, 50, 70})
        ins = instability(self.store, T.name, end)          # last drop 330 windows (2 h 45 min) ago
        self.assertFalse(ins.unstable)
        self.assertEqual(len(ins.stretch), 4)               # still the last stretch, for the record

    def test_a_path_change_just_before_is_named(self):
        self.store.add_route_event(T0 - 600, f"tunnel:{T.name}", f"tunnel:{T.name}", "changed", {})
        end = fill(self.store, T0, 200, bad_over={10, 25, 70, 77, 150})
        self.assertIsNotNone(instability(self.store, T.name, end).route_event)


class MonitorUnstable(unittest.TestCase):
    def run_windows(self, mon, start, n, bad):
        for i in range(n):
            m, rows = healthy_internet()
            over = w(T.overlay, 15, 0 if i in bad else 15)
            mon.step(m, rows, now=start + (i + 1) * WIN, tunnels=[(T, w(T.underlay, 15, 15), over)])
        return start + n * WIN

    def test_microdrops_open_one_alert_that_closes_when_it_calms_down(self):
        with tempfile.TemporaryDirectory() as d:
            store = Store(Path(d) / "t.db")
            mon = Monitor(store, WIN)
            end = self.run_windows(mon, T0, 40, bad={5, 17, 31})
            self.assertEqual(store.incidents_between(0, 2e9, scope="tunnels"), [])   # too short for an outage
            [inc] = store.incidents_between(0, 2e9, scope="unstable")
            self.assertEqual((inc.scope, inc.code, inc.closed), (f"unstable:tunnel:{T.name}", "unstable_config", None))
            self.assertEqual(inc.opened, T0 + 5 * WIN)
            self.assertEqual(inc.details["drops"], 3)
            self.assertIn("clean during 3 of them", " ".join(inc.evidence))
            # one alert, in plain words, and only for this; the tunnel itself never "went down"
            title, body = alerts.describe(inc, "opened", "en")
            self.assertIn("Unstable tunnel: its configuration", title)
            self.assertIn("DPD", body)
            self.assertEqual([i.id for i in store.incidents_to_alert()[0]], [inc.id])
            self.run_windows(mon, end, 130, bad=set())     # an hour (and more) without a drop
            [inc] = store.incidents_between(0, 2e9, scope="unstable")
            self.assertEqual(inc.closed, T0 + 32 * WIN)     # unstable until its last drop
            self.assertEqual(store.incidents_between(0, 2e9), [])   # your internet was never at fault
            store.close()


class Pages(WebAppBase):
    def setUp(self):
        super().setUp()
        settings_mod.save(self.store, {"tunnels": [T.__dict__]})
        mon = Monitor(self.store, WIN)
        start = time.time() - 40 * WIN
        for i in range(40):
            m, rows = healthy_internet()
            over = w(T.overlay, 15, 0 if i in (5, 17, 31) else 15)
            mon.step(m, rows, now=start + (i + 1) * WIN, tunnels=[(T, w(T.underlay, 15, 15), over)])
        self.create_admin()

    def test_tunnel_card_shows_instability_drops_and_cause(self):
        html = self.client.get("/tunnels").get_data(as_text=True)
        self.assertIn("Unstable ·", html)
        self.assertIn("Unstable tunnel: its configuration", html)
        self.assertIn('<figure class="drops">', html)
        self.assertIn("3 drops in the last 24 h (3 too short to count as an outage)", html)
        self.assertNotIn("<script", html)

    def test_dashboard_row_says_unstable(self):
        html = self.client.get("/").get_data(as_text=True)
        self.assertIn('class="row s-warn"', html)
        self.assertIn("Unstable tunnel: its configuration (path was clean). 3 drops", html)

    def test_tv_board_says_unstable_not_up(self):
        self.store.set_settings({"tv_token": "tok"})
        html = self.client.get("/tv/tok").get_data(as_text=True)
        self.assertIn('<li class="s-warn">', html)
        self.assertIn("<b>Unstable</b>", html)

    def test_incidents_page_and_report(self):
        html = self.client.get("/incidents").get_data(as_text=True)
        self.assertIn("Unstable tunnel: its configuration", html)
        now = time.time()
        rep = build_report(self.store, now - 86400, now, "en", now=now)
        self.assertIn("Instability inside the tunnels", rep)
        self.assertRegex(rep, r"<td>branch</td><td class=\"num\">3</td><td class=\"num\">3</td>")


if __name__ == "__main__":
    unittest.main()
