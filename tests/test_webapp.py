"""Security and page tests for the web UI. Skipped when the [web] extra is not installed."""

import re
import tempfile
import unittest
from pathlib import Path

try:
    import flask  # noqa: F401
    HAVE_WEB = True
except ImportError:  # pragma: no cover
    HAVE_WEB = False

from isitmyisp import settings as settings_mod
from isitmyisp.classifier import Measurements
from isitmyisp.monitor import Monitor
from isitmyisp.probes.icmp import WindowStats
from isitmyisp.store import Store

PASSWORD = "correct horse battery"
T0 = 1_794_000_000.0


def w(target, sent, received, med=30.0):
    ok = received > 0
    return WindowStats(target, sent, received, med, med, med, 0.5, med if ok else None)


def csrf(html: str) -> str:
    m = re.search(r'name="csrf_token" value="([^"]+)"', html)
    assert m, "no csrf token in page"
    return m.group(1)


@unittest.skipUnless(HAVE_WEB, "web extra not installed")
class WebAppBase(unittest.TestCase):
    bind = "127.0.0.1:8080"

    def setUp(self):
        from isitmyisp.webapp import create_app
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name) / "w.db")
        mon = Monitor(self.store, 30.0)
        for i in range(3):
            n = 15
            anchors = [w(a, n, n) for a in ("1.1.1.1", "8.8.8.8", "9.9.9.9")]
            m = Measurements([w("192.168.1.1", n, n, 2.0)], w("181.0.0.1", n, n, 5.0), anchors,
                             {a.target: w(f"tcp://{a.target}:443", 10, 10) for a in anchors})
            mon.step(m, [("home", m.home[0]), ("isp", m.isp_hop)] + [("anchor", a) for a in anchors],
                     now=__import__("time").time() - (3 - i) * 30)
        self.app = create_app(self.store, data_dir=Path(self.tmp.name), bind=self.bind)
        self.app.config["TESTING"] = True
        self.client = self.app.test_client()

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def create_admin(self):
        token = settings_mod.issue_setup_token(self.store)
        page = self.client.get(f"/setup?token={token}").get_data(as_text=True)
        r = self.client.post("/setup", data={"csrf_token": csrf(page), "token": token, "username": "admin",
                                             "password": PASSWORD, "confirm": PASSWORD})
        self.assertEqual(r.status_code, 302)
        return r

    def login(self, password=PASSWORD, next_=None):
        page = self.client.get("/login").get_data(as_text=True)
        url = "/login" + (f"?next={next_}" if next_ else "")
        return self.client.post(url, data={"csrf_token": csrf(page), "username": "admin", "password": password})


class Setup(WebAppBase):
    def test_redirects_to_setup_without_users(self):
        r = self.client.get("/")
        self.assertEqual(r.status_code, 302)
        self.assertIn("/setup", r.headers["Location"])

    def test_wrong_setup_token_is_rejected(self):
        settings_mod.issue_setup_token(self.store)
        page = self.client.get("/setup").get_data(as_text=True)
        r = self.client.post("/setup", data={"csrf_token": csrf(page), "token": "nope", "username": "admin",
                                             "password": PASSWORD, "confirm": PASSWORD})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(self.store.user_count(), 0)

    def test_setup_creates_argon2id_admin_and_logs_in(self):
        self.create_admin()
        row = self.store.get_user(username="admin")
        self.assertTrue(row[2].startswith("$argon2id$"))
        self.assertEqual(self.client.get("/").status_code, 200)
        self.assertEqual(self.client.get("/setup").status_code, 404)  # one-time

    def test_short_password_rejected(self):
        token = settings_mod.issue_setup_token(self.store)
        page = self.client.get("/setup").get_data(as_text=True)
        r = self.client.post("/setup", data={"csrf_token": csrf(page), "token": token, "username": "admin",
                                             "password": "short", "confirm": "short"})
        self.assertEqual(r.status_code, 400)


