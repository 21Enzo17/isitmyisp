import http.server
import tempfile
import threading
import time
import unittest
from pathlib import Path

from isitmyisp import alerts
from isitmyisp.classifier import Measurements
from isitmyisp.monitor import Monitor
from isitmyisp.probes.icmp import WindowStats
from isitmyisp.services import Check, Service, ServiceError, check_http, check_tcp, state, validate
from isitmyisp.settings import load as load_settings
from isitmyisp.store import Store

WIN = 30.0
GOOD_TG = {"telegram_enabled": "1", "telegram_bot_token": "123456789:" + "A" * 35, "telegram_chat_id": "42",
           "min_minutes": "2", "notify_close": "1"}


def w(target, sent, received, med=30.0):
    ok = received > 0
    return WindowStats(target, sent, received, med, med, med, 0.5, med if ok else None)


def internet(loss_pct=0):
    n = 15
    lost = round(n * loss_pct / 100)
    anchors = [w(a, n, n - lost) for a in ("1.1.1.1", "8.8.8.8", "9.9.9.9")]
    tcp = {a.target: w(f"tcp://{a.target}:443", 10, 10 - round(10 * loss_pct / 100)) for a in anchors}
    m = Measurements([w("192.168.1.1", n, n, 2.0)], w("181.0.0.1", n, n, 5.0), anchors, tcp)
    return m, [("home", m.home[0])] + [("anchor", a) for a in anchors]


class StoreCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name) / "t.db")

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()


class AlertSettings(StoreCase):
    def test_validate_and_mask_secrets(self):
        cfg = alerts.validate(GOOD_TG, alerts.load(self.store))
        alerts.save(self.store, cfg)
        view = alerts.masked(alerts.load(self.store))
        self.assertEqual(view["telegram"]["bot_token"], "")
        self.assertTrue(view["telegram"]["bot_token_set"])

    def test_empty_secret_keeps_the_stored_one(self):
        alerts.save(self.store, alerts.validate(GOOD_TG, alerts.load(self.store)))
        again = alerts.validate({**GOOD_TG, "telegram_bot_token": ""}, alerts.load(self.store))
        self.assertEqual(again["telegram"]["bot_token"], GOOD_TG["telegram_bot_token"])

    def test_bad_inputs(self):
        for bad in ({**GOOD_TG, "telegram_bot_token": "nope"}, {**GOOD_TG, "telegram_chat_id": "abc"},
                    {"email_enabled": "1", "email_host": "smtp.x", "email_sender": "x", "email_to": "a@b.c"},
                    {"webhook_enabled": "1", "webhook_url": "ftp://x"}, {"min_minutes": "999"}):
            with self.assertRaises(alerts.AlertError):
                alerts.validate(bad, alerts.load(self.store))

    def test_alert_settings_do_not_restart_probes(self):
        before = self.store.settings_version()
        alerts.save(self.store, alerts.validate(GOOD_TG, alerts.load(self.store)))
        self.assertEqual(self.store.settings_version(), before)


