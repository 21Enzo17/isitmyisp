"""Small things (QA group 4): language links keep the page's args, read-only isn't "Admin", styled
404/405, an availability sparkline that isn't always green, no empty min=, an mtr that fits a phone."""

import unittest
from pathlib import Path

from isitmyisp import settings as settings_mod
from tests._web import HAVE_WEB
from tests.test_webapp import WebAppBase


@unittest.skipUnless(HAVE_WEB, "web extra not installed")
class MinorTest(WebAppBase):
    def setUp(self):
        super().setUp()
        self.create_admin()
        self.login()

    def page(self, url):
        return self.client.get(url).get_data(as_text=True)

    def test_lang_links_keep_the_other_args(self):
        html = self.page("/chart?span=6h&lang=en")
        self.assertIn('href="?span=6h&amp;lang=es"', html)
        self.assertNotIn("lang=en&amp;lang", html)

    def test_not_found_and_wrong_method_are_styled(self):
        r = self.client.get("/nope?lang=es")
        self.assertEqual(r.status_code, 404)
        self.assertIn("Volver al panel", r.get_data(as_text=True))
        r = self.client.get("/logout")
        self.assertEqual(r.status_code, 405)
        self.assertIn("style.css", r.get_data(as_text=True))
        self.assertNotIn("style.css", self.client.get("/api/nope").get_data(as_text=True))

    def test_dashboard_has_no_empty_min(self):
        self.assertNotIn('min=""', self.page("/"))

    def test_sparkline_tone_follows_availability(self):
        from isitmyisp.webapp import views
        self.assertEqual([views.avail_tone(p) for p in (100, 99.5, 99, 97, None)], ["good", "good", "warn", "bad", "good"])
        tpl = (Path(views.__file__).parent / "templates" / "dashboard.html").read_text()
        self.assertIn("kpi-spark s-{{ k.avail.tone }}", tpl)


@unittest.skipUnless(HAVE_WEB, "web extra not installed")
class ReadOnlyLabelTest(WebAppBase):
    bind = "127.0.0.1:8080"

    def test_auth_off_reads_as_viewer(self):
        s = settings_mod.load(self.store)
        settings_mod.save(self.store, {**s.__dict__, "auth_mode": "none"})
        html = self.client.get("/?lang=es").get_data(as_text=True)
        self.assertIn("<small>Lector</small>", html)
        self.assertNotIn("<small>Administrador</small>", html)


class MtrFitsTest(unittest.TestCase):
    def test_mtr_table_scrolls_in_its_box(self):
        from isitmyisp import report
        self.assertIn(".tscroll { overflow-x: auto; }", report.CSS)
        self.assertIn('<div class="tscroll"><table class="mtr">', Path(report.__file__).read_text())


if __name__ == "__main__":
    unittest.main()
