import io
import tempfile
import time
import unittest
from pathlib import Path

from isitmyisp import settings as settings_mod
from isitmyisp import speedtest as sp
from isitmyisp.classifier import Measurements
from isitmyisp.monitor import Monitor
from isitmyisp.probes.icmp import WindowStats
from isitmyisp.store import Store

ON = {**sp.DEFAULTS, "enabled": True, "accepted": True}


class FakeHTTP:
    """Answers the speed test without any network: downloads are zeros, uploads are swallowed."""

    def __init__(self, fail=False):
        self.fail, self.uploaded, self.requests = fail, 0, 0

    def __call__(self, req, timeout=None):
        self.requests += 1
        if self.fail:
            raise OSError("network unreachable")
        if req.data:
            self.uploaded += len(req.data)
            return io.BytesIO(b"")
        return io.BytesIO(b"\0" * 2_000_000)


def no_ping(target, count, interval):
    return [30.0, 31.0, 29.0] if count == 5 else [55.0, 60.0, 58.0]


class Engine(unittest.TestCase):
    def test_stops_at_the_byte_cap_and_reports_bufferbloat(self):
        http = FakeHTTP()
        r = sp.run(10_000_000, opener=http, ping=no_ping, down_seconds=5, up_seconds=5)
        self.assertIsNone(r.error)
        self.assertGreater(r.down_mbps, 0)
        self.assertLessEqual(r.bytes_used, 10_000_000 + sp.STREAMS * 2_000_000 + sp.STREAMS * sp.UP_CHUNK)
        self.assertLess(r.seconds, 5)                    # the cap ended it, not the clock
        self.assertIn("budget", r.notes)
        self.assertEqual((r.idle_ms, r.loaded_ms), (30.0, 58.0))

    def test_network_error_is_recorded_not_raised(self):
        r = sp.run(10_000_000, opener=FakeHTTP(fail=True), ping=no_ping, down_seconds=1, up_seconds=1)
        self.assertIn("unreachable", r.error)

    def test_wan_counters_give_the_total_link_use(self):
        reads = iter([(0, 0), (int(500e6 / 8 * 1), 0)])  # 500 Mbps over ~1 s
        r = sp.run(5_000_000, opener=FakeHTTP(), ping=no_ping, counters=lambda: next(reads), down_seconds=1, up_seconds=1)
        self.assertIsNotNone(r.wan_down_mbps)

    def test_meter_skips_the_warm_up(self):
        m = sp._Meter(10**12, clock=time.monotonic)
        m.marks = [(0.0, 0), (0.5, 1_000_000), (1.0, 2_000_000), (3.0, 27_000_000)]   # slow start, then 100 Mbps
        self.assertAlmostEqual(m.mbps(), 100.0, delta=0.5)


class Schedule(unittest.TestCase):
    def t(self, *ymdh):
        y, mo, d, h = ymdh
        return time.mktime((y, mo, d, h, 0, 0, 0, 0, -1))

    def test_weekly_slot_and_grace(self):
        cfg = {**ON, "weekday": 6, "hour": 3}           # Sunday 03:00
        sunday3 = self.t(2026, 11, 8, 3)
        self.assertEqual(sp.last_slot(cfg, self.t(2026, 11, 10, 12)), sunday3)
        self.assertTrue(sp.due(cfg, None, sunday3 + 60))
        self.assertFalse(sp.due(cfg, sunday3 + 30, sunday3 + 600))        # already ran for this slot
        self.assertFalse(sp.due(cfg, None, sunday3 + 7 * 3600))           # off at 03:00: don't fire mid-day
        self.assertFalse(sp.due({**cfg, "schedule": "manual"}, None, sunday3 + 60))

    def test_budget_share(self):
        self.assertEqual(sp.per_test_bytes({**ON, "budget_gb": 7}), 1_000_000_000)   # 5 weekly + 2 manual

    def test_blocked_reasons(self):
        kw = dict(used_bytes=0, on_backup=False, incident=False, link_busy_pct=10)
        self.assertEqual(sp.blocked(sp.DEFAULTS, manual=True, **kw), "disabled")       # OFF by default
        self.assertEqual(sp.blocked({**ON, "accepted": False}, manual=True, **kw), "disabled")
        self.assertIsNone(sp.blocked(ON, manual=False, **kw))
        self.assertEqual(sp.blocked(ON, manual=True, **{**kw, "used_bytes": int(4.9e9)}), "budget")
        self.assertEqual(sp.blocked(ON, manual=True, **{**kw, "on_backup": True}), "backup")
        self.assertEqual(sp.blocked(ON, manual=False, **{**kw, "incident": True}), "incident")
        self.assertIsNone(sp.blocked(ON, manual=True, **{**kw, "incident": True}))     # by hand, during an incident: evidence
        self.assertEqual(sp.blocked(ON, manual=False, **{**kw, "link_busy_pct": 60}), "busy")

    def test_turning_it_on_requires_accepting_the_risks(self):
        with self.assertRaises(settings_mod.SettingsError):
            settings_mod.validate({"speedtest": {"enabled": True}})
        out = settings_mod.validate({"speedtest": {"enabled": True, "accepted": True, "budget_gb": "3"}})["speedtest"]
        self.assertEqual((out["enabled"], out["accepted"], out["budget_gb"]), (True, True, 3.0))
        off = settings_mod.validate({"speedtest": {"enabled": False, "accepted": True}})["speedtest"]
        self.assertFalse(off["accepted"])                # turning it off forgets the consent


