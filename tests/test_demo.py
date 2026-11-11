import tempfile
import time
import unittest
from pathlib import Path

from isitmyisp.demo import SCENARIOS, Simulator, build
from isitmyisp.report import build_report
from isitmyisp.store import Store

try:
    import flask  # noqa: F401
    HAVE_WEB = True
except ImportError:
    HAVE_WEB = False


class Scenarios(unittest.TestCase):
    def test_each_scenario_ends_in_its_state_and_keeps_it_live(self):
        expected = {"healthy": ("ok", set()), "isp": ("isp", {"internet"}),
                    "failover": ("ok", {"failover"}), "wifi": ("local", {"internet"})}
        for sc in SCENARIOS:
            with self.subTest(scenario=sc), tempfile.TemporaryDirectory() as d:
                sim = build(Path(d) / "d.db", hours=3, scenario=sc)
                code, scopes = expected[sc]
                self.assertEqual(sim.store.last_window()[2], code)
                self.assertEqual({i.scope for i in sim.store.active_incidents()}, scopes)
                now = sim.store.last_window()[0]
                for k in range(4):                          # the live feed keeps the scenario going
                    sim.step(now + 30 * (k + 1), sim.scenario_state(sc, now + 30 * (k + 1)))
                self.assertEqual(sim.store.last_window()[2], code)
                sim.store.close()

    def test_nothing_points_at_a_real_network(self):
        with tempfile.TemporaryDirectory() as d:
            sim = build(Path(d) / "d.db", hours=1, lang="es")
            targets = {s["target"] for s in sim.store.latest_samples()}
            for t in targets:   # documentation ranges, the public anchors, or .example services
                self.assertTrue(t.startswith(("192.168.", "203.0.113.", "198.51.100.", "10.10.", "1.1.1.1",
                                              "8.8.8.8", "9.9.9.9", "tcp://", "https://")) or ".example" in t, t)
            for s in sim.services:
                self.assertIn(".example", s.target)
            sim.store.close()

    def test_reports_from_a_demo_database_say_so(self):
        with tempfile.TemporaryDirectory() as d:
            sim = build(Path(d) / "d.db", hours=2)
            doc = build_report(sim.store, time.time() - 7200, time.time(), lang="en")
            self.assertIn("Synthetic demo data", doc)
            self.assertIn("@top-center", doc)                        # on every printed page too
            sim.store.close()
            real = Store(Path(d) / "real.db")
            self.assertNotIn("Synthetic demo data", build_report(real, 0, time.time()))
            real.close()


@unittest.skipUnless(HAVE_WEB, "web extra not installed")
class DemoWeb(unittest.TestCase):
    def setUp(self):
        from isitmyisp.webapp import create_app
        self.tmp = tempfile.TemporaryDirectory()
        self.sim = build(Path(self.tmp.name) / "d.db", hours=2, scenario="isp", speed=True)

        def app(demo):
            a = create_app(self.sim.store, data_dir=Path(self.tmp.name), demo=demo)
            a.config["WTF_CSRF_ENABLED"] = False                     # prove the gate itself refuses writes
            return a.test_client()
        self.demo, self.normal = app(True), app(False)

    def tearDown(self):
        self.sim.store.close()
        self.tmp.cleanup()

    def test_no_login_read_only_and_a_banner(self):
        html = self.demo.get("/?lang=en").get_data(as_text=True)
        self.assertIn("Demo data.", html)
        self.assertIn("Your ISP&#39;s network is failing", html)
        self.assertNotIn("Test the speed now", self.demo.get("/settings?lang=en").get_data(as_text=True))
        for path in ("/settings/general", "/speedtest/run", "/settings/isp/asn", "/logout", "/setup"):
            self.assertEqual(self.demo.post(path, data={"confirm": "1"}).status_code, 403, path)

    def test_the_database_flag_never_turns_off_login(self):
        # the demo database carries _demo, but only create_app(demo=True) skips authentication
        r = self.normal.get("/")
        self.assertEqual(r.status_code, 302)
        self.assertNotIn("Demo data.", self.normal.get("/setup").get_data(as_text=True))


if __name__ == "__main__":
    unittest.main()
