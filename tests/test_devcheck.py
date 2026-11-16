import tempfile
import time
import unittest
from pathlib import Path

from isitmyisp import devcheck
from isitmyisp.devcheck import cross, parse, series_stats
from isitmyisp.probes.icmp import WindowStats
from isitmyisp.texts import DEVCHECK, devcheck_text
from tests._web import HAVE_WEB

ANCHORS = ["1.1.1.1", "8.8.8.8", "9.9.9.9"]
OK = [(0.0, 30.0, "ok")] * 2
TCP = [{"role": "tcp", "target": f"tcp://{a}:443", "received": 10} for a in ANCHORS]


def dev(**kw):
    d = {"lan": [2.0, 2.4, 1.9, 2.2] * 5, "down_mbps": 400.0, "up_mbps": 300.0,
         "inet": {a: [10.0, 11.0, 12.0, 10.5] for a in ANCHORS}, "seconds": 15.0}
    d.update(kw)
    return d


class Parse(unittest.TestCase):
    def test_keeps_only_what_we_expect(self):
        p = parse({"lan": [1, None, "x", True, -3, 2.5], "down_mbps": "fast", "up_mbps": 50,
                   "inet": {"1.1.1.1": [10, None], "evil.example": [1]}, "seconds": 99999}, ANCHORS)
        self.assertEqual(p["lan"], [1.0, None, None, None, None, 2.5])
        self.assertEqual((p["down_mbps"], p["up_mbps"]), (None, 50.0))
        self.assertEqual(list(p["inet"]), ["1.1.1.1"])
        self.assertEqual(p["seconds"], 15.0)

    def test_needs_lan_measurements(self):
        for raw in ([], {}, {"lan": []}, {"lan": "nope"}):
            with self.assertRaises(ValueError):
                parse(raw, ANCHORS)

    def test_caps_the_samples(self):
        self.assertEqual(len(parse({"lan": [1] * 500}, ANCHORS)["lan"]), devcheck.MAX_SAMPLES)


class Helpers(unittest.TestCase):
    def test_series_stats(self):
        s = series_stats([10.0, None, 20.0, 10.0])
        self.assertEqual((s["sent"], s["loss"], s["ms"], s["jitter"]), (4, 25.0, 10.0, 10.0))
        self.assertEqual(series_stats([])["loss"], None)

    def test_device_label(self):
        android = "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 Chrome/131.0 Mobile Safari/537.36"
        edge = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/131.0 Safari/537.36 Edg/131.0"
        iphone = "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) Version/18.0 Mobile/15E148 Safari/604.1"
        self.assertEqual(devcheck.device_label(android), "Android · Chrome")
        self.assertEqual(devcheck.device_label(edge), "Windows · Edge")
        self.assertEqual(devcheck.device_label(iphone), "iPhone · Safari")
        self.assertEqual(devcheck.device_label(""), "? · ?")

    def test_device_key_hides_the_address(self):
        k = devcheck.device_key("192.168.1.20", "ua")
        self.assertEqual(len(k), 12)
        self.assertNotIn("192", k)
        self.assertNotEqual(k, devcheck.device_key("192.168.1.21", "ua"))


class Cross(unittest.TestCase):
    def test_all_fine(self):
        r = cross(dev(), OK, TCP)
        self.assertEqual((r["code"], r["why"]), ("fine", []))
        self.assertEqual(r["anchors"], ANCHORS)

    def test_bad_wifi_with_a_healthy_probe(self):
        r = cross(dev(lan=[200.0, None, 150.0, None, 300.0] * 4, down_mbps=2.0), OK, TCP)
        self.assertEqual(r["code"], "device_link")
        self.assertEqual(set(r["why"]), {"lan_loss", "lan_ms", "lan_jitter", "down_mbps"})

    def test_internet_bad_only_from_the_device(self):
        r = cross(dev(inet={a: [None, None, 10.0] for a in ANCHORS}), OK, TCP)
        self.assertEqual(r["code"], "device_path")

    def test_probe_saw_it_too(self):
        r = cross(dev(lan=[300.0] * 20), [(0.0, 30.0, "ok"), (30.0, 30.0, "isp"), (60.0, 30.0, "isp")], TCP)
        self.assertEqual(r["code"], "shared")
        self.assertEqual((r["probe"]["bad"], r["probe"]["bad_windows"], r["probe"]["windows"]), ("isp", 2, 3))

    def test_no_probe_windows(self):
        self.assertEqual(cross(dev(), [], [])["code"], "no_probe")
        self.assertEqual(cross(dev(), [(0.0, 30.0, "no_data")], [])["code"], "no_probe")

    def test_unfair_anchors_are_left_out(self):
        # 9.9.9.9 never answers HTTPS from the browser while the others do: not loss
        inet = {"1.1.1.1": [10.0] * 4, "8.8.8.8": [11.0] * 4, "9.9.9.9": [None] * 4}
        r = cross(dev(inet=inet), OK, TCP)
        self.assertEqual((r["code"], r["anchors"]), ("fine", ["1.1.1.1", "8.8.8.8"]))
        # the probe itself didn't reach 8.8.8.8 over TCP: not fair to judge the browser by it
        tcp = [s for s in TCP if "8.8.8.8" not in s["target"]] + [
            {"role": "tcp", "target": "tcp://8.8.8.8:443", "received": 0}]
        r = cross(dev(inet={"1.1.1.1": [10.0] * 4, "8.8.8.8": [None] * 4}), OK, tcp)
        self.assertEqual(r["anchors"], ["1.1.1.1"])

    def test_every_code_has_text(self):
        for lang in ("en", "es"):
            self.assertEqual(set(DEVCHECK[lang]), {"fine", "device_link", "device_path", "shared", "no_probe"})
            for code in DEVCHECK[lang]:
                text, _ = devcheck_text({"code": code, "probe": {"bad": "isp"}}, lang)
                self.assertNotIn("{", text, code)


