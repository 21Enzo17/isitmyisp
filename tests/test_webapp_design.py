"""Design decisions (QA group 3): what to do right under the verdict, a stale monitor reads as the
last known state, one "Check-up" in the nav, incidents as cards on a phone, red that isn't the ISP."""

import time
import unittest
from pathlib import Path
from unittest import mock

from isitmyisp import settings as settings_mod
from tests._web import HAVE_WEB
from tests.test_webapp import WebAppBase

CSS = Path(__file__).resolve().parent.parent / "isitmyisp" / "webapp" / "static" / "style.css"


@unittest.skipUnless(HAVE_WEB, "web extra not installed")
class DesignTest(WebAppBase):
    def setUp(self):
        super().setUp()
        self.create_admin()
        self.login()

    def page(self, url="/?lang=es"):
        return self.client.get(url).get_data(as_text=True)

    def test_what_to_do_comes_before_the_chart(self):
        html = self.page()
        self.assertLess(html.index('class="card where'), html.index('class="dash-row mid"'))

    def test_stale_monitor_freezes_the_numbers(self):
        from isitmyisp.webapp import views
        later = time.time() + 3600
        with mock.patch.object(views.time, "time", return_value=later):
            html = self.page()
        self.assertIn("Sin datos nuevos", html)
        self.assertNotIn("Midiendo…", html)
        self.assertIn('class="card kpi frozen"', html)
        self.assertIn('class="stale-note"', html)
        d = views.dashboard_data(self.store, settings_mod.load(self.store), now=later)
        # the uptime stops at the last window instead of growing for the hour nothing was measured
        self.assertEqual(d.kpi["uptime"]["value"], "1 min")

    def test_live_monitor_is_not_frozen(self):
        html = self.page()
        self.assertNotIn("frozen", html)
        self.assertNotIn("Sin datos nuevos", html)

    def test_one_check_up_in_the_nav_both_urls_work(self):
        for url, current in (("/doctor?lang=es", "Toda la red"), ("/check?lang=es", "Desde este equipo")):
            html = self.page(url)
            nav = html[html.index('class="nav"'):html.index("</nav>")]
            self.assertEqual(nav.count("<a "), 6)
            self.assertNotIn("Este equipo", nav)
            self.assertIn('class="active" aria-current="page"', nav)
            self.assertIn(f'aria-current="page">{current}</a>', html)

    def test_incident_cells_carry_their_labels(self):
        i = self.store.open_incident("isp", ["x"], ts=time.time() - 600)
        self.store.close_incident(i, ts=time.time() - 300)
        html = self.page("/incidents?lang=es")
        self.assertIn('class="inc-table"', html)
        self.assertIn('data-label="Duración"', html)


class TokensTest(unittest.TestCase):
    def test_generic_red_is_not_the_isp_color(self):
        css = CSS.read_text()
        self.assertIn("--bad:", css)
        self.assertIn(".btn.danger", css)
        rule = css[css.index(".btn.danger"):].split("}")[0]
        self.assertNotIn("--isp", rule)


if __name__ == "__main__":
    unittest.main()
