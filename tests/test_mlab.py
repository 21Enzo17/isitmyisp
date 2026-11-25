"""#115: M-Lab NDT7 as a second engine, with its own consent, and the plan held against the best figure."""
import io
import json
import tempfile
import threading
import time
import unittest
from pathlib import Path

from isitmyisp import mlab
from isitmyisp import speedtest as sp
from isitmyisp.store import Store
from tests.test_speedtest import ON, FakeHTTP, no_ping
from tests.test_webapp import WebAppBase, csrf


def locate_reply(*machines):
    results = [{"machine": m, "location": {"city": "Buenos Aires", "country": "AR"},
                "urls": {mlab.DOWN_KEY: f"wss://ndt-{m}.example/ndt/v7/download?access_token=t",
                         mlab.UP_KEY: f"wss://ndt-{m}.example/ndt/v7/upload?access_token=t"}} for m in machines]
    return json.dumps({"results": results}).encode()


class Locator:
    """Answers the locate API: each call a list of machines, in the order given."""

    def __init__(self, *replies, fail=False):
        self.replies, self.fail, self.calls = list(replies), fail, 0

    def __call__(self, req, timeout=None):
        self.calls += 1
        if self.fail:
            raise OSError("no route to host")
        return io.BytesIO(locate_reply(*self.replies[min(self.calls, len(self.replies)) - 1]))


class FakeSock:
    """A download socket that sends zeros, an upload one that swallows what it gets."""

    def __init__(self, log):
        self.log, self.sent, self.closed = log, 0, False

    def recv(self, n):
        if self.closed:
            return b""
        time.sleep(0.001)
        return b"\0" * min(n, 200_000)

    def sendall(self, data):
        self.sent += len(data)
        self.log["sent"] = self.log.get("sent", 0) + len(data)

    def close(self):
        self.closed = True


def fake_connect(log, refuse=False):
    def connect(url, timeout=10.0):
        log.setdefault("urls", []).append(url)
        if refuse:
            raise OSError("refused: HTTP/1.1 429 Too Many Requests")
        return FakeSock(log), 28.4, b"\0" * 10
    return connect


class Protocol(unittest.TestCase):
    def test_locate_keeps_machines_with_both_urls(self):
        got = mlab.locate(Locator(["mlab1-eze01"]))
        self.assertEqual(got[0]["machine"], "mlab1-eze01")
        self.assertEqual(got[0]["city"], "Buenos Aires")
        self.assertIn("/download?access_token=", got[0]["down"])

    def test_locate_errors(self):
        with self.assertRaises(sp.SpeedError):
            mlab.locate(Locator(fail=True))
        with self.assertRaises(sp.SpeedError):
            mlab.locate(Locator([]))

    def test_pick_wants_the_same_machine_for_every_stream(self):
        flat = lambda url: 10.0
        got = mlab.pick(Locator(["a", "b"], ["b", "a"]), streams=2, rtt=flat)
        self.assertEqual([m["machine"] for m in got], ["a", "a"])
        got = mlab.pick(Locator(["a"], ["c"]), streams=2, rtt=flat)   # not offered again: the nearest one
        self.assertEqual([m["machine"] for m in got], ["a", "c"])

    def test_pick_prefers_the_shortest_round_trip(self):
        rtts = {"scl": 118.0, "eze": 28.0, "gru": None}           # gru didn't answer
        rtt = lambda url: next(v for k, v in rtts.items() if k in url)
        got = mlab.pick(Locator(["scl", "eze", "gru"], ["eze"]), streams=2, rtt=rtt)
        self.assertEqual([m["machine"] for m in got], ["eze", "eze"])

    def test_upload_frame_is_a_masked_binary_message(self):
        for size, header in ((100, 2), (1000, 4), (1 << 20, 10)):
            f = mlab.upload_frame(size)
            self.assertEqual(f[0], 0x82)                 # FIN + binary
            self.assertTrue(f[1] & 0x80)                 # masked, as a client must
            self.assertEqual(len(f), header + 4 + size)
        self.assertEqual(int.from_bytes(mlab.upload_frame(1 << 20)[2:10], "big"), 1 << 20)


