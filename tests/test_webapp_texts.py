"""Texts and data that read right (QA group 2): causes in words, dates one way, no zero counts,
repeats folded, deltas in points with a real minus, a grade about the whole network."""

import http.client
import time
import unittest

from isitmyisp import doctor
from isitmyisp import settings as settings_mod
from isitmyisp.report import localize_evidence
from isitmyisp.services import _reason
from tests._web import HAVE_WEB
from tests.test_webapp import WebAppBase


class ReasonTest(unittest.TestCase):
    def test_exceptions_become_words(self):
        self.assertEqual(_reason(ConnectionResetError(104, "Connection reset by peer")), "connection dropped")
        self.assertEqual(_reason(http.client.RemoteDisconnected("Remote end closed connection")), "connection dropped")
        self.assertEqual(_reason(OSError("something odd")), "network error")

    def test_old_rows_with_exception_names_read_in_words(self):
        line = "https://outlook.live.com: RemoteDisconnected (3/3 checks failed)"
        self.assertEqual(localize_evidence(line, "es"), "https://outlook.live.com: se cortó la conexión (3/3 chequeos fallidos)")
        self.assertEqual(localize_evidence("https://x.com: OSError", "en"), "https://x.com: network error")


class GradeTest(unittest.TestCase):
    def test_probe_only_checks_dont_lower_the_grade(self):
        checks = [doctor.Check("speed", "probe", "bad", "wifi_no"), doctor.Check("dns", "network", "ok", "wifi_no")]
        self.assertEqual(doctor.grade(checks), "A")
        self.assertEqual(doctor.grade(checks + [doctor.Check("mtu", "network", "warn", "wifi_no")]), "B")


@unittest.skipUnless(HAVE_WEB, "web extra not installed")
class FiltersTest(WebAppBase):
    def render(self, src, lang="es", **ctx):
        from flask import g

        from isitmyisp.webapp.strings import S
        with self.app.test_request_context("/"):
            g.t, g.lang = S[lang], lang
            return self.app.jinja_env.from_string(src).render(**ctx)

    def test_today_says_the_time_another_day_says_the_day(self):
        now = time.time()
        today = time.mktime(time.localtime(now)[:3] + (0, 1, 0, 0, 0, -1))   # 00:01 today
        self.assertEqual(self.render("{{ ts|since }}", ts=today), "desde las 00:01")
        self.assertEqual(self.render("{{ ts|at }}", ts=today), "a las 00:01")
        other = self.render("{{ ts|since }}", ts=today - 2 * 86400)
        self.assertRegex(other, r"^desde el \w+ \d+ \w+, 00:01$")
        self.assertNotRegex(other, r"\d{4}-\d\d-\d\d")

    def test_delta_has_a_real_minus(self):
        html = self.render("{{ m|minus }}", m='<p><svg></svg>-21.0 pp</p>')
        self.assertIn("</svg>−21.0 pp", html)


@unittest.skipUnless(HAVE_WEB, "web extra not installed")
class PagesTest(WebAppBase):
    def setUp(self):
        super().setUp()
        self.create_admin()
        self.login()

    def test_repeated_service_failures_fold_into_one_row(self):
        from isitmyisp.webapp import views
        now = time.time()
        for k in range(5):
            i = self.store.open_incident("service_down", ["https://outlook.live.com: timeout"],
                                         ts=now - 3600 + k * 600, scope="service:Outlook")
            self.store.close_incident(i, ts=now - 3600 + k * 600 + 120)
        self.store.close_incident(self.store.open_incident("local", ["x"], ts=now - 7200), ts=now - 7000)
        rows = views.incident_rows(self.store, {"scope_internet": "Internet"}, now=now)
        self.assertEqual([r.count for r in rows], [5, 1])
        self.assertEqual(rows[0].first, now - 3600)
        self.assertEqual(rows[0].duration, "10 min")
        html = self.client.get("/incidents").get_data(as_text=True)
        self.assertIn("×5", html)

    def test_doctor_hides_zero_counts(self):
        from isitmyisp import demo
        demo.add_doctor_run(self.store)
        html = self.client.get("/doctor?lang=es").get_data(as_text=True)
        self.assertNotRegex(html, r"\b0 (bien|para mirar|mal|sin medir)")

    def test_ongoing_event_has_no_duration(self):
        self.store.open_incident("service_down", ["x"], ts=time.time() - 1320, scope="service:Outlook")
        html = self.client.get("/?lang=es").get_data(as_text=True)
        self.assertRegex(html, r"en curso</b> · hace 22 min</p>")

    def test_measuring_since_counts_elapsed_time(self):
        from isitmyisp.webapp import views
        first = self.store.first_and_last_window()[0]
        m = views.month_view(self.store, first + 30 * 3600)    # since yesterday evening: not "2 days"
        self.assertEqual((m["n"], m["dur"]), (1, "1 d 6 h"))

    def test_a_bad_route_change_long_over_folds(self):
        from isitmyisp import routes
        from isitmyisp.webapp import views
        now = time.time()
        card = {"quiet": False, "state": "back", "until": now - 13 * 3600, "since": now - 14 * 3600,
                "case": "worse", "series": {}, "window": (now - 15 * 3600, now - 12 * 3600), "mark": now - 14 * 3600}
        orig = routes.cards
        routes.cards = lambda *a, **k: [card]
        try:
            rc = views.route_cards(self.store, settings_mod.load(self.store), now=now)
        finally:
            routes.cards = orig
        self.assertEqual(rc["loud"], [])
        self.assertEqual(rc["quiet"][0]["back_ago"], "13 h")


if __name__ == "__main__":
    unittest.main()
