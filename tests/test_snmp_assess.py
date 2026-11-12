import tempfile
import time
import unittest
from pathlib import Path

from isitmyisp import settings as settings_mod
from isitmyisp.classifier import Measurements, assess, classify
from isitmyisp.monitor import Monitor
from isitmyisp.probes.icmp import WindowStats
from isitmyisp.report import build_report
from isitmyisp.snmp import (OID_IF_HC_IN, OID_IF_HC_OUT, OID_SYS_UPTIME, LinkMonitor, LinkUsage, SnmpError,
                            _int, _oid, _tlv, decode_response, encode_request)
from isitmyisp.store import Store

A = ["1.1.1.1", "8.8.8.8", "9.9.9.9"]


def w(target, sent, received, med=30.0):
    ok = received > 0
    return WindowStats(target, sent, received, med, med, med, 0.5, med if ok else None)


def lossy(loss_pct=0, link=None):
    n = 15
    lost = round(n * loss_pct / 100)
    anchors = [w(a, n, n - lost) for a in A]
    tcp = {a: w(f"tcp://{a}:443", 10, 10 - round(10 * loss_pct / 100)) for a in A}
    return Measurements([w("192.168.1.1", n, n, 2.0)], w("181.0.0.1", n, n, 5.0), anchors, tcp, link=link)


class Codec(unittest.TestCase):
    def test_request_encoding_matches_known_bytes(self):
        # GET sysDescr.0, community "public", request-id 1: canonical v2c packet
        pkt = encode_request("public", ["1.3.6.1.2.1.1.1.0"], 1)
        self.assertEqual(pkt.hex(), "302602010104067075626c6963a019020101020100020100300e300c06082b060102010101000500")

    def test_large_oid_component_and_negative_int(self):
        self.assertEqual(_oid("1.3.6.1.4.1.14988").hex(), "06072b06010401f50c")  # MikroTik enterprise OID
        self.assertEqual(_int(-1).hex(), "0201ff")

    def test_decode_response_counter64(self):
        vb = _tlv(0x30, _oid(OID_IF_HC_IN + ".2") + _tlv(0x46, (2**40).to_bytes(6, "big")))
        pdu = _tlv(0xA2, _int(7) + _int(0) + _int(0) + _tlv(0x30, vb))
        msg = _tlv(0x30, _int(1) + _tlv(0x04, b"public") + pdu)
        rid, err, vbs = decode_response(msg)
        self.assertEqual((rid, err, vbs), (7, 0, [(OID_IF_HC_IN + ".2", 2**40)]))

    def test_malformed(self):
        with self.assertRaises(SnmpError):
            decode_response(b"\x30\x05\x02")


class FakeClient:
    """Answers like a router: uptime and 64-bit counters for ifIndex 2 ('ether1')."""

    def __init__(self):
        self.uptime, self.rx, self.tx = 1000, 0, 0

    def walk(self, base, limit=256):
        if base.endswith("31.1.1.1.1"):  # ifName
            return [(base + ".1", "lo"), (base + ".2", "ether1")]
        return []

    def get(self, oids):
        return {OID_SYS_UPTIME: self.uptime, f"{OID_IF_HC_IN}.2": self.rx, f"{OID_IF_HC_OUT}.2": self.tx}


class Link(unittest.TestCase):
    def test_rates_and_percent_of_contract(self):
        c = FakeClient()
        lm = LinkMonitor(c, "ether1", down_contract_mbps=300, up_contract_mbps=100)
        self.assertIsNone(lm.sample(now=100.0))                 # first sample: no delta yet
        c.uptime, c.rx, c.tx = 4000, int(30 * 150e6 / 8), int(30 * 20e6 / 8)   # 150 Mbps down, 20 up over 30 s
        u = lm.sample(now=130.0)
        self.assertAlmostEqual(u.down_mbps, 150, delta=0.1)
        self.assertAlmostEqual(u.down_pct, 50, delta=0.1)
        self.assertAlmostEqual(u.up_pct, 20, delta=0.1)

    def test_router_reboot_resets_without_bogus_spike(self):
        c = FakeClient()
        lm = LinkMonitor(c, "ether1", 300, 100)
        c.rx = 10**12
        lm.sample(now=100.0)
        c.uptime, c.rx = 5, 1000                                # rebooted: counters back to ~0
        self.assertIsNone(lm.sample(now=130.0))

    def test_unknown_interface(self):
        lm = LinkMonitor(FakeClient(), "wan9", 300, 100)
        self.assertIsNone(lm.sample())
        self.assertIn("wan9", lm.error)


