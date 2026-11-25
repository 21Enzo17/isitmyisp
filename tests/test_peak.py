"""#115: an optional second scheduled test at peak hour, compared with the usual (night) one."""
import tempfile
import time
import unittest
from pathlib import Path

from isitmyisp import settings as settings_mod
from isitmyisp import speedtest as sp
from isitmyisp.store import Store
from tests.test_webapp import HAVE_WEB, WebAppBase, csrf

ON = {**sp.DEFAULTS, "enabled": True, "accepted": True}
PEAK = {**ON, "schedule": "daily", "hour": 3, "peak": True, "peak_hour": 21}


def t(y, mo, d, h, mi=0):
    return time.mktime((y, mo, d, h, mi, 0, 0, 0, -1))


def res(ts, down, trigger, **kw):
    return {"ts": ts, "down_mbps": down, "up_mbps": down / 2, "trigger": trigger, "servers": [], "error": None, **kw}


class Schedule(unittest.TestCase):
    def test_which_test_is_due(self):
        night, peak = t(2026, 11, 24, 3), t(2026, 11, 24, 21)
        self.assertEqual(sp.which_due(PEAK, [], night + 60), "scheduled")
        ran = [res(night + 60, 900, "scheduled")]
        self.assertIsNone(sp.which_due(PEAK, ran, night + 3600))
        self.assertEqual(sp.which_due(PEAK, ran, peak + 60), "peak")
        ran.append(res(peak + 60, 500, "peak"))
        self.assertIsNone(sp.which_due(PEAK, ran, peak + 600))              # once per slot
        self.assertIsNone(sp.which_due(PEAK, ran[:1], peak + 3 * 3600))     # past midnight is not the peak
        self.assertIsNone(sp.which_due({**PEAK, "peak": False}, ran[:1], peak + 60))
        self.assertIsNone(sp.which_due({**PEAK, "schedule": "manual"}, [], peak + 60))

    def test_weekly_peak_is_the_same_day(self):
        cfg = {**PEAK, "schedule": "weekly", "weekday": 6}                  # Sunday 03:00 and 21:00
        sunday = t(2026, 11, 22, 21)
        self.assertEqual(sp.which_due(cfg, [res(t(2026, 11, 22, 3), 900, "scheduled")], sunday + 60), "peak")
        self.assertIsNone(sp.which_due(cfg, [], t(2026, 11, 23, 21) + 60))  # Monday: no
        self.assertEqual(sp.next_run(cfg, t(2026, 11, 22, 12)), sunday)     # next: tonight's peak
        self.assertEqual(sp.next_run({**cfg, "peak": False}, t(2026, 11, 22, 12)), t(2026, 11, 29, 3))

    def test_it_halves_each_tests_share(self):
        self.assertEqual(sp.runs_per_month({**ON, "peak": True}), 10)
        self.assertLess(sp.per_test_bytes({**ON, "peak": True, "budget_gb": 7}), sp.per_test_bytes({**ON, "budget_gb": 7}))

    def test_validate(self):
        out = settings_mod.validate({"speedtest": {"enabled": True, "accepted": True, "peak": True, "peak_hour": "20"}})
        self.assertEqual((out["speedtest"]["peak"], out["speedtest"]["peak_hour"]), (True, 20))
        for bad in ({"peak": True, "peak_hour": 3, "hour": 3}, {"peak": True, "peak_hour": 24}, {"peak_hour": "x"}):
            with self.assertRaises(settings_mod.SettingsError):
                settings_mod.validate({"speedtest": {"enabled": True, "accepted": True, **bad}})

    def test_peak_against_night(self):
        now = t(2026, 11, 24, 22)
        hist = [res(now - 3600, 450, "peak"), res(now - 19 * 3600, 900, "scheduled"), res(now - 2 * 86400, 100, "peak")]
        self.assertEqual(sp.peak_vs_night(hist, now)["pct"], 50)
        self.assertEqual(sp.peak_vs_night(hist, now)["peak"], 450)
        self.assertIsNone(sp.peak_vs_night(hist[1:2], now))                # no peak test yet
        failed = [res(now - 3600, 0, "peak", error="timed out")] + hist[1:]
        self.assertEqual(sp.peak_vs_night(failed, now)["peak"], 100)       # skips the failed one
        self.assertIsNone(sp.peak_vs_night(hist, now + 30 * 86400))        # too old to compare
        # the best figure of each test, so a faster engine counts on both sides
        mlab = {"engine": "mlab", "name": "M-Lab", "where": "inside", "down_mbps": 930.0, "up_mbps": 600.0, "error": None}
        hist[1]["servers"] = [mlab]
        self.assertEqual(sp.peak_vs_night(hist, now)["night"], 930.0)


