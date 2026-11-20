"""QA group 1: inputs that broke a page, errors in the wrong language, forms that forgot what you typed."""

import unittest

from isitmyisp import settings as settings_mod
from tests._web import HAVE_WEB
from tests.test_webapp import WebAppBase, csrf


@unittest.skipUnless(HAVE_WEB, "needs the [web] extra")
class QABase(WebAppBase):
    def setUp(self):
        super().setUp()
        self.create_admin()

    def page(self, url="/settings"):
        return self.client.get(url).get_data(as_text=True)

    def post(self, url, page="/settings", **data):
        return self.client.post(url, data={"csrf_token": csrf(self.page(page)), **data})


class NonFiniteSpeeds(QABase):
    def test_inf_and_nan_plan_is_rejected(self):
        for bad in ("inf", "nan", "1e400", "-inf"):
            with self.subTest(bad=bad):
                r = self.post("/settings/plan", page="/settings/connection", down_mbps=bad, up_mbps="10")
                self.assertEqual(r.status_code, 400)
        self.assertEqual(settings_mod.load(self.store).link["down_mbps"], 0)

    def test_a_stored_inf_no_longer_breaks_the_pages(self):
        self.store.set_settings({"link": {**settings_mod.DEFAULTS["link"], "down_mbps": float("inf"),
                                         "up_mbps": float("nan")}})
        for url in ("/", "/settings/connection", "/settings"):
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)


class ErrorsInSpanishAndKeptValues(QABase):
    def setUp(self):
        super().setUp()
        self.store.set_settings({"lang": "es"})

    def test_spanish_error_and_typed_values_stay(self):
        r = self.post("/settings/general", anchors="1.1.1.1\n192.168.1.1", interval="3", window="45", lang="es",
                      dns="9.9.9.9")
        self.assertEqual(r.status_code, 400)
        html = r.get_data(as_text=True)
        self.assertIn("tiene que ser una dirección pública de internet", html)
        self.assertNotIn("must be a public address", html)
        self.assertIn("1.1.1.1\n192.168.1.1</textarea>", html)
        self.assertIn('value="45"', html)
        self.assertIn('value="9.9.9.9"', html)

    def test_only_the_sent_form_is_refilled(self):
        r = self.post("/settings/services/add", name="ERP", kind="tcp", target="nada")
        self.assertEqual(r.status_code, 400)
        html = r.get_data(as_text=True)
        self.assertIn("el destino TCP tiene que ser servidor:puerto", html)
        self.assertIn('value="nada"', html)
        self.assertIn('<option value="tcp" selected>', html)
        # the device form has its own "name" field: it isn't touched
        start = html.index('action="/settings/devices/add"')
        self.assertNotIn('value="ERP"', html[start:html.index("</form>", start)])

    def test_english_ui_stays_english(self):
        self.store.set_settings({"lang": "en"})
        r = self.post("/settings/general", anchors="192.168.1.1", interval="2", window="30", lang="en")
        self.assertIn("must be a public address", r.get_data(as_text=True))

    def test_the_csrf_token_is_not_overwritten(self):
        r = self.post("/settings/general", anchors="192.168.1.1", interval="2", window="30", lang="es")
        self.assertEqual(r.status_code, 400)
        self.assertTrue(csrf(r.get_data(as_text=True)))


class OddQueryParams(QABase):
    def test_chart_with_non_finite_range(self):
        for q in ("from=nan&to=inf", "from=-inf&to=1e400", "from=1e30&to=2", "k=99999999999999"):
            with self.subTest(q=q):
                r = self.client.get(f"/chart?{q}")
                self.assertEqual(r.status_code, 200)
                self.assertNotIn("-273", r.get_data(as_text=True))

    def test_check_with_a_huge_id(self):
        for q in ("id=99999999999999999999", "id=-5", "id=abc"):
            with self.subTest(q=q):
                self.assertEqual(self.client.get(f"/check?{q}").status_code, 200)