class Engine(unittest.TestCase):
    def test_download_and_upload_stop_at_the_cap(self):
        log = {}
        r = mlab.run(40_000_000, opener=Locator(["a"]), connect=fake_connect(log), rtt=lambda url: 1.0,
                     down_seconds=3, up_seconds=3, mark=lambda host: {"where": "outside", "asn": "AS64510"})
        self.assertIsNone(r["error"])
        self.assertEqual((r["engine"], r["name"], r["rtt_ms"], r["asn"]), ("mlab", "M-Lab Buenos Aires", 28.4, "AS64510"))
        self.assertGreater(r["down_mbps"], 0)
        self.assertGreater(r["up_mbps"], 0)
        # 70 % of the cap down, 30 % up; each stream may finish the block it was moving
        self.assertLessEqual(r["bytes"], 40_000_000 + mlab.STREAMS * (mlab.READ + mlab.FRAME))
        self.assertEqual(len(log["urls"]), 2 * mlab.STREAMS)

    def test_a_refusal_is_recorded_not_raised(self):
        r = mlab.run(10_000_000, opener=Locator(["a"]), connect=fake_connect({}, refuse=True), rtt=lambda url: 1.0,
                     down_seconds=1, up_seconds=1)
        self.assertIn("429", r["error"])
        self.assertIsNone(r["down_mbps"])

    def test_locate_failure_is_recorded(self):
        r = mlab.run(10_000_000, opener=Locator(fail=True), connect=fake_connect({}), down_seconds=1, up_seconds=1)
        self.assertIn("locate", r["error"])


class WithCloudflare(unittest.TestCase):
    def test_run_shares_the_cap_and_adds_mlab_as_a_server(self):
        caps = []

        def fake_mlab(cap, **kw):
            caps.append(cap)
            return {"name": "M-Lab Buenos Aires", "engine": "mlab", "where": "outside", "down_mbps": 1e9,
                    "up_mbps": 700.0, "bytes": 1000, "error": None, "rtt_ms": 28.0}
        r = sp.run(9_000_000, opener=FakeHTTP(), ping=no_ping, down_seconds=1, up_seconds=1,
                   mlab=True, mlab_run=fake_mlab)
        self.assertEqual(caps, [4_500_000])
        self.assertEqual(r.servers[0]["engine"], "mlab")
        self.assertEqual(sp.best(r.__dict__)["down_name"], "M-Lab Buenos Aires")

    def test_mlab_alone_gets_the_whole_cap_and_cloudflare_is_not_touched(self):
        caps = []

        def fake_mlab(cap, **kw):
            caps.append(cap)
            return {"name": "M-Lab Buenos Aires", "engine": "mlab", "where": "outside", "down_mbps": 930.0,
                    "up_mbps": 610.0, "bytes": 1000, "error": None, "rtt_ms": 28.0}

        def no_http(*a, **k):
            raise AssertionError("Cloudflare must not run")
        r = sp.run(9_000_000, opener=no_http, ping=no_ping, down_seconds=1, up_seconds=1,
                   mlab=True, mlab_run=fake_mlab, cloudflare=False)
        self.assertEqual(caps, [9_000_000])
        self.assertFalse(r.cloudflare)
        self.assertIsNone(r.down_mbps)
        self.assertEqual(sp.best(r.__dict__)["down"], 930.0)

    def test_off_by_default(self):
        r = sp.run(5_000_000, opener=FakeHTTP(), ping=no_ping, down_seconds=1, up_seconds=1,
                   mlab_run=lambda *a, **k: self.fail("M-Lab must not run"))
        self.assertEqual(r.servers, [])


class Best(unittest.TestCase):
    def test_the_best_of_every_engine(self):
        res = {"down_mbps": 325.0, "up_mbps": 133.0, "servers": [
            {"name": "M-Lab Buenos Aires", "down_mbps": 929.0, "up_mbps": 120.0},
            {"name": "broken", "down_mbps": 5000.0, "error": "timeout"}]}
        self.assertEqual(sp.best(res), {"down": 929.0, "down_name": "M-Lab Buenos Aires",
                                        "up": 133.0, "up_name": sp.SERVER})

    def test_cloudflare_failed_but_mlab_worked(self):
        res = {"error": "speed.cloudflare.com: 429", "down_mbps": None, "servers": [
            {"name": "M-Lab", "down_mbps": 900.0, "up_mbps": 600.0}]}
        self.assertEqual(sp.best(res)["down"], 900.0)
        self.assertIsNone(sp.best({"error": "x"})["down"])