class LocalAuth(WebAppBase):
    def setUp(self):
        super().setUp()
        self.create_admin()
        self.client.post("/logout", data={"csrf_token": csrf(self.client.get("/settings").get_data(as_text=True))})

    def test_pages_need_login(self):
        for path in ("/", "/incidents", "/tunnels", "/reports", "/settings", "/report"):
            r = self.client.get(path)
            self.assertEqual(r.status_code, 302, path)
            self.assertIn("/login", r.headers["Location"])
        self.assertEqual(self.client.get("/api/status").status_code, 401)
        self.assertEqual(self.client.get("/metrics").status_code, 401)

    def test_healthz_is_public_and_minimal(self):
        r = self.client.get("/healthz")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json(), {"ok": True})

    def test_metrics_bearer_token(self):
        token = settings_mod.metrics_token(self.store)
        self.assertEqual(self.client.get("/metrics", headers={"Authorization": f"Bearer {token}"}).status_code, 200)
        self.assertEqual(self.client.get("/metrics", headers={"Authorization": "Bearer wrong"}).status_code, 401)

    def test_bad_then_good_login(self):
        self.assertEqual(self.login("wrong password!").status_code, 401)
        r = self.login()
        self.assertEqual(r.status_code, 302)
        self.assertEqual(self.client.get("/").status_code, 200)

    def test_no_open_redirect(self):
        r = self.login(next_="//evil.example/x")
        self.assertEqual(r.headers["Location"], "/")

    def test_login_rate_limited(self):
        codes = [self.login("wrong password!").status_code for _ in range(11)]
        self.assertEqual(codes[-1], 429)


class CsrfAndSettings(WebAppBase):
    def setUp(self):
        super().setUp()
        self.create_admin()

    def page(self):
        return self.client.get("/settings").get_data(as_text=True)

    def test_post_without_csrf_token_is_rejected(self):
        r = self.client.post("/settings/general", data={"anchors": "1.1.1.1", "interval": "2", "window": "30",
                                                        "lang": "en"})
        self.assertEqual(r.status_code, 400)

    def test_cross_origin_post_is_rejected(self):
        r = self.client.post("/settings/general", headers={"Origin": "https://evil.example"},
                             data={"csrf_token": csrf(self.page()), "anchors": "1.1.1.1", "interval": "2",
                                   "window": "30", "lang": "en"})
        self.assertEqual(r.status_code, 403)

    def test_save_settings_bumps_version(self):
        before = self.store.settings_version()
        r = self.client.post("/settings/general", data={"csrf_token": csrf(self.page()), "anchors": "1.1.1.1\n9.9.9.9",
                                                        "interval": "1.5", "window": "20", "lang": "es"})
        self.assertEqual(r.status_code, 302)
        s = settings_mod.load(self.store)
        self.assertEqual((s.anchors, s.interval, s.window, s.lang), (["1.1.1.1", "9.9.9.9"], 1.5, 20, "es"))
        self.assertGreater(self.store.settings_version(), before)

    def test_invalid_anchor_rejected(self):
        r = self.client.post("/settings/general", data={"csrf_token": csrf(self.page()), "anchors": "192.168.1.1",
                                                        "interval": "2", "window": "30", "lang": "en"})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(settings_mod.load(self.store).anchors, settings_mod.DEFAULTS["anchors"])

    def test_tunnel_add_and_delete(self):
        r = self.client.post("/settings/tunnels/add", data={"csrf_token": csrf(self.page()), "name": "branch",
                                                            "underlay": "203.0.113.10", "overlay": "10.10.0.1",
                                                            "type": "ipsec-l2tp"})
        self.assertEqual(r.status_code, 302)
        self.assertEqual([t.name for t in settings_mod.load(self.store).tunnels], ["branch"])
        self.client.post("/settings/tunnels/delete", data={"csrf_token": csrf(self.page()), "name": "branch"})
        self.assertEqual(settings_mod.load(self.store).tunnels, [])

    def test_cannot_lock_yourself_out_with_proxy_mode(self):
        r = self.client.post("/settings/access", data={"csrf_token": csrf(self.page()), "auth_mode": "proxy",
                                                       "proxy_header": "Remote-User", "trusted_proxies": "10.0.0.5"})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(settings_mod.load(self.store).auth_mode, "local")

    def test_security_headers_and_no_scripts(self):
        r = self.client.get("/")
        csp = r.headers["Content-Security-Policy"]
        self.assertIn("default-src 'none'", csp)
        self.assertNotIn("script-src", csp)
        self.assertEqual(r.headers["X-Frame-Options"], "DENY")
        html = r.get_data(as_text=True)
        self.assertNotIn("<script", html)
        self.assertNotIn(' style="', html)  # inline styles would be blocked by the CSP
        self.assertIn("Internet is working", html)           # the verdict as a sentence
        self.assertIn('class="path"', html)                  # your network -> your ISP -> internet
        self.assertIn("font-src 'self'", csp)                 # self-hosted font, no third parties
        font = self.client.get("/static/fonts/ibm-plex-sans-400.woff2")
        self.assertEqual(font.mimetype, "font/woff2")

    def test_services_add_and_delete(self):
        r = self.client.post("/settings/services/add", data={"csrf_token": csrf(self.page()), "name": "ARCA",
                                                             "kind": "http", "target": "https://www.afip.gob.ar/"})
        self.assertEqual(r.status_code, 302)
        self.assertEqual([sv.name for sv in settings_mod.load(self.store).services], ["ARCA"])
        bad = self.client.post("/settings/services/add", data={"csrf_token": csrf(self.page()), "name": "X",
                                                               "kind": "http", "target": "not a url"})
        self.assertEqual(bad.status_code, 400)
        self.client.post("/settings/services/delete", data={"csrf_token": csrf(self.page()), "name": "ARCA"})
        self.assertEqual(settings_mod.load(self.store).services, [])

    def test_alerts_save_and_test_button(self):
        from unittest import mock
        from isitmyisp import alerts
        form = {"csrf_token": csrf(self.page()), "min_minutes": "3", "telegram_enabled": "1",
                "telegram_bot_token": "123456789:" + "B" * 35, "telegram_chat_id": "42", "action": "test"}
        with mock.patch.object(alerts, "send_all", return_value={"telegram": "ok"}) as sent:
            r = self.client.post("/settings/alerts", data=form)
        self.assertEqual(r.status_code, 200)
        self.assertTrue(sent.called)
        html = r.get_data(as_text=True)
        self.assertIn("telegram: ok", html)
        self.assertNotIn("B" * 35, html)  # the token is never rendered back
        self.assertEqual(alerts.load(self.store)["min_minutes"], 3)

    def test_link_settings_and_interface_listing(self):
        from unittest import mock
        form = {"csrf_token": csrf(self.page()), "enabled": "1", "host": "192.168.1.1", "community": "ro-secret",
                "port": "161", "interface": "ether1", "down_mbps": "1000", "up_mbps": "300"}
        with mock.patch("isitmyisp.snmp.interfaces", return_value=[(1, "lo"), (2, "ether1"), (3, "bridge")]):
            r = self.client.post("/settings/link", data={**form, "action": "test"})
        self.assertEqual(r.status_code, 200)
        html = r.get_data(as_text=True)
        self.assertIn("ether1 · bridge", html)
        self.assertEqual(settings_mod.load(self.store).link["enabled"], False)  # listing saves nothing
        r = self.client.post("/settings/link", data={**form, "action": "save"})
        self.assertEqual(r.status_code, 302)
        link = settings_mod.load(self.store).link
        self.assertEqual((link["enabled"], link["up_mbps"]), (True, 300.0))
        self.assertNotIn("ro-secret", self.client.get("/settings").get_data(as_text=True))  # never rendered back

    def test_language_switch_is_remembered(self):
        r = self.client.get("/?lang=es")
        self.assertIn("isitmyisp_lang=es", r.headers.get("Set-Cookie", ""))
        self.assertIn("Panel", self.client.get("/").get_data(as_text=True))

    def test_every_page_renders(self):
        for path in ("/", "/incidents", "/tunnels", "/reports", "/settings", "/report?since=1d", "/api/status"):
            self.assertEqual(self.client.get(path).status_code, 200, path)


