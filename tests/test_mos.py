import tempfile
import time
import unittest
from pathlib import Path

from isitmyisp import settings as settings_mod
from isitmyisp.mos import band_of, call_quality, mos_from_r, r_factor, window_quality
from isitmyisp.probes.icmp import WindowStats
from isitmyisp.report import call_periods
from isitmyisp.store import Store


class EModel(unittest.TestCase):
    def test_reference_points(self):
        # a clean 30 ms link is "excellent"; 1 % random loss costs G.711+PLC about 3.6 R points
        self.assertAlmostEqual(r_factor(30, 1, 0), 92.3, places=1)
        self.assertAlmostEqual(r_factor(30, 1, 0) - r_factor(30, 1, 1), 3.6, places=1)
        self.assertAlmostEqual(mos_from_r(70), 3.6, places=1)          # the "fit for calls" line
        self.assertAlmostEqual(mos_from_r(93.2), 4.41, places=2)       # best possible narrowband

    def test_delay_only_hurts_past_the_knee(self):
        self.assertGreater(r_factor(300, 0, 0), 80)                     # 170 ms one way: still good
        self.assertLess(r_factor(600, 0, 0), 70)                        # 320 ms one way: not fit

    def test_bands(self):
        self.assertEqual(call_quality(30, 1, 0).band, "excellent")
        self.assertEqual(call_quality(30, 1, 10).band, "poor")
        self.assertEqual(call_quality(75, 2, 33).band, "bad")
        self.assertFalse(call_quality(75, 2, 33).fit)
        self.assertEqual(call_quality(None, None, 100).mos, 1.0)        # nothing answered: no call
        self.assertEqual([band_of(m) for m in (4.4, 4.1, 3.7, 3.2, 2.0)], ["excellent", "good", "fair", "poor", "bad"])

    def test_window_uses_median_latency_and_mean_loss(self):
        rows = [{"sent": 15, "received": 15, "rtt_median": 30.0, "jitter": 1.0},
                {"sent": 15, "received": 12, "rtt_median": 32.0, "jitter": 3.0},
                {"sent": 15, "received": 15, "rtt_median": 500.0, "jitter": 1.0}]
        q = window_quality(rows)
        self.assertAlmostEqual(q.r, r_factor(32.0, 5 / 3, 20 / 3), places=1)


class Report(unittest.TestCase):
    def test_unfit_stretches_merge_and_short_blips_are_ignored(self):
        with tempfile.TemporaryDirectory() as d:
            store = Store(Path(d) / "m.db")
            t0 = time.time() - 3600
            for i in range(60):          # 30 min: a 5-minute bad stretch and a single bad window
                bad = 20 <= i < 30 or i == 45
                for a in ("1.1.1.1", "8.8.8.8"):
                    store.add_window("anchor", WindowStats(a, 15, 10 if bad else 15, 30, 30, 30, 1.0, 30.0),
                                     ts=t0 + 30 * (i + 1))
            store.commit()
            fit, bad = call_periods(store, t0, t0 + 1800)
            self.assertEqual(len(bad), 1)          # one lost-ping window pooled over 5 min is not a bad call
            # starts and ends where the loss did, give or take the 5-minute smoothing
            self.assertAlmostEqual(bad[0][0], t0 + 30 * 20, delta=120)
            self.assertAlmostEqual(bad[0][1], t0 + 30 * 30, delta=120)
            self.assertGreater(fit, 70)
            store.close()


class Settings(unittest.TestCase):
    def test_calls_destination(self):
        self.assertEqual(settings_mod.validate({"voip_target": " 200.45.1.2 "})["voip_target"], "200.45.1.2")
        self.assertEqual(settings_mod.validate({"voip_target": ""})["voip_target"], "")
        for bad in ("sip.example.com", "192.168.1.10"):
            with self.assertRaises(settings_mod.SettingsError):
                settings_mod.validate({"voip_target": bad})


if __name__ == "__main__":
    unittest.main()
