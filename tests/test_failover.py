import tempfile
import time
import unittest
from pathlib import Path

from isitmyisp import alerts
from isitmyisp.failover import REACHED, PathWatch, Provider, compare, isp_ttl, parse_ttl_reply, provider_of
from isitmyisp.monitor import Monitor
from isitmyisp.report import build_report
from isitmyisp.store import Store

# real iputils output (captured in the Docker image)
TTL_EXCEEDED = """PING 1.1.1.1 (1.1.1.1) 56(84) bytes of data.
From 181.89.4.100 icmp_seq=1 Time to live exceeded

--- 1.1.1.1 ping statistics ---
1 packets transmitted, 0 received, +1 errors, 100% packet loss, time 0ms
"""
SILENT = """PING 1.1.1.1 (1.1.1.1) 56(84) bytes of data.

--- 1.1.1.1 ping statistics ---
1 packets transmitted, 0 received, 100% packet loss, time 0ms
"""
ECHO = """PING 1.1.1.1 (1.1.1.1) 56(84) bytes of data.
64 bytes from 1.1.1.1: icmp_seq=1 ttl=58 time=29.0 ms
"""


def snapshot(isp_hop, asn=None, name=None, cgnat_first=False):
    path = [{"index": 1, "host": "192.168.1.1", "segment": "home", "asn": None, "as_name": None}]
    if cgnat_first:
        path.append({"index": 2, "host": "100.64.0.1", "segment": "isp", "asn": None, "as_name": None})
    path.append({"index": len(path) + 1, "host": isp_hop, "segment": "isp", "asn": asn, "as_name": name})
    path.append({"index": len(path) + 1, "host": "1.1.1.1", "segment": "beyond", "asn": "AS13335", "as_name": "Cloudflare"})
    return {"isp_hop": path[1]["host"], "isp_asn": asn, "isp_name": name, "path": path}


class Parse(unittest.TestCase):
    def test_outputs(self):
        self.assertEqual(parse_ttl_reply(TTL_EXCEEDED), "181.89.4.100")
        self.assertEqual(parse_ttl_reply(TTL_EXCEEDED.replace("100 icmp", "100: icmp")), "181.89.4.100")  # busybox
        self.assertIsNone(parse_ttl_reply(SILENT))
        self.assertEqual(parse_ttl_reply(ECHO), REACHED)   # path got shorter: also a change


class Watch(unittest.TestCase):
    def watch(self, answers, **kw):
        it = iter(answers)
        return PathWatch("181.89.4.100", 2, ["1.1.1.1"], probe=lambda target, ttl: next(it), **kw)

    def test_needs_two_different_answers_in_a_row(self):
        w = self.watch(["200.0.0.1", "181.89.4.100", "200.0.0.1", "200.0.0.1"])
        self.assertEqual([w.check() for _ in range(4)], [False, False, False, True])

    def test_silence_neither_confirms_nor_clears(self):
        w = self.watch(["200.0.0.1", None, "200.0.0.1"])
        self.assertEqual([w.check() for _ in range(3)], [False, False, True])

    def test_known_routers_of_the_same_isp_are_not_a_change(self):   # ECMP: the ISP balances its first hop
        w = self.watch(["181.89.4.101"] * 3, known={"181.89.4.101"})
        self.assertFalse(any(w.check() for _ in range(3)))


class Providers(unittest.TestCase):
    def test_by_asn_or_by_network(self):
        p = provider_of(snapshot("181.89.4.100", "AS7303", "Telecom Argentina"))
        self.assertEqual((p.asn, p.net16, p.name), ("AS7303", "181.89.0.0/16", "Telecom Argentina"))
        q = provider_of(snapshot("181.89.4.100"))
        self.assertEqual((q.asn, q.name), (None, "181.89.0.0/16"))

    def test_cgnat_first_hop_uses_the_first_public_one(self):
        snap = snapshot("181.89.4.100", cgnat_first=True)
        self.assertEqual(provider_of(snap).hop, "181.89.4.100")
        self.assertEqual(isp_ttl(snap), 2)                       # the watch pings the CGNAT hop's distance

    def test_compare(self):
        main = provider_of(snapshot("181.89.4.100", "AS7303", "Telecom"))
        self.assertEqual(compare(snapshot("181.89.9.9", "AS7303", "Telecom"), main).kind, "failback")  # reroute
        fo = compare(snapshot("190.2.3.4", "AS11664", "Claro"), main)
        self.assertEqual(fo.kind, "failover")
        self.assertIn("Telecom -> Claro", fo.evidence[0])
        self.assertEqual(compare(snapshot("190.2.3.4"), None).kind, "learn")

    def test_without_asn_the_network_decides_and_says_so(self):
        main = provider_of(snapshot("181.89.4.100"))
        fo = compare(snapshot("190.2.3.4"), main)
        self.assertEqual(fo.kind, "failover")
        self.assertIn("/16", fo.evidence[-1])
        self.assertEqual(compare(snapshot("181.89.200.1"), main).kind, "failback")

    def test_asn_arriving_later_is_not_a_failover(self):
        main = provider_of(snapshot("181.89.4.100"))              # learned before the ASN dataset existed
        self.assertTrue(provider_of(snapshot("181.89.4.100", "AS7303", "Telecom")).same_as(main))


class MonitorIncidents(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name) / "f.db")
        self.mon = Monitor(self.store, 30.0)

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def fo(self):
        return [i for i in self.store.incidents_between(0, 2e10, scope="failover")]

    def test_learn_failover_and_back(self):
        t0 = time.time() - 3600
        self.assertEqual(self.mon.observe_network(snapshot("181.89.4.100"), now=t0).kind, "learn")
        self.assertEqual(self.store.get_setting("primary_isp")["net16"], "181.89.0.0/16")
        self.assertEqual(self.store.settings_version(), 0)        # learning must not restart the session
        self.mon.observe_network(snapshot("190.2.3.4", "AS11664", "Claro"), now=t0 + 60)
        self.mon.observe_network(snapshot("190.2.3.5", "AS11664", "Claro"), now=t0 + 120)  # still on backup
        self.assertEqual(len(self.fo()), 1)
        self.assertEqual(self.fo()[0].details["backup"]["name"], "Claro")
        self.mon.resume()                                         # a restart keeps it open
        self.assertIsNone(self.fo()[0].closed)
        self.mon.observe_network(snapshot("181.89.4.100", "AS7303", "Telecom"), now=t0 + 900)
        self.assertEqual(self.fo()[0].closed, t0 + 900)
        self.assertEqual(self.store.get_setting("primary_isp")["asn"], "AS7303")  # upgraded once known

        title, body = alerts.describe(self.fo()[0], "opened", "es")
        self.assertIn("Enlace a internet", title)
        self.assertIn("respaldo", body)
        for k in range(34):
            self.store.add_window_verdict("ok", 30.0, ts=t0 + 30 * (k + 1))
        self.store.commit()
        doc = build_report(self.store, t0 - 60, t0 + 1000, lang="es", now=t0 + 1000)
        self.assertIn("Enlace de respaldo en uso", doc)
        self.assertIn("14 min", doc)


if __name__ == "__main__":
    unittest.main()
