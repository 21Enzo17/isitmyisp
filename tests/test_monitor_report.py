import tempfile
import unittest
from pathlib import Path

from isitmyisp.classifier import Measurements
from isitmyisp.monitor import Monitor
from isitmyisp.probes.icmp import WindowStats
from isitmyisp.report import build_report, fmt_duration, isp_message
from isitmyisp.store import Store

FIXTURES = Path(__file__).parent / "fixtures"
ANCHORS = ["1.1.1.1", "8.8.8.8", "9.9.9.9"]
T0 = 1_794_000_000.0
WIN = 30.0


def w(target, sent, received, med=30.0):
    ok = received > 0
    return WindowStats(target, sent, received, med if ok else None, med if ok else None, med if ok else None,
                       0.5 if ok else None, med if ok else None)


def measure(anchor_loss_pct=0, home_loss_pct=0):
    n = 15
    lost_a = round(n * anchor_loss_pct / 100)
    lost_h = round(n * home_loss_pct / 100)
    home = [w("192.168.1.1", n, n - lost_h, 2.0)]
    isp = w("181.0.0.1", n, n, 5.0)  # first hop fine -> loss is beyond it (ISP backbone)
    anchors = [w(a, n, n - lost_a) for a in ANCHORS]
    tcp = {a: w(f"tcp://{a}:443", 10, 10 - round(10 * anchor_loss_pct / 100)) for a in ANCHORS}
    m = Measurements(home, isp, anchors, tcp)
    rows = [("home", home[0]), ("isp", isp)] + [("anchor", a) for a in anchors]
    return m, rows


class MonitorLifecycle(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name) / "t.db")
        self.captured = []
        self.mon = Monitor(self.store, WIN, capture=lambda target, iid: self.captured.append((target, iid)),
                           recapture_every=90)

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def run_seq(self, seq):
        for i, kind in enumerate(seq):
            m, rows = measure(anchor_loss_pct=40 if kind in ("isp", "local") else 0, home_loss_pct=40 if kind == "local" else 0)
            self.mon.step(m, rows, now=T0 + (i + 1) * WIN)

    def test_single_bad_window_is_not_an_incident(self):
        self.run_seq(["ok", "isp", "ok", "ok"])
        self.assertEqual(self.store.incidents_between(0, 2e9), [])
        self.assertEqual(self.captured, [])

    def test_incident_open_close_with_capture(self):
        self.run_seq(["ok", "isp", "isp", "isp", "ok", "ok"])
        incs = self.store.incidents_between(0, 2e9)
        self.assertEqual(len(incs), 1)
        inc = incs[0]
        self.assertEqual(inc.code, "isp")
        # bad windows are #2..#4 (ending at T0+60..T0+120) -> started at T0+30, ended at T0+120
        self.assertEqual(inc.opened, T0 + WIN)
        self.assertEqual(inc.closed, T0 + 4 * WIN)
        self.assertEqual(inc.duration(), 3 * WIN)
        self.assertGreaterEqual(inc.peak_loss, 40.0)
        self.assertEqual(len(self.captured), 1)
        self.assertEqual(self.captured[0][1], inc.id)

    def test_long_incident_is_recaptured(self):
        self.run_seq(["isp"] * 8 + ["ok", "ok"])
        self.assertGreaterEqual(len(self.captured), 3)

    def test_change_of_cause_splits_incidents(self):
        self.run_seq(["isp", "isp", "isp", "local", "local", "ok", "ok"])
        incs = self.store.incidents_between(0, 2e9)
        self.assertEqual([i.code for i in incs], ["isp", "local"])
        self.assertEqual(incs[0].closed, incs[1].opened)

    def test_resume_closes_dangling_incident(self):
        self.run_seq(["isp", "isp", "isp"])  # crash before it closes
        self.assertIsNone(self.store.incidents_between(0, 2e9)[0].closed)
        Monitor(self.store, WIN).resume()
        self.assertIsNotNone(self.store.incidents_between(0, 2e9)[0].closed)