class AlertDispatch(StoreCase):
    def setUp(self):
        super().setUp()
        alerts.save(self.store, alerts.validate(GOOD_TG, alerts.load(self.store)))
        self.sent = []
        self.alerter = alerts.Alerter(self.store, lambda: "es", sender=self._fake_send)

    def _fake_send(self, cfg, title, body, extra):
        self.sent.append((extra["event"], title, body))
        return {"telegram": "ok"}

    def test_waits_for_min_minutes_then_alerts_once(self):
        t0 = time.time() - 600
        iid = self.store.open_incident("isp", ["1.1.1.1: 33% loss"], ts=t0)
        self.alerter.tick(now=t0 + 60, background=False)        # 1 min: below the 2 min threshold
        self.assertEqual(self.sent, [])
        self.alerter.tick(now=t0 + 180, background=False)       # 3 min: alert
        self.alerter.tick(now=t0 + 240, background=False)       # no duplicate
        self.assertEqual([e for e, _, _ in self.sent], ["incident_opened"])
        self.assertIn("Problema en la red del ISP", self.sent[0][1])
        self.assertIn("Qué hacer", self.sent[0][2])
        self.store.close_incident(iid, ts=t0 + 300)
        self.alerter.tick(now=t0 + 330, background=False)
        self.alerter.tick(now=t0 + 360, background=False)
        self.assertEqual([e for e, _, _ in self.sent], ["incident_opened", "incident_closed"])

    def test_short_incident_never_alerts(self):
        t0 = time.time() - 600
        iid = self.store.open_incident("local", [], ts=t0)
        self.store.close_incident(iid, ts=t0 + 60)
        self.alerter.tick(now=t0 + 400, background=False)
        self.assertEqual(self.sent, [])

    def test_restart_does_not_duplicate(self):
        t0 = time.time() - 600
        self.store.open_incident("isp", [], ts=t0)
        self.alerter.tick(now=t0 + 300, background=False)
        fresh = alerts.Alerter(self.store, lambda: "en", sender=self._fake_send)  # e.g. after a restart
        fresh.tick(now=t0 + 330, background=False)
        self.assertEqual(len(self.sent), 1)

    def test_failed_delivery_is_retried_and_recorded(self):
        calls = []
        def failing(cfg, title, body, extra):
            calls.append(1)
            return {"telegram": "Telegram answered 401: check the bot token and chat id"}
        a = alerts.Alerter(self.store, lambda: "en", sender=failing)
        t0 = time.time() - 600
        self.store.open_incident("isp", [], ts=t0)
        a.tick(now=t0 + 300, background=False)
        a.tick(now=t0 + 330, background=False)
        self.assertEqual(len(calls), 2)  # not marked as sent, so it retries
        self.assertIn("401", self.store.get_setting("_alerts_last")["errors"]["telegram"])

    def test_webhook_payload_shapes(self):
        self.assertIn("content", alerts.webhook_payload("https://discord.com/api/webhooks/1/x", "t", "b", {}))
        self.assertIn("text", alerts.webhook_payload("https://hooks.slack.com/services/x", "t", "b", {}))
        generic = alerts.webhook_payload("http://homeassistant.local:8123/api/webhook/x", "t", "b", {"code": "isp"})
        self.assertEqual((generic["title"], generic["code"]), ("t", "isp"))


class ServiceRules(StoreCase):
    def test_validate(self):
        ok = validate([{"name": "ARCA", "kind": "http", "target": "https://www.afip.gob.ar/"},
                       {"name": "ERP", "kind": "tcp", "target": "erp.example.com:443"}])
        self.assertEqual(len(ok), 2)
        for bad in ([{"name": "x", "kind": "http", "target": "www.afip.gob.ar"}],
                    [{"name": "x", "kind": "tcp", "target": "erp.example.com"}],
                    [{"name": "", "kind": "http", "target": "https://a.b/"}],
                    [{"name": "a", "kind": "http", "target": "https://a.b/"}, {"name": "a", "kind": "http", "target": "https://c.d/"}]):
            with self.assertRaises(ServiceError):
                validate(bad)

    def test_state_machine(self):
        c = lambda ok: Check(0, ok, 10.0 if ok else None, "x")  # noqa: E731
        self.assertIsNone(state([c(False), c(False)]))
        self.assertEqual(state([c(True), c(False), c(False), c(False)]), "down")
        self.assertEqual(state([c(False), c(True), c(True)]), "up")

    def _run(self, internet_loss):
        svc = Service("ARCA", "http", "https://www.afip.gob.ar/")
        mon = Monitor(self.store, WIN)
        t0 = time.time() - 3600
        checks = []
        for i in range(8):
            now = t0 + (i + 1) * WIN
            checks.append(Check(now - 5, i not in (2, 3, 4), 120.0 if i not in (2, 3, 4) else None,
                                "HTTP 200" if i not in (2, 3, 4) else "timeout"))
            m, rows = internet(internet_loss)
            mon.step(m, rows, now=now, services=[(svc, list(checks))])
        return self.store.incidents_between(0, 2e9, scope="service:ARCA")

    def test_service_down_while_internet_ok_is_their_problem(self):
        incs = self._run(internet_loss=0)
        self.assertEqual(len(incs), 1)
        self.assertEqual(incs[0].code, "service_down")
        self.assertIsNotNone(incs[0].closed)
        self.assertIn("timeout", incs[0].evidence[0])

    def test_service_always_has_a_sample_even_with_short_windows(self):
        svc = Service("ERP", "tcp", "erp.example.com:443")
        mon = Monitor(self.store, 20.0)
        now = time.time()
        m, rows = internet()
        mon.step(m, rows, now=now, services=[(svc, [Check(now - 35, True, 50.0, "TCP connect OK")])])
        self.assertIn("service:ERP", {s["role"] for s in self.store.latest_samples()})

    def test_service_down_while_internet_bad_is_not_blamed_on_service(self):
        self.assertEqual(self._run(internet_loss=40), [])