def w(target, n, received, med=30.0):
    return WindowStats(target, n, received, med, med, med, 0.5, med if received else None)


class RunnerAndMonitor(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name) / "s.db")

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def test_manual_request_runs_once_and_is_stored(self):
        calls = []

        def fake_run(cap, **kw):
            calls.append((cap, kw["trigger"]))
            return sp.Result(ts=time.time(), down_mbps=900, up_mbps=800, bytes_used=cap, trigger=kw["trigger"])
        runner = sp.Runner(self.store, run_fn=fake_run)
        ctx = dict(wireless=False, on_backup=False, incident=False, link_busy_pct=None)
        self.assertIsNone(runner.tick({**ON, "schedule": "manual"}, time.time(), **ctx))
        self.store.set_settings({"_speed_request": time.time()}, bump=False)
        self.assertEqual(runner.tick({**ON, "schedule": "manual"}, time.time(), **ctx), "started")
        runner.thread.join(2)
        self.assertTrue(runner.suppress(time.time(), 30))
        self.assertIsNone(runner.tick({**ON, "schedule": "manual"}, time.time(), **ctx))   # the same press doesn't repeat
        self.assertEqual(calls, [(sp.per_test_bytes({**ON, "schedule": "manual"}), "manual")])
        self.assertLessEqual(calls[0][0], sp.PER_TEST_MAX)
        self.assertEqual(self.store.speedtests_between(0, 2e10)[0]["down_mbps"], 900)

    def test_a_disabled_test_never_runs_even_if_requested(self):
        runner = sp.Runner(self.store, run_fn=lambda cap, **kw: self.fail("must not run"))
        self.store.set_settings({"_speed_request": time.time()}, bump=False)
        self.assertEqual(runner.tick(sp.DEFAULTS, time.time(), wireless=False, on_backup=False, incident=False,
                                     link_busy_pct=None), "disabled")

    def test_windows_during_a_test_open_no_incident(self):
        mon = Monitor(self.store, 30.0)
        t0 = time.time() - 600
        anchors = [w(a, 15, 5, 300) for a in ("1.1.1.1", "8.8.8.8", "9.9.9.9")]       # the link is full
        m = Measurements([w("192.168.1.1", 15, 15, 2)], w("181.0.0.1", 15, 15, 5), anchors,
                         {a.target: w(f"tcp://{a.target}:443", 10, 3) for a in anchors})
        for i in range(4):
            res = mon.step(m, [("anchor", a) for a in anchors], now=t0 + 30 * (i + 1), suppress=True)
            self.assertEqual(res.verdict.code, "speedtest")
        self.assertEqual(self.store.incidents_between(0, 2e10, scope=None), [])
        self.assertEqual({c for _, _, c in self.store.windows_between(0, 2e10)}, {"speedtest"})
        self.assertEqual(self.store.brief_events(0, 2e10), [])                         # not a "brief drop" either


if __name__ == "__main__":
    unittest.main()
