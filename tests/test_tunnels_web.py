import json
import tempfile
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from isitmyisp.classifier import Measurements
from isitmyisp.config import ConfigError, Tunnel, parse
from isitmyisp.monitor import Monitor
from isitmyisp.probes.icmp import WindowStats
from isitmyisp.store import Store
from isitmyisp.timeutil import parse_when
from isitmyisp.tunnels import classify_tunnel, periodic_interval
from isitmyisp.web import metrics_text, start_server

T = Tunnel("branch", "198.51.100.20", "10.10.0.1", "ipsec-l2tp")
T0 = 1_794_000_000.0
WIN = 30.0


def w(target, sent, received, med=40.0):
    ok = received > 0
    return WindowStats(target, sent, received, med if ok else None, med if ok else None, med if ok else None,
                       0.5 if ok else None, med if ok else None)


class TunnelVerdicts(unittest.TestCase):
    def test_up(self):
        self.assertEqual(classify_tunnel(T, w(T.underlay, 15, 15), w(T.overlay, 15, 15), True).code, "up")

    def test_config_when_path_is_clean(self):
        v = classify_tunnel(T, w(T.underlay, 15, 15), w(T.overlay, 15, 0), True)
        self.assertEqual(v.code, "config")

    def test_path_remote_when_our_internet_is_fine(self):
        v = classify_tunnel(T, w(T.underlay, 15, 7), w(T.overlay, 15, 6), internet_ok=True)
        self.assertEqual(v.code, "path_remote")

    def test_path_local_when_our_internet_is_bad(self):
        v = classify_tunnel(T, w(T.underlay, 15, 7), w(T.overlay, 15, 6), internet_ok=False)
        self.assertEqual(v.code, "path_local")

    def test_unknown_when_far_end_filters_icmp(self):
        v = classify_tunnel(T, w(T.underlay, 15, 0), w(T.overlay, 15, 0), True, underlay_ever_answered=False)
        self.assertEqual(v.code, "unknown")

    def test_silent_underlay_that_used_to_answer_is_path(self):
        v = classify_tunnel(T, w(T.underlay, 15, 0), w(T.overlay, 15, 0), True, underlay_ever_answered=True)
        self.assertEqual(v.code, "path_remote")

    def test_one_lost_packet_through_tunnel_is_noise(self):
        self.assertEqual(classify_tunnel(T, w(T.underlay, 15, 15), w(T.overlay, 15, 14), True).code, "up")


class Periodic(unittest.TestCase):
    def test_regular_drops_detected(self):
        starts = [T0 + i * 7200 + d for i, d in enumerate([0, 30, -20, 10])]
        self.assertAlmostEqual(periodic_interval(starts), 7200, delta=60)

    def test_irregular_drops_ignored(self):
        self.assertIsNone(periodic_interval([T0, T0 + 1000, T0 + 9000, T0 + 9500]))

    def test_needs_three_events(self):
        self.assertIsNone(periodic_interval([T0, T0 + 7200]))


class ConfigParsing(unittest.TestCase):
    def test_valid(self):
        cfg = parse({"tunnel": [{"name": "a", "underlay": "203.0.113.1", "overlay": "10.0.0.1", "type": "wireguard"}]})
        self.assertEqual(cfg.tunnels[0], Tunnel("a", "203.0.113.1", "10.0.0.1", "wireguard"))

    def test_errors(self):
        for bad in ({"tunnel": [{"name": "a", "underlay": "not-an-ip", "overlay": "10.0.0.1"}]},
                    {"tunnel": [{"name": "a", "overlay": "10.0.0.1"}]},
                    {"tunnel": [{"name": "a", "underlay": "1.2.3.4", "overlay": "10.0.0.1", "type": "pptp"}]},
                    {"tunnel": [{"name": "a", "underlay": "1.2.3.4", "overlay": "10.0.0.1"},
                                {"name": "a", "underlay": "1.2.3.5", "overlay": "10.0.0.2"}]}):
            with self.assertRaises(ConfigError):
                parse(bad)

    def test_parse_when(self):
        self.assertEqual(parse_when("2d", now=T0), T0 - 2 * 86400)
        with self.assertRaises(ValueError):
            parse_when("yesterday")