class Choice(unittest.TestCase):
    def test_the_engine_decides_what_runs(self):
        self.assertEqual(sp.uses(ON), (True, False))                                   # Cloudflare by default
        self.assertEqual(sp.uses({**ON, "engine": "mlab", "mlab_accepted": True}), (False, True))
        self.assertEqual(sp.uses({**ON, "engine": "both", "mlab_accepted": True}), (True, True))
        self.assertEqual(sp.uses({**ON, "engine": "mlab"}), (True, False))             # no consent: Cloudflare
        old = {k: v for k, v in ON.items() if k != "engine"}
        self.assertEqual(sp.engine_of({**old, "mlab": True}), "both")                   # saved before 0.7.1
        self.assertEqual(sp.engines({**ON, "engine": "mlab", "mlab_accepted": True}), 1)
        only = {**ON, "engine": "command"}
        self.assertEqual(sp.uses(only), (False, False))                                 # only your command
        self.assertEqual(sp.uses(only, command=False), (True, False))                   # none set: Cloudflare
        self.assertEqual(sp.per_test_bytes(only), 0)
        self.assertGreater(sp.per_test_bytes(only, command=False), 0)
        self.assertIsNone(sp.budget_short(only, 1000, 600))

    def test_validate_keeps_the_choice(self):
        got = sp.validate({"enabled": True, "accepted": True, "engine": "mlab", "mlab_accepted": True}, ON)
        self.assertEqual((got["engine"], got["mlab"], got["mlab_accepted"]), ("mlab", True, True))
        with self.assertRaises(ValueError):
            sp.validate({"enabled": True, "accepted": True, "engine": "ookla"}, ON)
        back = sp.validate({"enabled": True, "accepted": True, "engine": "cloudflare"}, got)
        self.assertFalse(back["mlab"] or back["mlab_accepted"])


