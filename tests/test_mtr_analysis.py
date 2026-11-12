import unittest
from pathlib import Path

from isitmyisp.probes.mtr import Hop, analyze_path, parse_mtr_json

FIXTURES = Path(__file__).parent / "fixtures"


def hop(i, host, loss):
    return Hop(index=i, host=host, loss=loss, sent=20, avg=10.0, best=9.0, worst=12.0, stdev=1.0)


class RealWorldFixtures(unittest.TestCase):
    def test_home_ar_icmp_ratelimit_is_not_loss(self):
        # Real capture (Argentina, home fiber): hop 4 never answers, hop 5 shows 80% "loss",
        # but the destination is reached with 0% loss. Nothing is wrong with this path.
        hops = parse_mtr_json((FIXTURES / "mtr_home_ar_icmp_ratelimit.json").read_text())
        p = analyze_path("1.1.1.1", hops)
        self.assertTrue(p.reached)
        self.assertEqual(p.destination_loss, 0.0)
        self.assertIsNone(p.loss_starts_at)
        self.assertFalse(p.degraded)
        status = {ha.hop.index: ha.status for ha in p.hops}
        self.assertEqual(status[4], "no_reply")
        self.assertEqual(status[5], "icmp_deprioritized")
        self.assertEqual(status[7], "ok")


class SyntheticPaths(unittest.TestCase):
    def test_loss_starting_at_isp_access(self):
        hops = [hop(1, "192.168.1.1", 0), hop(2, "181.0.0.1", 12), hop(3, "181.0.0.9", 11), hop(4, "1.1.1.1", 12)]
        p = analyze_path("1.1.1.1", hops)
        self.assertTrue(p.degraded)
        self.assertEqual(p.loss_starts_at, 2)

    def test_loss_at_gateway(self):
        hops = [hop(1, "192.168.1.1", 8), hop(2, "181.0.0.1", 8), hop(3, "1.1.1.1", 9)]
        self.assertEqual(analyze_path("1.1.1.1", hops).loss_starts_at, 1)

    def test_spike_on_middle_hop_but_clean_after(self):
        hops = [hop(1, "192.168.1.1", 0), hop(2, "181.0.0.1", 0), hop(3, "200.0.0.1", 60), hop(4, "1.1.1.1", 0)]
        p = analyze_path("1.1.1.1", hops)
        self.assertFalse(p.degraded)
        self.assertEqual(p.hops[2].status, "icmp_deprioritized")

    def test_loss_starts_later_than_noisy_hop(self):
        # hop 3 is noisy (ICMP), real loss begins at hop 5 and persists.
        hops = [hop(1, "192.168.1.1", 0), hop(2, "181.0.0.1", 0), hop(3, "200.0.0.1", 40),
                hop(4, "200.0.0.5", 0), hop(5, "200.0.0.9", 6), hop(6, "1.1.1.1", 6)]
        p = analyze_path("1.1.1.1", hops)
        self.assertEqual(p.loss_starts_at, 5)

    def test_destination_silent(self):
        hops = [hop(1, "192.168.1.1", 0), hop(2, "???", 100)]
        p = analyze_path("10.9.9.9", hops)
        self.assertFalse(p.reached)


if __name__ == "__main__":
    unittest.main()