def healthy_internet():
    n = 15
    home = [w("192.168.1.1", n, n, 2.0)]
    anchors = [w(a, n, n, 30.0) for a in ("1.1.1.1", "8.8.8.8", "9.9.9.9")]
    tcp = {a.target: w(f"tcp://{a.target}:443", 10, 10, 31.0) for a in anchors}
    m = Measurements(home, w("181.0.0.1", n, n, 5.0), anchors, tcp)
    return m, [("home", home[0])] + [("anchor", a) for a in anchors]


class MonitorTunnels(unittest.TestCase):
    def test_tunnel_incident_with_scope_and_capture(self):
        with tempfile.TemporaryDirectory() as d:
            store = Store(Path(d) / "t.db")
            captured = []
            mon = Monitor(store, WIN, capture=lambda target, iid: captured.append(target))
            seq = ["up", "down", "down", "down", "up", "up"]
            for i, state in enumerate(seq):
                m, rows = healthy_internet()
                over = w(T.overlay, 15, 15 if state == "up" else 0)
                mon.step(m, rows, now=T0 + (i + 1) * WIN, tunnels=[(T, w(T.underlay, 15, 15), over)])
            self.assertEqual(store.incidents_between(0, 2e9), [])  # internet scope untouched
            incs = store.incidents_between(0, 2e9, scope="tunnels")
            self.assertEqual(len(incs), 1)
            self.assertEqual((incs[0].code, incs[0].tunnel), ("config", "branch"))
            self.assertIsNotNone(incs[0].closed)
            self.assertEqual(captured, [T.underlay])  # evidence of the path outside the tunnel
            store.close()


class Web(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.store = Store(Path(cls.tmp.name) / "w.db")
        mon = Monitor(cls.store, WIN)
        for i in range(4):
            m, rows = healthy_internet()
            mon.step(m, rows, now=T0 + (i + 1) * WIN)
        cls.httpd = start_server(cls.store, "127.0.0.1:0")
        cls.base = f"http://127.0.0.1:{cls.httpd.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.store.close()
        cls.tmp.cleanup()

    def get(self, path):
        with urllib.request.urlopen(self.base + path, timeout=5) as r:
            return r.status, r.headers.get("Content-Type"), r.read().decode()

    def test_dashboard(self):
        code, ctype, body = self.get("/?lang=es")
        self.assertEqual(code, 200)
        self.assertIn("text/html", ctype)
        self.assertIn('http-equiv="refresh"', body)
        self.assertNotIn("<script", body)

    def test_status_json(self):
        _, ctype, body = self.get("/api/status")
        data = json.loads(body)
        self.assertEqual(data["verdict"], "ok")
        self.assertEqual(ctype, "application/json")

    def test_metrics_format(self):
        _, _, body = self.get("/metrics")
        self.assertIn('isitmyisp_verdict{code="ok"} 1', body)
        self.assertIn('isitmyisp_loss_ratio{role="anchor",target="1.1.1.1"} 0.0', body)
        for line in body.splitlines():
            self.assertTrue(line.startswith(("# HELP isitmyisp_", "# TYPE isitmyisp_", "isitmyisp_")), line)

    def test_report_and_404(self):
        code, _, body = self.get("/report?since=2026-01-01")
        self.assertEqual(code, 200)
        self.assertIn("<svg", body)
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.get("/nope")
        self.assertEqual(ctx.exception.code, 404)

    def test_metrics_text_escapes_labels(self):
        self.assertIn("isitmyisp_incidents_total", metrics_text(self.store))


if __name__ == "__main__":
    unittest.main()