class ProxyMode(WebAppBase):
    def setUp(self):
        super().setUp()
        settings_mod.save(self.store, {"auth_mode": "proxy", "trusted_proxies": ["127.0.0.1/32"]})

    def test_trusted_proxy_with_header(self):
        r = self.client.get("/", headers={"Remote-User": "enzo"})
        self.assertEqual(r.status_code, 200)
        self.assertIn("enzo", r.get_data(as_text=True))

    def test_missing_header_or_untrusted_source(self):
        self.assertEqual(self.client.get("/").status_code, 403)
        r = self.client.get("/", headers={"Remote-User": "enzo"}, environ_base={"REMOTE_ADDR": "192.168.1.50"})
        self.assertEqual(r.status_code, 403)


class NoneModeLoopback(WebAppBase):
    def setUp(self):
        super().setUp()
        settings_mod.save(self.store, {"auth_mode": "none"})

    def test_read_only(self):
        self.assertEqual(self.client.get("/").status_code, 200)
        page = self.client.get("/settings").get_data(as_text=True)
        r = self.client.post("/settings/general", data={"csrf_token": csrf(page), "anchors": "1.1.1.1",
                                                        "interval": "2", "window": "30", "lang": "en"})
        self.assertEqual(r.status_code, 403)


class NoneModeExposed(WebAppBase):
    bind = "0.0.0.0:8080"

    def setUp(self):
        super().setUp()
        settings_mod.save(self.store, {"auth_mode": "none"})

    def test_refused_when_not_on_loopback(self):
        self.assertEqual(self.client.get("/").status_code, 403)


if __name__ == "__main__":
    unittest.main()