class Consent(unittest.TestCase):
    def test_mlab_needs_its_own_consent(self):
        with self.assertRaises(ValueError):
            sp.validate({"enabled": True, "accepted": True, "mlab": True}, ON)
        got = sp.validate({"enabled": True, "accepted": True, "mlab": True, "mlab_accepted": True}, ON)
        self.assertTrue(got["mlab"] and got["mlab_accepted"])
        off = sp.validate({"enabled": True, "accepted": True}, got)       # unticked: off, consent forgotten
        self.assertFalse(off["mlab"] or off["mlab_accepted"])

    def test_runner_passes_mlab_only_with_consent(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(Path(tmp) / "s.db")
            try:
                for cfg, want, cf in (({**ON, "schedule": "manual", "mlab": True, "mlab_accepted": True}, True, True),
                                      ({**ON, "schedule": "manual", "mlab": True, "mlab_accepted": False}, False, True),
                                      ({**ON, "schedule": "manual", "engine": "mlab", "mlab_accepted": True}, True, False),
                                      ({**ON, "schedule": "manual", "engine": "command"}, False, True)):
                    got, done = {}, threading.Event()

                    def fake_run(cap, got=got, done=done, **kw):
                        got.update(kw)
                        done.set()
                        return sp.Result(ts=time.time(), trigger=kw["trigger"])
                    runner = sp.Runner(store, run_fn=fake_run)
                    store.set_settings({"_speed_request": time.time()}, bump=False)
                    self.assertEqual(runner.tick(cfg, time.time(), wireless=False, on_backup=False, incident=False,
                                                 link_busy_pct=None, isp_asn="AS64500"), "started")
                    runner.thread.join(2)
                    self.assertEqual(got.get("mlab", False), want)
                    self.assertEqual(got.get("cloudflare", True), cf)
                    self.assertTrue(callable(got["mark"]))
            finally:
                store.close()


class Web(WebAppBase):
    def test_settings_dashboard_and_report_use_the_best(self):
        from isitmyisp.report import build_report
        self.create_admin()
        page = self.client.get("/settings").get_data(as_text=True)
        form = {"csrf_token": csrf(page), "enabled": "1", "accepted": "1", "schedule": "manual", "weekday": "6",
                "hour": "3", "budget_gb": "5", "max_busy_pct": "30", "engine": "both"}
        r = self.client.post("/settings/speedtest?lang=es", data=form)
        self.assertEqual(r.status_code, 400)
        self.assertIn("publica cada prueba con tu IP", r.get_data(as_text=True))
        self.assertEqual(self.client.post("/settings/speedtest", data={**form, "mlab_accepted": "1"}).status_code, 302)
        self.assertTrue(self.store.get_setting("speedtest")["mlab"])
        page = self.client.get("/settings/connection?lang=en").get_data(as_text=True)
        self.assertIn("about 30 seconds", page)            # Cloudflare, then M-Lab

        self.store.set_settings({"link": {"down_mbps": 1000, "up_mbps": 600}})
        self.store.add_speedtest(sp.Result(ts=time.time() - 60, down_mbps=325.0, up_mbps=133.0, servers=[
            {"name": "M-Lab Buenos Aires", "engine": "mlab", "where": "outside", "asn": "AS64510",
             "down_mbps": 929.0, "up_mbps": 610.0, "bytes": 1, "error": None, "rtt_ms": 28.0}]))
        page = self.client.get("/?lang=en").get_data(as_text=True)
        self.assertIn("<b>929</b> Mbps", page)
        self.assertIn("93% of 1000 Mbps", page)
        self.assertIn("Best figure, from M-Lab Buenos Aires", page)
        self.assertIn("28 ms", page)
        html = build_report(self.store, time.time() - 3600, time.time(), "en")
        self.assertIn("929 Mbps (93%)", html)
        self.assertNotIn("325 Mbps (32%)", html)

    def test_mlab_only_hides_the_cloudflare_row(self):
        self.create_admin()
        self.store.set_settings({"speedtest": {**ON, "engine": "mlab", "mlab": True, "mlab_accepted": True}})
        self.store.add_speedtest(sp.Result(ts=time.time() - 60, cloudflare=False, servers=[
            {"name": "M-Lab Buenos Aires", "engine": "mlab", "where": "outside", "down_mbps": 930.0,
             "up_mbps": 610.0, "bytes": 1, "error": None, "rtt_ms": 28.0}]))
        page = self.client.get("/?lang=en").get_data(as_text=True)
        self.assertIn("<b>930</b> Mbps", page)
        self.assertNotIn("speed.cloudflare.com", page)
        page = self.client.get("/settings/connection?lang=en").get_data(as_text=True)
        self.assertIn('value="mlab" checked', page)

    def test_the_wizard_asks_for_the_engine(self):
        self.create_admin()
        page = self.client.get("/welcome/speed?lang=en").get_data(as_text=True)
        self.assertIn('value="cloudflare" checked', page)
        skip = self.client.post("/welcome/speed", data={"csrf_token": csrf(page), "action": "skip"})
        self.assertTrue(skip.headers["Location"].endswith("/welcome/done"))
        self.assertFalse((self.store.get_setting("speedtest") or {}).get("enabled"))
        bad = self.client.post("/welcome/speed", data={"csrf_token": csrf(page), "action": "save", "engine": "mlab",
                                                       "accepted": "1"})
        self.assertEqual(bad.status_code, 400)
        ok = self.client.post("/welcome/speed", data={"csrf_token": csrf(page), "action": "save", "engine": "mlab",
                                                      "accepted": "1", "mlab_accepted": "1"})
        self.assertTrue(ok.headers["Location"].endswith("/welcome/done"))
        cfg = self.store.get_setting("speedtest")
        self.assertEqual((cfg["enabled"], cfg["engine"], cfg["mlab_accepted"]), (True, "mlab", True))
        self.assertIn("M-Lab", self.client.get("/welcome/done?lang=en").get_data(as_text=True))


if __name__ == "__main__":
    unittest.main()
