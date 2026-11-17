"""#68: iperf3 servers besides Cloudflare, marked inside or outside the ISP, and where the bottleneck is."""
import json
import socket
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

from isitmyisp import speedtest as sp
from isitmyisp.store import Store
from isitmyisp.texts import SPEEDWHERE, speed_where_text
from tests.test_speedtest import ON, FakeHTTP, no_ping
from tests.test_webapp import WebAppBase, csrf


def resolver(ip):
    return lambda host, port, type=None: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 0))]


def lookup(table):
    return lambda ips, data_dir=None, online=False: {ip: table[ip] for ip in ips if ip in table}


class Servers(unittest.TestCase):
    def test_parse(self):
        got = sp.parse_servers("iperf.example.net\n10.8.0.1:5202 outside  # the branch\n\n[2001:db8::1]:5201 INSIDE")
        self.assertEqual(got, [{"host": "iperf.example.net", "port": 5201, "where": "auto"},
                               {"host": "10.8.0.1", "port": 5202, "where": "outside"},
                               {"host": "2001:db8::1", "port": 5201, "where": "inside"}])
        self.assertEqual([sp.label(s) for s in got], ["iperf.example.net", "10.8.0.1:5202", "[2001:db8::1]"])
        self.assertEqual(sp.parse_servers(got), got)        # stored values round-trip

    def test_parse_rejects(self):
        for bad in ("a b c", "host sideways", "-oProxy=x", "host:99999", "bad_host!", "a\nb\nc\nd"):
            with self.assertRaises(ValueError, msg=bad):
                sp.parse_servers(bad)

    def test_validate_keeps_or_sets_servers(self):
        cur = {**ON, "servers": [{"host": "a.example", "port": 5201, "where": "auto"}]}
        form = {"enabled": True, "accepted": True}
        self.assertEqual(sp.validate(form, cur)["servers"], cur["servers"])
        self.assertEqual(sp.validate({**form, "servers": ""}, cur)["servers"], [])


class Mark(unittest.TestCase):
    def test_by_asn(self):
        table = {"200.45.0.9": ("AS64500", "Example ISP"), "104.16.0.7": ("AS64510", "Hosting")}
        inside = sp.mark("x", isp_asn="AS64500", resolve=resolver("200.45.0.9"), lookup=lookup(table))
        outside = sp.mark("x", isp_asn="AS64500", resolve=resolver("104.16.0.7"), lookup=lookup(table))
        self.assertEqual((inside["where"], inside["asn"]), ("inside", "AS64500"))
        self.assertEqual((outside["where"], outside["as_name"]), ("outside", "Hosting"))

    def test_cannot_tell(self):
        self.assertEqual(sp.mark("x", isp_asn="AS64500", resolve=resolver("10.8.0.1"), lookup=lookup({}))["where"], "private")
        self.assertEqual(sp.mark("x", isp_asn="AS64500", resolve=resolver("100.64.3.2"), lookup=lookup({}))["where"], "inside")
        # no ASN data, or the ISP's ASN unknown
        self.assertIsNone(sp.mark("x", isp_asn="AS64500", resolve=resolver("1.0.0.200"), lookup=lookup({}))["where"])
        self.assertIsNone(sp.mark("x", isp_asn=None, resolve=resolver("200.45.0.9"),
                                  lookup=lookup({"200.45.0.9": ("AS64500", "")}))["where"])

        def fails(*a, **k):
            raise socket.gaierror("no such host")
        self.assertIsNone(sp.mark("nope.invalid", isp_asn="AS64500", resolve=fails)["where"])


