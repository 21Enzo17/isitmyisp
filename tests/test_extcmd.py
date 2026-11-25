"""#115: the user's own speed test command, set in the config file only, and the outputs it understands."""
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from isitmyisp import extcmd
from isitmyisp import speedtest as sp
from isitmyisp.config import COMMAND_ENV, ConfigError, SpeedCommand, load, speed_command
from isitmyisp.store import Store
from tests.test_speedtest import ON, FakeHTTP, no_ping
from tests.test_webapp import WebAppBase

OOKLA = {"type": "result", "timestamp": "2026-11-22T06:00:00Z",
         "ping": {"jitter": 0.3, "latency": 1.512, "low": 1.2, "high": 2.0},
         "download": {"bandwidth": 117_375_000, "bytes": 1_200_000_000, "elapsed": 10_000},
         "upload": {"bandwidth": 94_375_000, "bytes": 900_000_000, "elapsed": 10_000},
         "packetLoss": 0, "isp": "Telecom Argentina",
         "server": {"id": 1, "host": "speedtest.example.ar:8080", "port": 8080, "name": "Personal",
                    "location": "Buenos Aires", "country": "Argentina", "ip": "181.0.0.9"},
         "result": {"id": "x", "url": "https://www.speedtest.net/result/c/x", "persisted": True}}
LIBRESPEED = [{"timestamp": "2026-11-22T06:00:00Z", "server": {"name": "Frankfurt (Clouvider)",
               "url": "https://fra.speedtest.example.net/backend"}, "client": {"ip": "203.0.113.1"},
               "bytes_sent": 124_059_648, "bytes_received": 150_994_944, "ping": 20.5, "jitter": 1.2,
               "upload": 95.2, "download": 118.4, "share": ""}]
SPEEDTEST_CLI = {"download": 72_624_789.16, "upload": 201_893_290.67, "ping": 82.415,
                 "server": {"url": "http://speed.example.br:8080/speedtest/upload.php", "name": "Vila Velha",
                            "country": "Brazil", "cc": "BR", "sponsor": "Loga", "id": "36722",
                            "host": "speed.example.br:8080", "latency": 82.415},
                 "timestamp": "2026-11-25T18:49:40Z", "bytes_sent": 151_519_232, "bytes_received": 91_000_208,
                 "share": None, "client": {"isp": "Personal", "country": "AR"}}
IPERF_DOWN = {"start": {"connected": [{"remote_host": "10.8.0.1"}], "test_start": {"reverse": 1}},
              "end": {"streams": [{"sender": {"mean_rtt": 2100}}],
                      "sum_sent": {"bytes": 1_100_000_100, "bits_per_second": 8.9e8},
                      "sum_received": {"bytes": 1_100_000_000, "bits_per_second": 8.8e8}}}
IPERF_BIDIR = {"start": {"connected": [{"remote_host": "10.8.0.1"}], "test_start": {"reverse": 0}},
               "end": {"sum_sent": {"bytes": 500}, "sum_received": {"bytes": 600, "bits_per_second": 5e8},
                       "sum_sent_bidir_reverse": {"bytes": 700},
                       "sum_received_bidir_reverse": {"bytes": 800, "bits_per_second": 9e8}}}


def proc(out="", err="", code=0):
    return subprocess.CompletedProcess([], code, out, err)


class Parse(unittest.TestCase):
    def test_ookla(self):
        fmt, got = extcmd.parse(json.dumps(OOKLA))
        self.assertEqual(fmt, "ookla")
        self.assertEqual((got["down_mbps"], got["up_mbps"], got["ping_ms"]), (939.0, 755.0, 1.5))
        self.assertEqual(got["bytes"], 2_100_000_000)
        self.assertEqual((got["host"], got["server"]), ("181.0.0.9", "Personal (Buenos Aires, Argentina)"))

    def test_librespeed(self):
        fmt, got = extcmd.parse(json.dumps(LIBRESPEED))
        self.assertEqual(fmt, "librespeed")
        self.assertEqual((got["down_mbps"], got["up_mbps"], got["ping_ms"]), (118.4, 95.2, 20.5))
        self.assertEqual(got["host"], "fra.speedtest.example.net")

    def test_the_python_speedtest_cli_is_bits_per_second(self):
        fmt, got = extcmd.parse(json.dumps(SPEEDTEST_CLI))   # same fields as librespeed's, other units
        self.assertEqual(fmt, "speedtest-cli")
        self.assertEqual((got["down_mbps"], got["up_mbps"], got["ping_ms"]), (72.6, 201.9, 82.4))
        self.assertEqual((got["host"], got["server"]), ("speed.example.br", "Loga (Vila Velha, Brazil)"))

    def test_iperf3_one_way_and_both(self):
        fmt, got = extcmd.parse(json.dumps(IPERF_DOWN))
        self.assertEqual((fmt, got["down_mbps"], got["up_mbps"], got["ping_ms"]), ("iperf3", 880.0, None, 2.1))
        _, got = extcmd.parse(json.dumps(IPERF_BIDIR))
        self.assertEqual((got["down_mbps"], got["up_mbps"], got["bytes"]), (900.0, 500.0, 600 + 800))
        with self.assertRaises(extcmd.ParseError):
            extcmd.parse(json.dumps({"start": {}, "end": {}, "error": "unable to connect to server"}))

    def test_plain_json_after_progress_lines(self):
        out = "measuring...\n50%\n" + json.dumps({"download_mbps": 930, "upload_mbps": 600, "server": "Mine"})
        fmt, got = extcmd.parse(out)
        self.assertEqual((fmt, got["down_mbps"], got["server"]), ("json", 930.0, "Mine"))

    def test_what_is_not_a_result(self):
        for text in ("", "Speedtest by Ookla\n Download: 939 Mbps", "[]", json.dumps({"hello": 1}),
                     json.dumps({"download_mbps": "fast"}), json.dumps({"download_mbps": -5})):
            with self.subTest(text=text), self.assertRaises(extcmd.ParseError):
                extcmd.parse(text)
        with self.assertRaises(extcmd.ParseError):    # forced to the wrong format
            extcmd.parse(json.dumps(LIBRESPEED), "ookla")


