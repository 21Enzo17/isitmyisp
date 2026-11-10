import struct
import unittest

from isitmyisp.discovery import segment_path
from isitmyisp.probes.icmp import FpingProber, PingProber
from isitmyisp.probes.mtr import Hop
from isitmyisp.probes.sockets import _dns_query


def hop(i, host, best, loss=0.0):
    return Hop(index=i, host=host, loss=loss, sent=10, avg=best + 0.5, best=best, worst=best + 2, stdev=0.5)


def segs(path):
    return [p.segment for p in path]


ASN = {"181.89.4.100": ("AS7303", "Telecom"), "181.96.60.162": ("AS7303", "Telecom"),
       "200.1.1.1": ("AS7303", "Telecom"), "1.1.1.1": ("AS13335", "Cloudflare")}


class Segmentation(unittest.TestCase):
    def test_simple_home_fiber(self):
        p = segment_path([hop(1, "192.168.1.1", 1.0), hop(2, "181.89.4.100", 4.0),
                          hop(3, "181.96.60.162", 28.0), hop(4, "1.1.1.1", 29.0)], ASN)
        self.assertEqual(segs(p), ["home", "isp", "isp", "beyond"])

    def test_double_nat_is_home(self):
        # your router -> ISP's router at home (both private, ~1 ms apart) -> ISP
        p = segment_path([hop(1, "192.168.1.1", 1.0), hop(2, "192.168.0.1", 1.6),
                          hop(3, "181.89.4.100", 5.0), hop(4, "1.1.1.1", 29.0)], ASN)
        self.assertEqual(segs(p), ["home", "home", "isp", "beyond"])

    def test_private_far_hop_is_isp_addressing(self):
        # private address 6 ms away: the ISP using private space in its access network
        p = segment_path([hop(1, "192.168.1.1", 1.0), hop(2, "10.20.0.1", 7.0),
                          hop(3, "181.89.4.100", 8.0), hop(4, "1.1.1.1", 29.0)], ASN)
        self.assertEqual(segs(p), ["home", "isp", "isp", "beyond"])

    def test_cgnat(self):
        p = segment_path([hop(1, "192.168.1.1", 1.0), hop(2, "100.72.0.1", 5.0),
                          hop(3, "181.89.4.100", 6.0), hop(4, "1.1.1.1", 29.0)], ASN)
        self.assertEqual(segs(p), ["home", "isp", "isp", "beyond"])

    def test_silent_hop_inherits_next(self):
        p = segment_path([hop(1, "192.168.1.1", 1.0), Hop(2, "???", 100, 10, 0, 0, 0, 0),
                          hop(3, "181.89.4.100", 5.0), hop(4, "1.1.1.1", 29.0)], ASN)
        self.assertEqual(segs(p), ["home", "isp", "isp", "beyond"])

    def test_without_asn_data_stays_conservative(self):
        p = segment_path([hop(1, "192.168.1.1", 1.0), hop(2, "181.89.4.100", 4.0),
                          hop(3, "181.96.60.162", 28.0), hop(4, "1.1.1.1", 29.0)], {})
        self.assertEqual(segs(p), ["home", "isp", "beyond", "beyond"])


class Parsers(unittest.TestCase):
    def test_fping_reply_and_timeout(self):
        p = FpingProber(["1.1.1.1", "192.0.2.1"], interval=1.0)
        p.feed("[1794279664.24863] 1.1.1.1   : [0], 64 bytes, 29.3 ms (29.3 avg, 0% loss)\n")
        p.feed("[1794279665.03275] 192.0.2.1 : [0], timed out (NaN avg, 100% loss)\n")
        p.feed("[1794279665.24903] 1.1.1.1   : [1], 64 bytes, 29.5 ms (29.4 avg, 0% loss)\n")
        ok = p.buf.window("1.1.1.1", 10, 1794279666.0)
        dead = p.buf.window("192.0.2.1", 10, 1794279666.0)
        self.assertEqual((ok.sent, ok.received, ok.rtt_median), (2, 2, 29.4))
        self.assertEqual((dead.sent, dead.received), (1, 0))

    def test_ping_fallback_parser(self):
        p = PingProber(["1.1.1.1"])
        p.feed("1.1.1.1", "[1794278609.305086] 64 bytes from 1.1.1.1: icmp_seq=1 ttl=58 time=28.9 ms\n")
        p.feed("1.1.1.1", "[1794278610.305086] no answer yet for icmp_seq=2\n")
        s = p.buf.window("1.1.1.1", 10, 1794278611.0)
        self.assertEqual((s.sent, s.received), (2, 1))

    def test_dns_query_packet(self):
        pkt = _dns_query("www.google.com", 0x1234)
        qid, flags, qd = struct.unpack("!HHH", pkt[:6])
        self.assertEqual((qid, flags, qd), (0x1234, 0x0100, 1))
        self.assertIn(b"\x06google\x03com\x00", pkt)


if __name__ == "__main__":
    unittest.main()
