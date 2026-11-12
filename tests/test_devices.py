"""Devices on your network: validation (private addresses only here), checks and incidents."""

import shutil
import socket
import tempfile
import time
import unittest
from pathlib import Path

from isitmyisp import alerts
from isitmyisp.classifier import Measurements
from isitmyisp.devices import Device, DeviceError, check, check_ping, validate
from isitmyisp.monitor import Monitor
from isitmyisp.probes.icmp import WindowStats
from isitmyisp.services import Check
from isitmyisp.store import Store

WIN = 30.0


def w(target, sent, received, med=30.0):
    ok = received > 0
    return WindowStats(target, sent, received, med if ok else None, med if ok else None, med if ok else None,
                       0.5 if ok else None, med if ok else None)


def network(home_loss=0):
    n = 15
    lost = round(n * home_loss / 100)
    anchors = [w(a, n, n - lost) for a in ("1.1.1.1", "8.8.8.8", "9.9.9.9")]
    tcp = {a.target: w(f"tcp://{a.target}:443", 10, 10 - round(10 * home_loss / 100)) for a in anchors}
    m = Measurements([w("192.168.1.1", n, n - lost, 2.0)], w("181.0.0.1", n, n - lost, 5.0), anchors, tcp)
    return m, [("home", m.home[0])] + [("anchor", a) for a in anchors]


class Validation(unittest.TestCase):
    def test_only_addresses_on_your_network(self):
        ok = validate([{"name": "Posnet", "kind": "pos", "target": "192.168.1.60"},
                       {"name": "Impresora", "kind": "printer", "target": "impresora.local", "port": "9100"},
                       {"name": "NVR", "kind": "camera", "target": "nvr", "port": 554},
                       {"name": "AP", "kind": "ap", "target": "fe80::1"}])
        self.assertEqual([d["port"] for d in ok], [None, 9100, 554, None])
        for bad in ([{"name": "x", "kind": "pos", "target": "8.8.8.8"}],              # public: goes in services
                    [{"name": "x", "kind": "pos", "target": "www.banco.com.ar"}],
                    [{"name": "x", "kind": "toaster", "target": "192.168.1.2"}],
                    [{"name": "x", "kind": "pos", "target": "192.168.1.2", "port": "70000"}],
                    [{"name": "", "kind": "pos", "target": "192.168.1.2"}],
                    [{"name": "a", "kind": "pos", "target": "10.0.0.1"}, {"name": "a", "kind": "pos", "target": "10.0.0.2"}]):
            with self.assertRaises(DeviceError, msg=bad):
                validate(bad)

    def test_endpoint_and_how(self):
        self.assertEqual(Device("p", "printer", "192.168.1.70", 9100).endpoint, "192.168.1.70:9100")
        self.assertEqual(Device("p", "pos", "192.168.1.60").how, "ping")


class Checks(unittest.TestCase):
    def test_tcp_port_on_this_machine(self):
        srv = socket.socket()
        srv.bind(("127.0.0.1", 0))
        srv.listen()
        port = srv.getsockname()[1]
        try:
            self.assertTrue(check(Device("x", "printer", "127.0.0.1", port)).ok)
        finally:
            srv.close()
        self.assertFalse(check(Device("x", "printer", "127.0.0.1", port)).ok)    # nothing listening now

    @unittest.skipUnless(shutil.which("ping") or shutil.which("fping"), "needs ping")
    def test_ping_names_the_failure(self):
        bad = check_ping("nonexistent-host.invalid", timeout=1)
        self.assertFalse(bad.ok)
        self.assertIn(bad.detail, ("name not found", "no reply to ping", "timeout"))


class Incidents(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name) / "d.db")

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def run_with(self, home_loss):
        dev = Device("Posnet caja 1", "pos", "192.168.1.60")
        mon = Monitor(self.store, WIN)
        t0 = time.time() - 3600
        checks = []
        for i in range(8):
            now = t0 + (i + 1) * WIN
            ok = i not in (2, 3, 4)
            checks.append(Check(now - 5, ok, 1.2 if ok else None, "ping OK" if ok else "no reply to ping"))
            m, rows = network(home_loss)
            mon.step(m, rows, now=now, devices=[(dev, list(checks))])
        return self.store.incidents_between(0, 2e10, scope="device:Posnet caja 1")

    def test_device_down_while_your_network_is_fine_is_the_device(self):
        incs = self.run_with(home_loss=0)
        self.assertEqual(len(incs), 1)
        self.assertEqual(incs[0].code, "device_down")
        self.assertIsNotNone(incs[0].closed)
        self.assertIn("192.168.1.60 (ping): no reply to ping", incs[0].evidence[0])
        self.assertIn("device:Posnet caja 1", {s["role"] for s in self.store.latest_samples()})

    def test_not_blamed_on_the_device_when_your_network_fails(self):
        self.assertEqual(self.run_with(home_loss=40), [])

    def test_alert_says_it_is_the_device(self):
        incs = self.run_with(home_loss=0)
        title, body = alerts.describe(incs[0], "opened", "es")
        self.assertIn("Dispositivo Posnet caja 1", title)
        self.assertIn("es el aparato", body)