class Run(unittest.TestCase):
    def test_ookla_result_as_a_server(self):
        calls, marked = [], []

        def runner(argv, **kw):
            calls.append((argv, kw))
            return proc(json.dumps(OOKLA))
        cmd = SpeedCommand(("speedtest", "-f", "json", "--accept-license"))
        r = extcmd.run(cmd, runner=runner, mark=lambda h: marked.append(h) or {"where": "inside", "asn": "AS7303"})
        self.assertEqual(calls[0][0], ["speedtest", "-f", "json", "--accept-license"])
        self.assertNotIn("shell", calls[0][1])
        self.assertEqual(calls[0][1]["timeout"], 120)
        self.assertEqual(r["name"], "Ookla · Personal (Buenos Aires, Argentina)")
        self.assertEqual((r["engine"], r["down_mbps"], r["up_mbps"], r["rtt_ms"]), ("command", 939.0, 755.0, 1.5))
        self.assertEqual((r["where"], r["asn"], r["bytes"], r["error"]), ("inside", "AS7303", 2_100_000_000, None))
        self.assertEqual(r["url"], "https://www.speedtest.net/result/c/x")
        self.assertEqual(marked, ["181.0.0.9"])

    def test_bytes_estimated_when_the_tool_does_not_say(self):
        r = extcmd.run(SpeedCommand(("x",), name="Mine"), runner=lambda a, **k: proc('{"download_mbps": 800}'))
        self.assertEqual(r["name"], "Mine")
        self.assertEqual(r["bytes"], int(800 * sp.DOWN_SECONDS * 1e6 / 8))

    def test_failures_are_recorded(self):
        def missing(argv, **kw):
            raise FileNotFoundError(argv[0])

        def slow(argv, **kw):
            raise subprocess.TimeoutExpired(argv, kw["timeout"])
        log = '{"type":"log","timestamp":"x","message":"Configuration - Could not retrieve or read configuration","level":"error"}'
        cases = ((missing, "command not found"), (slow, "no result after 120 s"),
                 (lambda a, **k: proc("", log, 2), "Could not retrieve or read configuration"),
                 (lambda a, **k: proc("Download: 939 Mbps"), "not JSON"),
                 (lambda a, **k: proc("", "speedtest: error: unrecognized arguments: -f json"), "unrecognized arguments"))
        for runner, why in cases:
            with self.subTest(why=why):
                r = extcmd.run(SpeedCommand(("speedtest",)), runner=runner)
                self.assertIn(why, r["error"])
                self.assertFalse(r["error"].startswith("speedtest: speedtest:"))
                self.assertIsNone(r["down_mbps"])
                self.assertEqual(r["bytes"], 0)

    def test_a_real_process(self):
        script = "import json; print('warming up'); print(json.dumps({'download_mbps': 812.5, 'upload_mbps': 401}))"
        r = extcmd.run(SpeedCommand((sys.executable, "-c", script), name="Script"))
        self.assertIsNone(r["error"])
        self.assertEqual((r["down_mbps"], r["up_mbps"]), (812.5, 401.0))
        r = extcmd.run(SpeedCommand((sys.executable, "-c", "import sys; sys.exit('no server')")))
        self.assertEqual(r["error"], f"{os.path.basename(sys.executable)}: no server")


