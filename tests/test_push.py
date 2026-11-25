"""#115: another machine sends its speed test results (POST /api/speedtest) with a token of their own."""
import json
import time
import unittest

from isitmyisp import settings as settings_mod
from isitmyisp import speedtest as sp
from tests.test_extcmd import LIBRESPEED, OOKLA
from tests.test_webapp import HAVE_WEB, WebAppBase, csrf

BODY = json.dumps(OOKLA)


@unittest.skipUnless(HAVE_WEB, "web extra not installed")
class Push(WebAppBase):
    def push(self, body=BODY, token=None, query=""):
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        return self.client.post(f"/api/speedtest{query}", data=body, headers=headers,
                                content_type="application/json")

    def make_token(self, action="new"):
        page = self.client.get("/settings/connection?lang=en").get_data(as_text=True)
        r = self.client.post("/settings/speed-push", data={"csrf_token": csrf(page), "action": action})
        self.assertEqual(r.status_code, 302)
        return settings_mod.push_token(self.store)

    def test_off_until_an_admin_makes_a_token(self):
        self.create_admin()
        self.assertEqual(self.push().status_code, 401)
        self.assertEqual(self.push(token="guess").status_code, 401)   # no token yet: nothing matches
        page = self.client.get("/settings/connection?lang=en").get_data(as_text=True)
        self.assertIn("Results from another machine", page)
        self.assertIn("Make a token", page)
        self.assertIsNone(settings_mod.push_token(self.store))

    def test_a_pushed_ookla_result_is_shown_and_uses_no_budget(self):
        self.create_admin()
        token = self.make_token()
        self.assertTrue(token)
        page = self.client.get("/settings/connection?lang=en").get_data(as_text=True)
        self.assertIn(token, page)
        self.assertIn('/api/speedtest?name=PC"', page)
        self.store.set_settings({"link": {"down_mbps": 1000, "up_mbps": 600}})

        r = self.push(token=token, query="?name=PC")
        self.assertEqual(r.status_code, 201, r.get_data(as_text=True))
        got = r.get_json()
        self.assertEqual((got["format"], got["down_mbps"], got["up_mbps"], got["ping_ms"]), ("ookla", 939.0, 755.0, 1.5))
        self.assertEqual(got["name"], "PC · Personal (Buenos Aires, Argentina)")

        [res] = self.store.speedtests_between(time.time() - 60, time.time() + 1)
        self.assertEqual((res["trigger"], res["bytes_used"], res["down_mbps"]), ("push", 0, None))
        self.assertEqual(res["servers"][0]["engine"], "push")
        self.assertEqual(self.store.speed_bytes_since(0), 0)

        # shown although this machine's own speed test is off
        page = self.client.get("/?lang=en").get_data(as_text=True)
        self.assertIn("<b>939</b> Mbps", page)
        self.assertIn("94% of 1000 Mbps", page)
        self.assertIn("by another machine", page)
        self.assertNotIn("<td>speed.cloudflare.com</td>", page)   # Cloudflare didn't run

    def test_any_format_the_own_engine_reads(self):
        self.create_admin()
        token = self.make_token()
        r = self.push(json.dumps(LIBRESPEED), token=token, query="?format=librespeed&wireless=1")
        self.assertEqual(r.status_code, 201, r.get_data(as_text=True))
        [res] = self.store.speedtests_between(0, time.time() + 1)
        self.assertTrue(res["wireless"])
        r = self.push("Download: 939 Mbps", token=token)
        self.assertEqual(r.status_code, 400)
        self.assertIn("not JSON", r.get_json()["error"])
        self.assertEqual(self.push(token=token, query="?format=bash").status_code, 400)

    def test_a_session_is_not_enough_and_csrf_is_not_needed(self):
        self.create_admin()                       # logged in, but the API wants the token
        self.assertEqual(self.push().status_code, 401)
        token = self.make_token()
        self.assertEqual(self.push(token=token).status_code, 201)   # no CSRF token in the request

    def test_new_token_and_off(self):
        self.create_admin()
        old = self.make_token()
        new = self.make_token()
        self.assertNotEqual(old, new)
        self.assertEqual(self.push(token=old).status_code, 401)
        self.assertEqual(self.push(token=new).status_code, 201)
        self.assertIsNone(self.make_token("off"))
        self.assertEqual(self.push(token=new).status_code, 401)

    def test_rate_limited(self):
        self.create_admin()
        token = self.make_token()
        codes = [self.push(token=token).status_code for _ in range(7)]
        self.assertEqual(codes[:6], [201] * 6)
        self.assertEqual(codes[6], 429)


@unittest.skipUnless(HAVE_WEB, "web extra not installed")
class Demo(unittest.TestCase):
    def test_demo_refuses_it(self):
        import tempfile
        from pathlib import Path

        from isitmyisp.store import Store
        from isitmyisp.webapp import create_app
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(Path(tmp) / "d.db")
            try:
                token = settings_mod.push_token(store, "new")
                client = create_app(store, data_dir=Path(tmp), demo=True).test_client()
                r = client.post("/api/speedtest", data=BODY, headers={"Authorization": f"Bearer {token}"})
                self.assertEqual(r.status_code, 403)
            finally:
                store.close()


class Report(unittest.TestCase):
    def test_no_cloudflare_row_for_a_pushed_test(self):
        from isitmyisp.report import R, speed_where_section
        server = {"name": "PC · Personal", "engine": "push", "where": "inside", "asn": "AS7303",
                  "down_mbps": 939.0, "up_mbps": 755.0, "error": None}
        res = sp.Result(ts=time.time(), trigger="push", where=None, servers=[server]).__dict__
        html = speed_where_section([res], R["en"], "en")
        self.assertIn("PC · Personal", html)
        self.assertNotIn(sp.SERVER, html)


if __name__ == "__main__":
    unittest.main()