class Iperf(unittest.TestCase):
    def fake(self, payload, seen):
        def runner(cmd, **kw):
            seen.append(cmd)
            return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps(payload), stderr="")
        return runner

    def test_parses_and_caps_the_rate(self):
        seen = []
        out = {"end": {"sum_received": {"bits_per_second": 287e6, "bytes": 300_000_000},
                       "sum_sent": {"bytes": 301_000_000}}}
        mbps, moved = sp._iperf3("h", 5201, 100_000_000, reverse=True, seconds=8, runner=self.fake(out, seen))
        self.assertEqual(mbps, 287.0)
        self.assertEqual(moved, int(301_000_000 * 9 / 8))
        cmd = seen[0]
        self.assertIn("-R", cmd)
        rate = int(cmd[cmd.index("-b") + 1])
        self.assertLessEqual(rate * sp.STREAMS * 9 / 8, 100_000_000)    # can't move more than its share

    def test_error_from_iperf(self):
        with self.assertRaises(sp.SpeedError):
            sp._iperf3("h", 5201, 10**8, reverse=False, seconds=6,
                       runner=self.fake({"error": "unable to connect to server"}, []))

    def test_run_splits_the_cap_and_records_each_server(self):
        calls = []

        def iperf(host, port, cap, *, reverse, seconds):
            calls.append((host, cap, reverse))
            if host == "down.example":
                raise sp.SpeedError("down.example: unable to connect")
            return (280.0 if reverse else 90.0), cap // 2
        servers = [{"host": "isp.example", "port": 5201, "where": "auto"},
                   {"host": "down.example", "port": 5201, "where": "outside"}]
        r = sp.run(9_000_000, opener=FakeHTTP(), ping=no_ping, down_seconds=1, up_seconds=1, servers=servers,
                   mark=lambda h: {"where": "inside", "asn": "AS64500"}, iperf=iperf, isp_asn="AS64500")
        share = 9_000_000 // 3
        self.assertEqual(calls[:2], [("isp.example", int(share * 0.7), True), ("isp.example", int(share * 0.3), False)])
        a, b = r.servers
        self.assertEqual((a["where"], a["down_mbps"], a["up_mbps"], a["forced"]), ("inside", 280.0, 90.0, False))
        self.assertEqual((b["where"], b["forced"]), ("outside", True))       # forced beats the ASN
        self.assertIn("unable", b["error"])
        self.assertEqual(r.where, "outside")
        self.assertLessEqual(r.bytes_used, 9_000_000 + sp.STREAMS * (2_000_000 + sp.UP_CHUNK))

    def test_without_iperf3_installed(self):
        orig = sp.iperf_available
        sp.iperf_available = lambda: False
        try:
            r = sp.run_server({"host": "h", "port": 5201, "where": "auto"}, 10**8)
        finally:
            sp.iperf_available = orig
        self.assertIn("not installed", r["error"])
        self.assertEqual(r["bytes"], 0)


class Locate(unittest.TestCase):
    def res(self, cf, *servers, error=None):
        return {"down_mbps": cf, "where": "outside", "error": error,
                "servers": [{"name": n, "where": w, "down_mbps": d, "error": None} for n, w, d in servers]}

    def test_codes(self):
        exit_ = sp.locate(self.res(40, ("isp", "inside", 300)), 300)
        self.assertEqual((exit_["code"], exit_["inside"], exit_["outside"], exit_["outside_name"]),
                         ("exit", 300, 40, sp.SERVER))
        self.assertEqual(sp.locate(self.res(90, ("isp", "inside", 100)), 300)["code"], "access")
        self.assertEqual(sp.locate(self.res(280, ("isp", "inside", 290)), 300)["code"], "even")
        self.assertEqual(sp.locate(self.res(90, ("isp", "inside", 100)))["code"], "even")      # no plan

    def test_best_of_each_side(self):
        r = self.res(40, ("isp", "inside", 300), ("vps", "outside", 250))
        self.assertEqual(sp.locate(r, 300)["code"], "even")       # Cloudflare alone was slow: not the exit

    def test_needs_both_sides(self):
        self.assertIsNone(sp.locate(self.res(40, ("vps", "outside", 50))))
        self.assertIsNone(sp.locate(self.res(40, ("vpn", "private", 300), ("?", None, 300))))
        self.assertIsNone(sp.locate(self.res(None, ("isp", "inside", 300), error="boom")))

    def test_every_code_has_text(self):
        for lang in ("en", "es"):
            self.assertEqual(set(SPEEDWHERE[lang]), {"exit", "access", "even"})
            for code in SPEEDWHERE[lang]:
                text = speed_where_text({"code": code, "inside": 300, "outside": 40}, lang)
                self.assertNotIn("{", text)
                self.assertIn("300", text)
        self.assertEqual(speed_where_text(None), "")