class ReportPeriod(QABase):
    def setUp(self):
        super().setUp()
        self.store.set_settings({"lang": "es"})

    def test_a_bad_date_goes_back_to_reports_with_the_input(self):
        for bad in ("01/11/2026", "ayer", "25:00"):
            with self.subTest(bad=bad):
                r = self.client.get("/report", query_string={"since": bad, "until": "2026-11-07"})
                self.assertEqual(r.status_code, 400)
                html = r.get_data(as_text=True)
                self.assertIn(f"«{bad}» no es una fecha", html)
                self.assertIn(f'value="{bad}"', html)
                self.assertIn('value="2026-11-07"', html)

    def test_upper_case_units_work(self):
        self.assertEqual(self.client.get("/report?since=7D").status_code, 200)

    def test_reversed_dates_are_the_same_period(self):
        import time
        day = lambda ts: time.strftime("%Y-%m-%d", time.localtime(ts))
        now = time.time()
        r = self.client.get("/report", query_string={"since": day(now), "until": day(now - 3 * 86400)})
        self.assertEqual(r.status_code, 200)
        self.assertNotIn("No hay mediciones", r.get_data(as_text=True))

    def test_the_future_is_refused(self):
        r = self.client.get("/report", query_string={"since": "2099-01-01"})
        self.assertEqual(r.status_code, 400)
        self.assertIn("todavía no pasó", r.get_data(as_text=True))

    def test_an_empty_period_says_when_there_is_data(self):
        html = self.client.get("/report", query_string={"since": "2020-01-01", "until": "2020-01-02"}).get_data(as_text=True)
        self.assertIn("Hay mediciones del", html)
        self.assertNotIn("Corré", html)

    def test_without_weasyprint_no_pdf_button_and_a_translated_message(self):
        self.app.config["PDF_OK"] = False
        html = self.page("/reports")
        self.assertNotIn("/report.pdf", html)
        self.assertIn("imprimilo como PDF desde el navegador", html)
        self.assertNotIn("/report.pdf", self.client.get("/report?since=24h").get_data(as_text=True))
        from unittest import mock

        from isitmyisp import pdf
        with mock.patch.object(pdf, "html_to_pdf", side_effect=pdf.PdfUnavailable("x")):
            r = self.client.get("/report.pdf?since=24h")
        self.assertEqual(r.status_code, 501)
        self.assertIn("text/html", r.content_type)
        self.assertIn("imprimilo como PDF", r.get_data(as_text=True))



class PartialIncidentsAreNotCuts(QABase):
    """Only some destinations failing: your internet worked, so it isn't a cut anywhere you're told about cuts."""
    def setUp(self):
        super().setUp()
        import time
        now = time.time()
        self.store.add_window_verdict("remote", 600, ts=now - 1200, evidence=["9.9.9.9: 100% loss"])
        i = self.store.open_incident("remote", ["9.9.9.9: 100% loss"], ts=now - 1800)
        self.store.close_incident(i, ts=now - 1200)

    def test_the_report_counts_no_cuts(self):
        import time

        from isitmyisp.report import build_report
        html = build_report(self.store, time.time() - 7 * 86400, time.time(), lang="es")
        self.assertIn("Sin incidentes en este período", html)
        self.assertNotIn("Los cortes que más te afectaron", html)
        self.assertIn("Solo fallaron algunos destinos 1 vez", html)

    def test_the_dashboard_counts_time_without_cuts_from_the_start(self):
        import time

        from isitmyisp.webapp import views
        d = views.dashboard_data(self.store, settings_mod.load(self.store), now=time.time())
        self.assertFalse(d.kpi["uptime"]["ongoing"])
        self.assertEqual(d.kpi["uptime"]["since"], self.store.first_and_last_window()[0])


class TvWithoutSignIn(QABase):
    def test_the_board_shows_with_nothing_to_pair(self):
        settings_mod.save(self.store, {"auth_mode": "none"})
        r = self.client.get("/tv")
        self.assertEqual(r.status_code, 200)
        self.assertNotIn("tv-pair-code", r.get_data(as_text=True))


if __name__ == "__main__":
    unittest.main()
