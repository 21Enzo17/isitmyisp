import tempfile
import unittest
from pathlib import Path

from isitmyisp.classifier import Measurements, assess, classify
from isitmyisp.lan import LanStats, LanWatch, arp_mac
from isitmyisp.probes.icmp import WindowStats
from isitmyisp.report import localize_evidence
from isitmyisp.snmp import (
    OID_IF_HC_IN_BCAST,
    OID_IF_HC_IN_MCAST,
    LinkMonitor,
    LinkUsage,
)

A = ["1.1.1.1", "8.8.8.8", "9.9.9.9"]
GW, MAC1, MAC2 = "192.168.1.1", "04:18:92:7a:44:73", "74:86:7a:fe:46:d8"
ARP = """IP address       HW type     Flags       HW address            Mask     Device
192.168.1.22     0x1         0x2         74:86:7a:fe:46:d8     *        eth0
192.168.1.1      0x1         0x2         {mac}     *        eth0
192.168.1.9      0x1         0x0         00:00:00:00:00:00     *        eth0
"""
DUP = "64 bytes from 192.168.1.1: icmp_seq=7 ttl=64 time=1.92 ms (DUP!)"
REPLY = "64 bytes from 192.168.1.1: icmp_seq=7 ttl=64 time=1.80 ms"


def w(target, sent, received, med=30.0):
    return WindowStats(target, sent, received, med, med, med, 0.5, med if received else None)


def meas(loss_pct=0, home_loss=0, lan=None, link=None):
    n = 15
    lost, lost_h = round(n * loss_pct / 100), round(n * home_loss / 100)
    anchors = [w(a, n, n - lost) for a in A]
    tcp = {a: w(f"tcp://{a}:443", 10, 10 - round(10 * loss_pct / 100)) for a in A}
    return Measurements([w(GW, n, n - lost_h, 2.0)], w("181.0.0.1", n, n, 5.0), anchors, tcp, link=link, lan=lan)


class Signals(unittest.TestCase):
    def test_quiet_lan_has_no_signals(self):
        self.assertEqual(LanStats(0, 15, [MAC1], 0, 6.0, 5.0).signals(), [])

    def test_duplicates_need_more_than_one(self):
        self.assertEqual(LanStats(dups=1, replies=16).signals(), [])
        self.assertIn("duplicate replies", LanStats(dups=5, replies=20).signals()[0])

    def test_storm_absolute_or_against_baseline(self):
        self.assertTrue(LanStats(mcast_pps=800).storm)                       # a flood whatever the usual rate
        self.assertTrue(LanStats(mcast_pps=150, mcast_base=8).storm)         # 10x the usual and >= 100/s
        self.assertFalse(LanStats(mcast_pps=150, mcast_base=40).storm)       # a busy but normal network
        self.assertFalse(LanStats(mcast_pps=60, mcast_base=1).storm)         # many times the usual, still tiny
        self.assertFalse(LanStats(mcast_pps=150).storm)                      # no baseline yet: only absolute

    def test_one_mac_change_is_not_a_flap(self):
        self.assertEqual(LanStats(macs=[MAC1, MAC2], flaps=1).signals(), [])  # router swapped
        self.assertIn("MAC", LanStats(macs=[MAC1, MAC2], flaps=3).signals()[0])

    def test_spanish_evidence(self):
        es = [localize_evidence(x, "es") for x in LanStats(4, 20, [MAC1, MAC2], 2, 900, 6).signals()]
        self.assertTrue(es[0].startswith("ping al gateway: 4 respuestas duplicadas (DUP) de 20"))
        self.assertIn("broadcast en tu placa de red: 900 paquetes/s (habitual 6)", es[1])
        self.assertIn("la MAC del gateway cambió 2 veces", es[2])


class Arp(unittest.TestCase):
    def test_reads_the_gateway_mac(self):
        self.assertEqual(arp_mac(GW, ARP.format(mac=MAC1.upper())), MAC1)
        self.assertIsNone(arp_mac("192.168.1.9", ARP.format(mac=MAC1)))     # incomplete entry
        self.assertIsNone(arp_mac("10.0.0.1", ARP.format(mac=MAC1)))


