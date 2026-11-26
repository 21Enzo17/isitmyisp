"""The phone mode (/phone): whose fault and why, the path hop by hop, what changed, the last 24 h, what's
affected and the capacity, in one column and without JavaScript."""

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
        self.assertIn("Last 24 hours", html)                            # the 24 h strip and the latest incidents
        self.assertIn('class="ph-strip strip"', html)
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
        self.assertIn("Últimos incidentes", html)
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
        self.assertIn('class="ph-claim"', html)                       # the ISP is blamed: the report is the button

    def test_a_service_down_is_named_even_with_internet_working(self):
        from types import SimpleNamespace

        from isitmyisp.webapp import views
        self.create_admin()
        self.assertNotIn('class="ph-card ph-alert"', self.page().get_data(as_text=True))
        orig = views.service_cards
        views.service_cards = lambda *a, **k: [SimpleNamespace(name="ERP", state="down", ms=None, since=None),
                                               SimpleNamespace(name="Mail", state="up", ms=20.0, since=None)]
        try:
            html = self.page().get_data(as_text=True)
        finally:
            views.service_cards = orig
        self.assertIn('class="ph-card ph-alert"', html)
        self.assertIn("Not answering: ERP", html)
        self.assertIn('<span class="ph-tag bad">ERP</span>', html)    # grouped: the failing one by name
        self.assertIn('<span class="ph-tag ok">1 OK</span>', html)     # the rest as a count
        self.assertLess(html.index("What&#39;s affected"), html.index("Your connection"))   # first, while it fails

    def test_the_report_is_one_tap_away(self):
        self.create_admin()
        html = self.page().get_data(as_text=True)
        self.assertIn('href="/report?since=7d"', html)                 # quiet link when the ISP isn't blamed
        self.assertNotIn('class="ph-claim"', html)

    def test_the_link_load_from_the_router(self):
        from isitmyisp.snmp import LinkUsage
        self.create_admin()
        self.assertNotIn("Link load", self.page().get_data(as_text=True))   # SNMP off: no card at all
        settings_mod.save(self.store, {"link": {"enabled": True, "host": "192.168.1.1", "community": "test-ro", "down_mbps": 300, "up_mbps": 30}})
        self.assertIn("Can&#39;t read the router", self.page().get_data(as_text=True))
        self.store.add_link_usage(time.time() - 60, LinkUsage(120.0, 6.0, 40.0, 20.0, 12.0))
        html = self.page().get_data(as_text=True)
        self.assertIn("Link load", html)
        self.assertIn("40% of contract", html)
        self.assertIn("Router CPU", html)
        self.assertIn("<b>12%</b>", html)
        self.assertIn("Room to spare", html)
        self.store.add_link_usage(time.time() - 30, LinkUsage(290.0, 6.0, 96.7, 20.0, 12.0))
        self.assertIn("The link is full", self.page().get_data(as_text=True))

    def test_on_the_backup_link_it_says_so_in_a_sentence(self):
        from isitmyisp.monitor import Monitor
        main = {"isp_hop": "181.89.4.100", "isp_asn": "AS7303", "isp_name": "Telecom",
                "path": [{"index": 2, "host": "181.89.4.100", "segment": "isp", "asn": "AS7303", "as_name": "Telecom"}]}
        backup = {"isp_hop": "190.2.3.4", "isp_asn": "AS11664", "isp_name": "Claro",
                  "path": [{"index": 2, "host": "190.2.3.4", "segment": "isp", "asn": "AS11664", "as_name": "Claro"}]}
        mon = Monitor(self.store, 30.0)
        mon.observe_network(main)
        mon.observe_network(backup)
        self.store.add_network(backup)
        self.create_admin()
        html = self.page().get_data(as_text=True)
        self.assertIn("Internet works, on the backup link", html)
        self.assertIn('class="ph-advice ph-backup"', html)
        self.assertIn("Going out through Claro", html)
        self.assertIn("Your main ISP, Telecom, is not in use.", html)

    def test_why_ping_against_tcp_and_the_isp_as_text(self):
        from isitmyisp.classifier import Measurements
        from isitmyisp.monitor import Monitor
        from tests.test_webapp import w
        self.create_admin()
        self.store.add_network({"isp_hop": "181.0.0.1", "isp_asn": "AS7303", "isp_name": "Telecom", "gateway": "192.168.1.1"})
        mon = Monitor(self.store, 30.0)
        for i in range(6):
            m = Measurements([w("192.168.1.1", 15, 15, 2.0)], w("181.0.0.1", 15, 0),
                             [w(a, 15, 0) for a in ("1.1.1.1", "8.8.8.8", "9.9.9.9")], {})
            mon.step(m, [("home", m.home[0]), ("isp", m.isp_hop)] + [("anchor", a) for a in m.anchors]
                     + [("tcp", w("tcp://1.1.1.1:443", 15, 15, 31.0))],
                     now=time.time() - (6 - i) * 30)
        html = self.page().get_data(as_text=True)
        self.assertIn('<details class="ph-why">', html)                # the evidence, folded under the verdict
        self.assertIn("Why we say so", html)
        self.assertIn('<span class="ip">AS7303</span>', html)          # the ISP's ASN and hop, selectable text
        self.assertIn('<span class="ip">181.0.0.1</span>', html)
        self.assertIn("Each destination: ping and TCP 443", html)
        self.assertRegex(html, r'<td class="ip">1\.1\.1\.1</td><td>—</td>\s*<td>31 ms</td>')   # ping lost, TCP answers
        self.assertIn('class="ph-spark"', html)                         # 6 h of latency on each hop
        self.assertRegex(html, r'<b>since \d\d:\d\d</b>')             # a clock time, not "x min ago"

    def test_what_changed_shows_only_when_something_did(self):
        self.create_admin()
        self.assertNotIn("What changed", self.page().get_data(as_text=True))
        iid = self.store.open_incident("public_ip", ["203.0.113.7 → 198.51.100.9"], ts=time.time() - 600, scope="public_ip")
        self.store.set_incident_details(iid, {"expected": "203.0.113.7", "seen": "198.51.100.9"})
        html = self.page().get_data(as_text=True)
        self.assertIn("What changed", html)
        self.assertIn("Your public IP isn&#39;t the fixed one: 203.0.113.7 → 198.51.100.9", html)

    def test_the_speed_folds_and_the_actions_are_at_the_end(self):
        from isitmyisp import demo
        self.create_admin()
        settings_mod.save(self.store, {"speedtest": {"enabled": True, "accepted": True},
                                       "link": {"down_mbps": 300, "up_mbps": 30}})
        demo.add_speed_result(self.store)
        html = self.page().get_data(as_text=True)
        self.assertIn('<details class="ph-speed">', html)
        self.assertRegex(html, r"<summary><span>Download</span> <b>287</b> Mbps · 96% of 300 Mbps</summary>")
        self.assertIn('href="/check"', html)                            # test from this phone
        self.assertIn('href="/chart?span=1h"', html)                    # the last hour, in detail
        self.assertIn('<meta http-equiv="refresh" content="30">', html)
