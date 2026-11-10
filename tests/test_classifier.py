import unittest

from isitmyisp.classifier import Measurements, classify
from isitmyisp.probes.icmp import WindowStats
from isitmyisp.stats import Baseline


def w(target, sent, received, med=20.0, jitter=1.0):
    ok = received > 0
    return WindowStats(target, sent, received, med - 1 if ok else None, med if ok else None,
                       med + 1 if ok else None, jitter if ok else None, med if ok else None)


ANCHORS = ["1.1.1.1", "8.8.8.8", "9.9.9.9"]


def anchors(sent=60, received=60, med=30.0):
    return [w(a, sent, received, med) for a in ANCHORS]


def tcp(sent=30, received=30):
    return {a: w(f"tcp://{a}:443", sent, received, 35.0) for a in ANCHORS}


GW = w("192.168.1.1", 60, 60, 2.0)
ISP = w("181.0.0.1", 60, 60, 5.0)


class Verdicts(unittest.TestCase):
    def test_all_good(self):
        self.assertEqual(classify(Measurements([GW], ISP, anchors(), tcp())).code, "ok")

    def test_one_lost_packet_is_not_a_problem(self):
        # The bug this whole module exists to prevent: 1/50 lost = "2%" but proves nothing.
        a = [w("1.1.1.1", 50, 49, 30), *anchors()[1:]]
        self.assertEqual(classify(Measurements([GW], ISP, a, tcp())).code, "ok")

    def test_local_problem_on_wifi(self):
        gw = w("192.168.1.1", 60, 48, 30.0)
        v = classify(Measurements([gw], ISP, anchors(60, 48), tcp(30, 24), wireless=True))
        self.assertEqual(v.code, "local")
        self.assertIn("wifi", v.hints)

    def test_second_home_router_problem_is_local(self):
        isp_router = w("192.168.0.1", 60, 45, 3.0)  # double NAT: the ISP's router at home
        v = classify(Measurements([GW, isp_router], ISP, anchors(60, 45), tcp(30, 22)))
        self.assertEqual(v.code, "local")
        self.assertIn("192.168.0.1", v.evidence[0])

    def test_router_filtering_icmp_is_not_local(self):
        # Business firewalls often don't answer ping: internet works through them, so it's not "your side".
        v = classify(Measurements([w("192.168.1.1", 60, 0)], ISP, anchors(), tcp()))
        self.assertEqual(v.code, "ok")
        self.assertIn("router_icmp", v.hints)

    def test_access_problem(self):
        v = classify(Measurements([GW], w("181.0.0.1", 60, 50), anchors(60, 50), tcp(30, 25)))
        self.assertEqual(v.code, "access")

    def test_isp_backbone_problem(self):
        v = classify(Measurements([GW], ISP, anchors(60, 48), tcp(30, 24)))
        self.assertEqual(v.code, "isp")

    def test_remote_only(self):
        a = [w("1.1.1.1", 60, 40), w("8.8.8.8", 60, 60), w("9.9.9.9", 60, 60)]
        t = tcp()
        t["1.1.1.1"] = w("tcp://1.1.1.1:443", 30, 20)
        self.assertEqual(classify(Measurements([GW], ISP, a, t)).code, "remote")

    def test_icmp_loss_with_clean_tcp_is_not_a_problem(self):
        v = classify(Measurements([GW], ISP, anchors(60, 45), tcp(30, 30)))
        self.assertEqual(v.code, "ok")
        self.assertIn("icmp_only", v.hints)

    def test_tcp_failing_with_clean_icmp_is_a_problem(self):
        v = classify(Measurements([GW], ISP, anchors(), tcp(30, 15)))
        self.assertEqual(v.code, "isp")

    def test_isp_hop_icmp_noise(self):
        v = classify(Measurements([GW], w("181.0.0.1", 60, 30), anchors(), tcp()))
        self.assertEqual(v.code, "ok")
        self.assertIn("isp_hop_icmp", v.hints)

    def test_dns_failure(self):
        dns = [w("dns://192.168.1.1", 20, 10, 15.0)]
        v = classify(Measurements([GW], ISP, anchors(), tcp(), dns=dns))
        self.assertEqual(v.code, "dns")

    def test_one_dns_of_two_failing_is_a_hint(self):
        dns = [w("dns://192.168.1.1", 20, 10), w("dns://1.1.1.1", 20, 20)]
        v = classify(Measurements([GW], ISP, anchors(), tcp(), dns=dns))
        self.assertEqual(v.code, "ok")
        self.assertIn("dns_partial", v.hints)

    def _baselines(self):
        b = Baseline()
        for _ in range(10):
            b.update(30.0, healthy=True)
        return {**{a: b for a in ANCHORS}, **{f"tcp://{a}:443": b for a in ANCHORS}}

    def test_latency_spike_against_baseline(self):
        # Real congestion: ICMP and TCP both slow down.
        slow_tcp = {a: w(f"tcp://{a}:443", 30, 30, 95.0) for a in ANCHORS}
        v = classify(Measurements([GW], ISP, anchors(med=95.0), slow_tcp), self._baselines())
        self.assertEqual(v.code, "isp")
        self.assertIn("latency", v.evidence[0])

    def test_icmp_latency_spike_with_normal_tcp_is_deprioritization(self):
        normal_tcp = {a: w(f"tcp://{a}:443", 30, 30, 31.0) for a in ANCHORS}
        v = classify(Measurements([GW], ISP, anchors(med=95.0), normal_tcp), self._baselines())
        self.assertEqual(v.code, "ok")
        self.assertIn("icmp_only", v.hints)


if __name__ == "__main__":
    unittest.main()