class Watch(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        root = Path(self.dir.name)
        (root / "eth0" / "statistics").mkdir(parents=True)
        self.counter, self.arp = root / "eth0" / "statistics" / "multicast", root / "arp"
        self.lw = LanWatch(GW, "eth0", ping=False, sys_root=str(root), arp_path=str(self.arp))

    def tearDown(self):
        self.dir.cleanup()

    def tick(self, t, count, mac=MAC1):
        self.counter.write_text(f"{count}\n")
        self.arp.write_text(ARP.format(mac=mac))
        self.lw.sample(now=t)

    def test_rates_baseline_and_storm(self):
        count = 0
        for t in range(0, 32, 2):            # a calm window: 5 multicast packets/s
            self.tick(t, count)
            count += 10
        calm = self.lw.window()
        self.assertAlmostEqual(calm.mcast_pps, 5.0)
        self.assertIsNone(calm.mcast_base)
        self.assertEqual(calm.signals(), [])
        for t in range(32, 62, 2):           # then a storm: 2000/s
            count += 4000
            self.tick(t, count)
        storm = self.lw.window()
        self.assertEqual(storm.mcast_base, 5.0)
        self.assertTrue(storm.storm)
        self.tick(62, count + 10)
        self.assertEqual(self.lw.window().mcast_base, 5.0)   # the storm didn't become "usual"

    def test_counter_reset_is_skipped(self):
        self.tick(0, 10**9)
        self.tick(2, 50)
        self.assertIsNone(self.lw.window().mcast_pps)

    def test_mac_flap_and_duplicates(self):
        for t, mac in enumerate([MAC1, MAC2, MAC1, MAC1]):
            self.tick(t * 2, 0, mac)
        for line in (REPLY, DUP, REPLY, DUP, "PING 192.168.1.1 (192.168.1.1) 56(84) bytes of data."):
            self.lw.feed_ping(line)
        st = self.lw.window()
        self.assertEqual((st.flaps, st.macs, st.dups, st.replies), (2, [MAC1, MAC2], 2, 4))
        nxt = self.lw.window()
        self.assertEqual((nxt.flaps, nxt.macs, nxt.dups), (0, [MAC1], 0))   # a new window starts clean

    def test_missing_files_give_no_data(self):
        lw = LanWatch(GW, "nope0", ping=False, sys_root=self.dir.name, arp_path=str(Path(self.dir.name, "x")))
        lw.sample(now=0)
        lw.sample(now=2)
        self.assertEqual(lw.window(), LanStats())


class Verdicts(unittest.TestCase):
    LOOP = LanStats(dups=8, replies=24, macs=[MAC1], mcast_pps=3000, mcast_base=6)

    def test_loop_with_loss_is_your_side_not_the_isp(self):
        v = classify(meas(loss_pct=40, home_loss=30, lan=self.LOOP))
        self.assertEqual(v.code, "loop")
        self.assertIn("duplicate replies", v.evidence[0])
        self.assertTrue(any(e.startswith("home router") for e in v.evidence))

    def test_loop_promotes_what_would_look_like_the_isp(self):
        self.assertEqual(classify(meas(loss_pct=40)).code, "isp")
        self.assertEqual(classify(meas(loss_pct=40, lan=self.LOOP)).code, "loop")

    def test_signs_without_failures_are_only_a_hint(self):
        v = classify(meas(lan=self.LOOP))
        self.assertEqual(v.code, "ok")
        self.assertIn("lan_loop", v.hints)

    def test_router_broadcast_from_snmp(self):
        link = LinkUsage(30, 5, 10, 5, 12, bcast_pps=4500, bcast_if="bridge")
        v = classify(meas(loss_pct=40, link=link))
        self.assertEqual(v.code, "loop")
        self.assertIn("broadcast on your router (bridge): 4500 packets/s", v.evidence)

    def test_isp_incident_rules_a_loop_out_only_when_measured(self):
        quiet = meas(loss_pct=40, lan=LanStats(0, 15, [MAC1], 0, 6.0, 5.0))
        self.assertIn("loop", assess(quiet, classify(quiet))["ruled_out"])
        blind = meas(loss_pct=40)
        self.assertNotIn("loop", assess(blind, classify(blind))["ruled_out"])


class RouterBroadcast(unittest.TestCase):
    class Client:
        def __init__(self):
            self.bc = {1: 0, 2: 0, 3: 0}

        def walk(self, base, limit=256):
            if base.endswith("31.1.1.1.1"):
                return [(base + ".1", "lo"), (base + ".2", "ether1"), (base + ".3", "bridge")]
            if base in (OID_IF_HC_IN_BCAST, OID_IF_HC_IN_MCAST):
                return [(f"{base}.{i}", v) for i, v in self.bc.items()]
            return []

        def get(self, oids):
            return {o: 1000 for o in oids}

    def test_busiest_lan_interface_wan_excluded(self):
        c = self.Client()
        lm = LinkMonitor(c, "ether1")
        lm.sample(now=100.0)
        c.bc = {1: 0, 2: 10**6, 3: 30 * 2000}   # the WAN is noisy, but it's the ISP's side
        u = lm.sample(now=130.0)
        self.assertEqual((u.bcast_pps, u.bcast_if), (4000.0, "bridge"))   # bcast + mcast counted together


if __name__ == "__main__":
    unittest.main()
