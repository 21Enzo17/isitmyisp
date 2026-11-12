import unittest

from isitmyisp.stats import Baseline, Hysteresis, loss_is_significant, wilson_interval


class Significance(unittest.TestCase):
    def test_wilson_bounds(self):
        lo, hi = wilson_interval(1, 50)
        self.assertLess(lo, 1.0)
        self.assertGreater(hi, 8.0)

    def test_noise_is_not_significant(self):
        self.assertFalse(loss_is_significant(1, 50))
        self.assertFalse(loss_is_significant(2, 50))
        self.assertFalse(loss_is_significant(2, 300))

    def test_real_loss_is_significant(self):
        self.assertTrue(loss_is_significant(3, 50))
        self.assertTrue(loss_is_significant(10, 300))

    def test_single_failure_is_never_significant(self):
        # 1 failed TCP connect out of 10 has a Wilson low bound of 1.8%: still not evidence.
        self.assertFalse(loss_is_significant(1, 10))
        self.assertTrue(loss_is_significant(2, 10))

    def test_too_few_samples(self):
        self.assertFalse(loss_is_significant(2, 5))

    def test_total_outage_needs_no_statistics(self):
        self.assertTrue(loss_is_significant(3, 3))


class BaselineTests(unittest.TestCase):
    def test_only_learns_when_healthy(self):
        b = Baseline()
        for v in (30, 31, 29, 30, 32):
            b.update(v, healthy=True)
        b.update(500, healthy=False)
        self.assertEqual(b.value, 30)

    def test_spike_needs_both_ratio_and_absolute(self):
        b = Baseline()
        for _ in range(5):
            b.update(3.0, healthy=True)
        self.assertFalse(b.is_spike(9.0))  # 3x but only +6 ms: not a spike
        b2 = Baseline()
        for _ in range(5):
            b2.update(30.0, healthy=True)
        self.assertTrue(b2.is_spike(80.0))


class HysteresisTests(unittest.TestCase):
    def test_single_bad_window_does_not_open(self):
        h = Hysteresis()
        self.assertIsNone(h.update("isp").opened)
        self.assertIsNone(h.update("ok").closed)
        self.assertIsNone(h.active)

    def test_open_and_close(self):
        h = Hysteresis()
        h.update("isp")
        self.assertEqual(h.update("isp").opened, "isp")
        self.assertIsNone(h.update("ok").closed)
        self.assertEqual(h.update("ok").closed, "isp")

    def test_change_of_cause(self):
        h = Hysteresis()
        h.update("isp"), h.update("isp")
        h.update("local")
        t = h.update("local")
        self.assertEqual((t.closed, t.opened), ("isp", "local"))


    def feed(self, seq, **kw):
        h = Hysteresis(**kw)
        return h, [h.update(c) for c in seq]

    def test_isp_and_access_are_one_outage(self):
        # whether the first hop also looks bad flips from window to window: still one ISP outage
        _, ts = self.feed(["isp", "access", "isp", "access"])
        self.assertEqual([t.opened for t in ts if t.opened], ["access"])
        self.assertFalse(any(t.closed for t in ts))
        self.assertEqual(ts[1].since, 2)

    def test_a_link_that_comes_and_goes_opens_an_intermittent_incident(self):
        h, ts = self.feed(["isp", "ok", "isp", "ok", "isp"])
        t = ts[-1]
        self.assertEqual((t.opened, t.intermittent, t.since), ("isp", True, 5))   # from the first drop
        self.assertTrue(h.intermittent)

    def test_drops_every_minute_and_a_half_count_too(self):
        _, ts = self.feed(["isp", "ok", "ok"] * 3)
        self.assertEqual([t.opened for t in ts if t.opened], ["isp"])

    def test_two_scattered_bad_windows_are_still_noise(self):
        _, ts = self.feed(["isp", "ok", "ok", "ok", "isp", "ok", "ok", "ok", "ok", "ok"])
        self.assertFalse(any(t.opened for t in ts))

    def test_intermittent_stays_open_through_short_quiet_spells(self):
        h, ts = self.feed(["isp", "ok", "isp", "ok", "isp", "ok", "ok", "isp", "ok", "ok", "ok"])
        self.assertEqual(sum(1 for t in ts if t.opened), 1)
        self.assertFalse(any(t.closed for t in ts))
        for _ in range(3):                                   # 3 quiet windows so far, 3 more
            t = h.update("ok")
        self.assertEqual((t.closed, t.clean), ("isp", 6))      # six clean windows (3 min) end it

    def test_after_closing_old_drops_dont_count_again(self):
        _, ts = self.feed(["isp", "ok", "isp", "ok", "isp"] + ["ok"] * 6 + ["isp"])
        self.assertIsNone(ts[-1].opened)

    def test_mixed_problems_open_with_the_most_frequent(self):
        _, ts = self.feed(["local", "ok", "isp", "ok", "isp"])
        self.assertEqual((ts[-1].opened, ts[-1].intermittent), ("isp", True))

    def test_steady_outage_closes_quickly(self):
        _, ts = self.feed(["isp", "isp", "ok", "ok"])
        self.assertEqual((ts[-1].closed, ts[-1].clean), ("isp", 2))

    def test_odd_window_inside_an_incident_changes_nothing(self):
        h, ts = self.feed(["isp", "isp", "local", "isp"])
        self.assertEqual([t.closed for t in ts if t.closed], [])
        self.assertEqual(h.active, "isp")


if __name__ == "__main__":
    unittest.main()