class Wired(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name) / "s.db")

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def test_runner_passes_servers_and_the_isp(self):
        got = {}

        def fake_run(cap, **kw):
            got.update(kw)
            return sp.Result(ts=time.time(), trigger=kw["trigger"])
        cfg = {**ON, "schedule": "manual", "servers": [{"host": "isp.example", "port": 5201, "where": "auto"}]}
        runner = sp.Runner(self.store, run_fn=fake_run)
        self.store.set_settings({"_speed_request": time.time()}, bump=False)
        self.assertEqual(runner.tick(cfg, time.time(), wireless=False, on_backup=False, incident=False,
                                     link_busy_pct=None, isp_asn="AS64500"), "started")
        runner.thread.join(2)
        self.assertEqual((got["servers"], got["isp_asn"]), (cfg["servers"], "AS64500"))
        self.assertTrue(callable(got["mark"]))

    def test_budget_and_backup_rules_still_hold(self):
        cfg = {**ON, "servers": [{"host": "isp.example", "port": 5201, "where": "auto"}]}
        self.assertEqual(sp.blocked(cfg, manual=True, used_bytes=0, on_backup=True, incident=False,
                                    link_busy_pct=None), "backup")
        self.assertEqual(sp.blocked(cfg, manual=False, used_bytes=0, on_backup=False, incident=True,
                                    link_busy_pct=None), "incident")
        self.assertEqual(sp.blocked(cfg, manual=True, used_bytes=int(5e9), on_backup=False, incident=False,
                                    link_busy_pct=None), "budget")

class Web(WebAppBase):
    def test_settings_form_dashboard_and_report(self):
        from isitmyisp import demo
        from isitmyisp.report import R, build_report, speed_where_section
        self.create_admin()
        page = self.client.get("/settings").get_data(as_text=True)
        form = {"csrf_token": csrf(page), "enabled": "1", "accepted": "1", "schedule": "manual", "weekday": "6",
                "hour": "3", "budget_gb": "5", "max_busy_pct": "30",
                "servers": "speedtest.example-isp.net\nvps.example.org:5202 outside"}
        self.assertEqual(self.client.post("/settings/speedtest", data=form).status_code, 302)
        saved = self.store.get_setting("speedtest")["servers"]
        self.assertEqual([s["where"] for s in saved], ["auto", "outside"])
        page = self.client.get("/settings/connection?lang=en").get_data(as_text=True)
        self.assertIn("vps.example.org:5202 outside", page)
        self.assertIn("about 45 seconds", page)            # Cloudflare plus two servers, one after the other
        r = self.client.post("/settings/speedtest", data={**form, "servers": "evil; rm -rf /"})
        self.assertEqual(r.status_code, 400)

        demo.add_speed_result(self.store)
        self.store.set_settings({"link": {"down_mbps": 300, "up_mbps": 100}})
        page = self.client.get("/?lang=es").get_data(as_text=True)
        self.assertIn("speedtest.example-isp.net", page)
        self.assertIn("dentro de tu ISP", page)
        self.assertIn("Hasta el ISP 287 Mbps, al resto de internet 58", page)

        tests = self.store.speedtests_between(0, 2e10)
        self.assertEqual(speed_where_section(tests[:1], R["en"], "en"), "")      # Cloudflare only: no section
        html = speed_where_section(tests, R["en"], "en", 300)
        self.assertNotIn("In 1 of 1", html)                  # one located test: no count
        last = tests[-1]
        fresh = sp.Result(**{**last, "ts": time.time() - 40})
        self.store.add_speedtest(fresh)
        html = build_report(self.store, time.time() - 7 * 86400, time.time(), lang="en")
        self.assertIn("Inside and outside the ISP", html)
        self.assertIn("the bottleneck is the ISP&#x27;s exit", html)
        self.assertIn("AS64510", html)

if __name__ == "__main__":
    unittest.main()