class Verdicts(unittest.TestCase):
    def test_full_link_is_your_own_traffic(self):
        v = classify(lossy(40, LinkUsage(290, 10, 96.7, 10, 20)))
        self.assertEqual(v.code, "saturation")
        self.assertIn("97% of contract", v.evidence[0])

    def test_isp_problem_with_quiet_link_rules_saturation_out(self):
        m = lossy(40, LinkUsage(30, 5, 10, 5, 12))
        v = classify(m)
        self.assertEqual(v.code, "isp")
        a = assess(m, v)
        self.assertIn("saturation", a["ruled_out"])
        self.assertIn("router_overload", a["ruled_out"])
        self.assertIn("home", a["ruled_out"])
        self.assertIn("transit", a["not_ruled_out"])

    def test_without_router_data_saturation_is_not_ruled_out(self):
        m = lossy(40)
        a = assess(m, classify(m))
        self.assertIn("saturation", a["not_ruled_out"])
        self.assertNotIn("saturation", a["ruled_out"])


class IncidentDetails(unittest.TestCase):
    def test_a_cause_is_ruled_out_only_if_every_window_ruled_it_out(self):
        with tempfile.TemporaryDirectory() as d:
            store = Store(Path(d) / "t.db")
            mon = Monitor(store, 30.0)
            t0 = time.time() - 3600
            links = [LinkUsage(30, 5, 10, 5, None), LinkUsage(30, 5, 10, 5, None), LinkUsage(230, 5, 76, 5, None)]
            for i, link in enumerate(links + [None, None]):
                mon.step(lossy(40 if i < 3 else 0, link), [], now=t0 + (i + 1) * 30)
            inc = store.incidents_between(0, 2e10)[0]
            self.assertEqual(inc.code, "isp")
            self.assertIn("saturation", inc.details["not_ruled_out"])  # 76% in the 3rd window: can't rule it out
            self.assertEqual(inc.details["link"]["down_pct"], 76)
            doc = build_report(store, t0, t0 + 600, lang="es", now=t0 + 600)
            from isitmyisp.report import ICON_OK, ICON_Q
            self.assertIn(f'<div>{ICON_Q}Saturación por tu propio tráfico', doc)
            self.assertNotIn("por debajo del 70%", doc)  # the ISP message must not claim it
            store.close()

    def test_message_claims_quiet_link_only_when_proven(self):
        with tempfile.TemporaryDirectory() as d:
            store = Store(Path(d) / "t.db")
            mon = Monitor(store, 30.0)
            t0 = time.time() - 3600
            for i in range(5):
                link = LinkUsage(30, 5, 10, 5, 15)
                mon.step(lossy(40 if i < 3 else 0, link), [], now=t0 + (i + 1) * 30)
            doc = build_report(store, t0, t0 + 600, lang="es", now=t0 + 600)
            self.assertIn("por debajo del 70% de la velocidad contratada", doc)
            from isitmyisp.report import ICON_OK
            self.assertIn(f"<div>{ICON_OK}Tu enlace no estaba lleno", doc)
            store.close()


class LinkSettings(unittest.TestCase):
    def test_validation(self):
        good = {"enabled": True, "host": "192.168.1.1", "community": "ro-secret", "port": 161,
                "interface": "ether1", "down_mbps": 1000, "up_mbps": 1000}
        self.assertEqual(settings_mod.validate({"link": good})["link"]["down_mbps"], 1000.0)
        for bad in ({**good, "host": "router.local"}, {**good, "community": ""}, {**good, "down_mbps": 0}):
            with self.assertRaises(settings_mod.SettingsError):
                settings_mod.validate({"link": bad})
        settings_mod.validate({"link": {**good, "enabled": False, "community": ""}})  # disabled: anything goes


if __name__ == "__main__":
    unittest.main()