class _Handler(http.server.BaseHTTPRequestHandler):
    status = 200

    def do_GET(self):  # noqa: N802
        self.send_response(type(self).status)
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, *a):
        pass


class RealChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.httpd = http.server.HTTPServer(("127.0.0.1", 0), _Handler)
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()
        cls.port = cls.httpd.server_address[1]

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()

    def test_http_200_and_503(self):
        _Handler.status = 200
        self.assertTrue(check_http(f"http://127.0.0.1:{self.port}/").ok)
        _Handler.status = 503
        c = check_http(f"http://127.0.0.1:{self.port}/")
        self.assertFalse(c.ok)
        self.assertEqual(c.detail, "HTTP 503")
        _Handler.status = 404  # the server answers: reachable
        self.assertTrue(check_http(f"http://127.0.0.1:{self.port}/").ok)

    def test_tcp_open_and_closed(self):
        self.assertTrue(check_tcp(f"127.0.0.1:{self.port}").ok)
        closed = check_tcp("127.0.0.1:1", timeout=2)
        self.assertFalse(closed.ok)


class RetentionAndBrief(StoreCase):
    def test_prune_keeps_incidents_and_drops_old_samples(self):
        now = time.time()
        old = now - 60 * 86400
        self.store.add_window("anchor", w("1.1.1.1", 15, 15), ts=old)
        self.store.add_window("anchor", w("1.1.1.1", 15, 15), ts=now)
        self.store.open_incident("isp", [], ts=old)
        self.store.prune(now=now)
        self.assertEqual(len(self.store.samples_between(0, 2e10)), 1)
        self.assertEqual(len(self.store.incidents_between(0, 2e10)), 1)

    def test_brief_events_exclude_incidents(self):
        mon = Monitor(self.store, WIN)
        t0 = time.time() - 3600
        seq = ["ok", "isp", "ok", "ok", "isp", "isp", "isp", "ok", "ok"]
        for i, k in enumerate(seq):
            m, rows = internet(40 if k == "isp" else 0)
            mon.step(m, rows, now=t0 + (i + 1) * WIN)
        brief = self.store.brief_events(0, 2e10)
        self.assertEqual(len(brief), 1)  # the single bad window; the 3-window one became an incident
        self.assertEqual(brief[0]["code"], "isp")
        self.assertTrue(brief[0]["evidence"])

    def test_language_follows_cli_until_chosen(self):
        self.assertEqual(load_settings(self.store, default_lang="es").lang, "es")
        self.store.set_settings({"lang": "en"})
        self.assertEqual(load_settings(self.store, default_lang="es").lang, "en")


if __name__ == "__main__":
    unittest.main()