class Stored(unittest.TestCase):
    def setUp(self):
        from isitmyisp.store import Store
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name) / "d.db")
        self.now = time.time()
        for i in range(3):
            ts = self.now - 60 + i * 30
            self.store.add_window_verdict("ok", 30.0, ts=ts)
            for a in ANCHORS:
                self.store.add_window("tcp", WindowStats(f"tcp://{a}:443", 10, 10, 9, 10, 11, 0.5, 10), ts=ts)
        self.store.db.commit()

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def test_run_and_round_trip(self):
        rec = devcheck.run(self.store, dev(), self.now, "Windows · Edge", "k1", "admin")
        self.assertEqual((rec["code"], rec["probe"]["windows"], rec["user"]), ("fine", 2, "admin"))   # the one 60 s ago is before the check
        i = self.store.add_device_check(rec)
        self.assertEqual(self.store.device_check(i)["device"], "Windows · Edge")
        self.assertIsNone(self.store.device_check(i + 99))
        got = self.store.device_checks_between(self.now - 10, self.now + 10)
        self.assertEqual([c["id"] for c in got], [i])

    def test_report_section(self):
        from isitmyisp.report import R, device_section
        self.assertEqual(device_section([], R["en"], "en"), "")
        a = devcheck.run(self.store, dev(), self.now, "Windows · Edge", "k1")
        b = devcheck.run(self.store, dev(lan=[300.0] * 20), self.now, "Android · Chrome", "k2")
        html = device_section([b, a], R["es"], "es")
        self.assertIn("Probado desde 2 equipos", html)
        self.assertIn("Android · Chrome", html)
        self.assertIn(devcheck_text(b, "es")[0][:20], html)

    def app(self):
        from isitmyisp.webapp import create_app
        app = create_app(self.store, data_dir=Path(self.tmp.name))
        app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
        self.store.set_settings({"auth_mode": "none"})
        return app.test_client()

    @unittest.skipUnless(HAVE_WEB, "web extra not installed")
    def test_web_page_and_csp(self):
        c = self.app()
        r = c.get("/check?lang=es")
        page = r.get_data(as_text=True)
        self.assertIn("Chequear desde este equipo", page)
        self.assertIn("check.js", page)
        self.assertIn('data-anchors="1.1.1.1 8.8.8.8 9.9.9.9"', page)
        csp = r.headers["Content-Security-Policy"]
        self.assertIn("script-src 'self'", csp)
        self.assertIn("connect-src 'self' https:", csp)
        self.assertNotIn("connect-src", c.get("/").headers["Content-Security-Policy"])

    @unittest.skipUnless(HAVE_WEB, "web extra not installed")
    def test_transfer_endpoints(self):
        c = self.app()
        self.assertEqual(c.get("/check/ping").status_code, 204)
        self.assertEqual(len(c.get("/check/down?bytes=5000").data), 5000)
        self.assertEqual(len(c.get("/check/down?bytes=1").data), 1024)          # clamped
        r = c.post("/check/up", data=b"x" * 200_000, content_type="application/octet-stream")
        self.assertEqual(r.get_json(), {"bytes": 200_000})
        # the biggest upload check.js sends, as waitress hands it over (wsgi.input_terminated)
        from isitmyisp.webapp import DEVICE_MAX_BYTES
        r = c.post("/check/up", data=b"\0" * DEVICE_MAX_BYTES, content_type="application/octet-stream",
                   environ_overrides={"wsgi.input_terminated": True})
        self.assertEqual(r.get_json(), {"bytes": DEVICE_MAX_BYTES})

    @unittest.skipUnless(HAVE_WEB, "web extra not installed")
    def test_upload_with_csrf_on(self):
        # CSRF reads the form before the view: the bigger limit must already hold by then
        import re
        c = self.app()
        c.application.config["WTF_CSRF_ENABLED"] = True
        token = re.search(r'data-csrf="([^"]+)"', c.get("/check").get_data(as_text=True)).group(1)
        r = c.post("/check/up", data=b"x" * (2 << 20), content_type="application/octet-stream",
                   headers={"X-CSRFToken": token})
        self.assertEqual(r.get_json(), {"bytes": 2 << 20})
        self.assertEqual(c.post("/check/up", data=b"x", content_type="application/octet-stream").status_code, 400)
        r = c.post("/check/result", data=b"{" + b" " * 70_000 + b"}", content_type="application/json",
                   headers={"X-CSRFToken": token})
        self.assertEqual(r.status_code, 413)          # the 64 KB limit still holds everywhere else

    @unittest.skipUnless(HAVE_WEB, "web extra not installed")
    def test_post_result_then_show_it(self):
        c = self.app()
        self.assertEqual(c.post("/check/result", json={"lan": []}).status_code, 400)
        r = c.post("/check/result", json=dev(), headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) Firefox/133.0"})
        body = r.get_json()
        rec = self.store.device_check(body["id"])
        self.assertEqual((rec["code"], rec["device"]), ("fine", "Linux · Firefox"))
        page = c.get(body["url"] + "&lang=en" if "?" in body["url"] else body["url"] + "?lang=en").get_data(as_text=True)
        self.assertIn("Linux · Firefox", page)
        self.assertIn(devcheck_text(rec, "en")[0], page)


if __name__ == "__main__":
    unittest.main()