class Runner(unittest.TestCase):
    def test_the_peak_test_is_stored_as_peak(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(Path(tmp) / "s.db")
            try:
                calls = []

                def fake_run(cap, **kw):
                    calls.append(kw["trigger"])
                    return sp.Result(ts=time.time(), down_mbps=500, up_mbps=300, trigger=kw["trigger"])
                runner = sp.Runner(store, run_fn=fake_run)
                lt = time.localtime()
                cfg = {**PEAK, "hour": (lt.tm_hour + 12) % 24, "peak_hour": lt.tm_hour}
                ctx = {"wireless": False, "on_backup": False, "incident": False, "link_busy_pct": None}
                self.assertEqual(runner.tick(cfg, time.time(), **ctx), "started")
                runner.thread.join(2)
                self.assertIsNone(runner.tick(cfg, time.time(), **ctx))
                self.assertEqual(calls, ["peak"])
                self.assertEqual(store.speedtests_between(0, 2e10)[0]["trigger"], "peak")
            finally:
                store.close()


@unittest.skipUnless(HAVE_WEB, "web extra not installed")
class Web(WebAppBase):
    def test_set_in_settings_and_compared_on_the_dashboard(self):
        self.create_admin()
        page = self.client.get("/settings/connection?lang=en").get_data(as_text=True)
        self.assertIn("Also test at peak hour", page)
        form = {"csrf_token": csrf(page), "enabled": "1", "accepted": "1", "schedule": "daily", "weekday": "6",
                "hour": "3", "budget_gb": "5", "max_busy_pct": "30", "peak": "1", "peak_hour": "21"}
        self.assertEqual(self.client.post("/settings/speedtest", data=form).status_code, 302)
        cfg = settings_mod.load(self.store).speedtest
        self.assertEqual((cfg["peak"], cfg["peak_hour"]), (True, 21))
        self.assertEqual(self.client.post("/settings/speedtest", data={**form, "peak_hour": "3"}).status_code, 400)

        now = time.time()
        self.store.add_speedtest(sp.Result(ts=now - 20 * 3600, down_mbps=900, up_mbps=600, trigger="scheduled"))
        self.store.add_speedtest(sp.Result(ts=now - 600, down_mbps=450, up_mbps=500, trigger="peak"))
        html = self.client.get("/?lang=en").get_data(as_text=True)
        self.assertIn("At peak hour: 450 Mbps, 50% of the usual test", html)
        self.assertIn("The line slows down in the evening", html)
        self.assertIn("(peak hour)", html)

    def test_a_small_budget_is_flagged(self):
        self.create_admin()
        self.store.set_settings({"speedtest": {**ON, "mlab": True, "mlab_accepted": True, "peak": True, "budget_gb": 15},
                                 "link": {"down_mbps": 1000, "up_mbps": 600}})
        html = self.client.get("/?lang=en").get_data(as_text=True)
        self.assertIn("too small to measure your 1000 Mbps plan", html)
        self.assertIn("Raise it to 40 GB in Settings", html)
        page = self.client.get("/settings/connection?lang=en").get_data(as_text=True)
        self.assertIn("a test needs 3.0 GB", page)
        self.store.set_settings({"speedtest": {**ON, "mlab": True, "mlab_accepted": True, "peak": True, "budget_gb": 40}})
        self.assertNotIn("too small to measure", self.client.get("/?lang=en").get_data(as_text=True))

    def test_a_cloudflare_error_still_shows_m_lab(self):
        self.create_admin()
        self.store.set_settings({"speedtest": {**ON, "mlab": True, "mlab_accepted": True}})
        mlab = {"engine": "mlab", "name": "M-Lab", "where": "inside", "down_mbps": 508.4, "up_mbps": 725.3, "error": None}
        err = "Cloudflare is limiting tests from this IP (HTTP 429)"
        self.store.add_speedtest(sp.Result(ts=time.time() - 60, trigger="manual", servers=[mlab], error=err))
        html = self.client.get("/?lang=en").get_data(as_text=True)
        self.assertNotIn("The last test", html)          # not reported as a failed test
        self.assertIn("<b>508</b> Mbps", html)
        self.assertIn("<b>725</b> Mbps", html)
        self.assertIn(err, html)                         # Cloudflare's row says why it has no figure
        tv = self.client.get("/tv?lang=en").get_data(as_text=True)
        self.assertIn("has-speed", tv)
        # nothing measured at all: only the error
        self.store.add_speedtest(sp.Result(ts=time.time() - 10, trigger="manual", servers=[{**mlab, "error": "timed out"}],
                                           error=err))
        self.assertIn("The last test", self.client.get("/?lang=en").get_data(as_text=True))


if __name__ == "__main__":
    unittest.main()
