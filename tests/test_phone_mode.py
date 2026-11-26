"""The phone mode (/phone): the verdict, the path, the last incident and the last speed test, in one column."""

import re
import time

from isitmyisp import settings as settings_mod
from tests.test_webapp import WebAppBase


class PhoneMode(WebAppBase):
    def page(self, lang="en"):
        return self.client.get(f"/phone?lang={lang}")

    def test_needs_sign_in_like_the_dashboard(self):
        self.create_admin()
        r = self.app.test_client().get("/phone")
        self.assertEqual(r.status_code, 302)
        self.assertIn("/login", r.headers["Location"])

    def test_shows_the_four_blocks_without_javascript(self):
        self.create_admin()
        r = self.page()
        self.assertEqual(r.status_code, 200)
        html = r.get_data(as_text=True)
        self.assertIn("Internet is working", html)                     # the verdict
        self.assertIn('class="ph-path', html)                           # the path: home, ISP, internet
        self.assertEqual(len(re.findall(r'<li class="s-', html)), 3)
        self.assertIn("Last incident", html)
        self.assertIn("No incidents in the last 30 days.", html)
        self.assertIn("The speed test is off", html)                    # off by default: says so, measures nothing
        self.assertIn('href="/"', html)                                 # the way back to the full dashboard
        self.assertNotIn('class="nav"', html)                           # no sidebar
        self.assertNotIn("<script", html)
        self.assertIn('class="theme-btn to-dark"', html)                # light / dark, by link

    def test_speed_against_the_plan(self):
        from isitmyisp import demo
        self.create_admin()
        settings_mod.save(self.store, {"speedtest": {"enabled": True, "accepted": True},
                                       "link": {"down_mbps": 300, "up_mbps": 30}})
        self.assertIn("No test yet", self.page().get_data(as_text=True))
        demo.add_speed_result(self.store)
        html = self.page().get_data(as_text=True)
        self.assertIn("287</b> Mbps", html)                             # the best engine, as on the dashboard and TV
        self.assertIn("96% of 300 Mbps", html)
        self.assertIn('class="bar-fill"', html)

    def test_spanish_and_the_theme_cookie(self):
        self.create_admin()
        self.client.set_cookie("theme", "dark")
        html = self.page("es").get_data(as_text=True)
        self.assertIn('data-theme="dark"', html)
        self.assertIn("Último incidente", html)
        self.assertIn("Abrir el panel completo", html)

    def test_an_ongoing_incident_is_the_last_one(self):
        from isitmyisp.classifier import Measurements
        from isitmyisp.monitor import Monitor
        from tests.test_webapp import w
        self.create_admin()
        mon = Monitor(self.store, 30.0)
        for i in range(6):   # the ISP's first hop and everything past it stop answering
            m = Measurements([w("192.168.1.1", 15, 15, 2.0)], w("181.0.0.1", 15, 0),
                             [w(a, 15, 0) for a in ("1.1.1.1", "8.8.8.8", "9.9.9.9")], {})
            mon.step(m, [("home", m.home[0]), ("isp", m.isp_hop)] + [("anchor", a) for a in m.anchors],
                     now=time.time() - (6 - i) * 30)
        html = self.page().get_data(as_text=True)
        self.assertIn('class="ph-ev g-isp now"', html)
        self.assertIn("ongoing", html)
        self.assertIn("The evidence points here", html)