class Config(unittest.TestCase):
    def test_list_or_string(self):
        self.assertEqual(speed_command({"command": ["speedtest", "-f", "json"]}).argv, ("speedtest", "-f", "json"))
        got = speed_command({"command": "librespeed-cli --json --server 'my server'", "name": "LS", "timeout": 60})
        self.assertEqual(got.argv, ("librespeed-cli", "--json", "--server", "my server"))
        self.assertEqual((got.name, got.timeout, got.text()), ("LS", 60, "librespeed-cli --json --server 'my server'"))
        self.assertIsNone(speed_command({}))

    def test_bad_values(self):
        for raw in ({"command": 5}, {"command": ["a", 1]}, {"command": "a 'b"}, {"command": "x", "format": "csv"},
                    {"command": "x", "timeout": 1}, {"command": "x", "timeout": "soon"}, {"command": [""]}):
            with self.subTest(raw=raw), self.assertRaises(ConfigError):
                speed_command(raw)

    def test_file_and_environment(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.toml"
            path.write_text('[speedtest]\ncommand = ["speedtest", "-f", "json"]\nname = "Ookla"\ntimeout = 90\n')
            with mock.patch.dict(os.environ, {COMMAND_ENV: ""}):
                self.assertEqual(load(str(path), Path(tmp)).speed_command.argv, ("speedtest", "-f", "json"))
            with mock.patch.dict(os.environ, {COMMAND_ENV: "/opt/speedtest -f json"}):
                got = load(str(path), Path(tmp)).speed_command          # the environment wins, the rest stays
                self.assertEqual((got.argv, got.name, got.timeout), (("/opt/speedtest", "-f", "json"), "Ookla", 90))
                empty = Path(tmp) / "empty"
                empty.mkdir()
                self.assertEqual(load(None, empty).speed_command.argv[0], "/opt/speedtest")   # no file at all

    def test_never_from_the_web_form(self):
        got = sp.validate({"enabled": True, "accepted": True, "command": ["rm", "-rf", "/"]}, ON)
        self.assertNotIn("command", got)


class WithTheOthers(unittest.TestCase):
    def test_runs_last_and_counts_its_bytes(self):
        seen = []

        def fake(command, mark=None):
            seen.append(command)
            return {"name": "Ookla · Personal", "engine": "command", "down_mbps": 1e9, "up_mbps": 755.0,
                    "bytes": 2_000_000_000, "error": None, "rtt_ms": 1.5}
        cmd = SpeedCommand(("speedtest",))
        r = sp.run(5_000_000, opener=FakeHTTP(), ping=no_ping, down_seconds=1, up_seconds=1,
                   command=cmd, command_run=fake)
        self.assertEqual(seen, [cmd])
        self.assertEqual(r.servers[-1]["engine"], "command")
        self.assertGreater(r.bytes_used, 2_000_000_000)
        self.assertEqual(sp.best(r.__dict__)["down_name"], "Ookla · Personal")

    def test_runner_passes_it_on(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(Path(tmp) / "s.db")
            try:
                got, done = {}, threading.Event()

                def fake_run(cap, **kw):
                    got.update(kw)
                    done.set()
                    return sp.Result(ts=time.time(), trigger=kw["trigger"])
                runner = sp.Runner(store, run_fn=fake_run)
                store.set_settings({"_speed_request": time.time()}, bump=False)
                cmd = SpeedCommand(("speedtest",))
                self.assertEqual(runner.tick({**ON, "schedule": "manual"}, time.time(), wireless=False, on_backup=False,
                                             incident=False, link_busy_pct=None, isp_asn="AS7303", command=cmd), "started")
                runner.thread.join(2)
                self.assertIs(got["command"], cmd)
                self.assertTrue(callable(got["mark"]))
            finally:
                store.close()


class Web(WebAppBase):
    def test_settings_show_it_and_the_dashboard_uses_it(self):
        self.create_admin()
        page = self.client.get("/settings/connection?lang=en").get_data(as_text=True)
        self.assertIn("[speedtest] command", page)                    # how to set one; no field to type it in
        self.assertNotIn('name="command"', page)
        (Path(self.tmp.name) / "config.toml").write_text(
            '[speedtest]\ncommand = ["speedtest", "-f", "json", "--accept-license"]\n')
        with mock.patch.dict(os.environ, {COMMAND_ENV: ""}):
            page = self.client.get("/settings/connection?lang=en").get_data(as_text=True)
            self.assertIn("<code>speedtest -f json --accept-license</code>", page)
            self.assertIn("Set in the config file", page)
            self.store.set_settings({"link": {"down_mbps": 1000, "up_mbps": 600}, "speedtest": {**ON, "schedule": "manual"}})
            self.store.add_speedtest(sp.Result(ts=time.time() - 60, down_mbps=325.0, up_mbps=133.0, servers=[
                {"name": "Ookla · Personal (Buenos Aires)", "engine": "command", "where": "inside", "asn": "AS7303",
                 "down_mbps": 939.0, "up_mbps": 755.0, "bytes": 1, "error": None, "rtt_ms": 1.5}]))
            page = self.client.get("/?lang=en").get_data(as_text=True)
            self.assertIn("<b>939</b> Mbps", page)
            self.assertIn("Best figure, from Ookla · Personal (Buenos Aires)", page)


if __name__ == "__main__":
    unittest.main()