class Report(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name) / "r.db")
        self.store.add_network({"isp_name": "Telecom Argentina S.A.", "isp_asn": "AS7303", "wireless": False,
                                "cgnat": False}, ts=T0)
        mon = Monitor(self.store, WIN, capture=self._capture)
        seq = ["ok"] * 10 + ["isp"] * 4 + ["ok"] * 10
        for i, kind in enumerate(seq):
            m, rows = measure(anchor_loss_pct=40 if kind == "isp" else 0)
            mon.step(m, rows, now=T0 + (i + 1) * WIN)

    def _capture(self, target, iid):
        data = {"target": target, "reached": True, "destination_loss": 33.3, "loss_starts_at": 2,
                "hops": [{"index": 1, "host": "192.168.1.1", "loss": 0.0, "sent": 30, "avg": 1.5, "best": 1.0,
                          "worst": 2.0, "status": "ok", "asn": None, "as_name": None},
                         {"index": 2, "host": "181.89.4.100", "loss": 33.3, "sent": 30, "avg": 9.0, "best": 4.0,
                          "worst": 40.0, "status": "real_loss", "asn": "AS7303", "as_name": "Telecom Argentina S.A."},
                         {"index": 3, "host": target, "loss": 33.3, "sent": 30, "avg": 30.0, "best": 28.0,
                          "worst": 60.0, "status": "real_loss", "asn": "AS13335", "as_name": "Cloudflare, Inc."}]}
        self.store.add_capture(iid, "mtr", target, data, ts=T0 + 13 * WIN)

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def test_report_contains_the_story(self):
        doc = build_report(self.store, T0, T0 + 25 * WIN, lang="en", now=T0 + 25 * WIN)
        self.assertIn("1 incident, 2 min in total. 1 of them was inside", doc)
        self.assertIn("ISP backbone / upstream", doc)
        self.assertIn("AS7303 Telecom Argentina S.A.", doc)
        self.assertIn("loss starts at hop 2 (181.89.4.100, AS7303 Telecom Argentina S.A.)", doc)
        self.assertIn("<svg", doc)
        self.assertNotIn("<script", doc)

    def test_report_in_spanish(self):
        doc = build_report(self.store, T0, T0 + 25 * WIN, lang="es", now=T0 + 25 * WIN)
        self.assertIn("Mensaje para tu ISP", doc)
        self.assertIn("la pérdida empieza en el salto 2", doc)

    def test_empty_period(self):
        doc = build_report(self.store, T0 - 10_000, T0 - 5_000, lang="en")
        self.assertIn("No measurements in this period", doc)

    def test_compress_evidence(self):
        from isitmyisp.report import compress_evidence
        lines = ["ISP first hop 181.0.0.1: OK", "1.1.1.1: 33.3% loss (5/15)", "8.8.8.8: 33.3% loss (5/15)",
                 "9.9.9.9: 20.0% loss (3/15)"]
        self.assertEqual(compress_evidence(lines), ["ISP first hop 181.0.0.1: OK",
                                                    "1.1.1.1, 8.8.8.8: 33.3% loss (5/15)", "9.9.9.9: 20.0% loss (3/15)"])

    def test_fmt_duration(self):
        self.assertEqual(fmt_duration(42), "42 s")
        self.assertEqual(fmt_duration(125), "2 min 5 s")
        self.assertEqual(fmt_duration(3 * 3600 + 12 * 60), "3 h 12 min")
        self.assertEqual(fmt_duration(2 * 86400 + 3600), "2 d 1 h")

    def test_message_excludes_home_problems(self):
        from isitmyisp.report import R
        from isitmyisp.store import Incident
        incs = [Incident(1, T0, T0 + 60, "local", [], 30.0)]
        self.assertEqual(isp_message(incs, {}, R["en"], T0, T0 + 600, T0 + 600), R["en"]["msg_none"])


if __name__ == "__main__":
    unittest.main()
