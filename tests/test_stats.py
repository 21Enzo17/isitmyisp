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


if __name__ == "__main__":
    unittest.main()
